"""Offline GUI restoration with dummy bytes; no installers or network access."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui
from vpn_common import ClientError


def digest(data):
    return hashlib.sha256(data).hexdigest()


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vpn gui test ')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'repo'
        self.bundle = self.root / 'vendor' / 'gui' / 'dummy'
        self.bundle.mkdir(parents=True)
        self.output = self.base / 'downloads'
        chunks = (b'dummy installer first half\x00', b'second half\xff')
        self.data = b''.join(chunks)
        parts = []
        for index, chunk in enumerate(chunks, 1):
            part = self.bundle / f'archive.part{index:03}'
            part.write_bytes(chunk)
            parts.append({'path': part.relative_to(self.root).as_posix(), 'sha256': digest(chunk), 'size': len(chunk)})
        self.package = {
            'platform': 'windows-amd64', 'filename': 'dummy-installer.zip',
            'sha256': digest(self.data), 'size': len(self.data),
            'sourceUrl': 'https://example.test/releases/dummy-installer.zip', 'parts': parts,
        }
        self.app = {'id': 'dummy', 'name': 'Dummy GUI', 'version': '1.2.3', 'license': 'Test-only',
                    'sourceUrl': 'https://example.test/dummy', 'packages': [self.package]}
        self.manifest = {'schemaVersion': 1, 'apps': [self.app]}
        self.manifest_path = self.bundle.parent / 'manifest.json'
        self.save_manifest()
        self.target = self.output / 'dummy' / '1.2.3' / 'windows-amd64' / 'dummy-installer.zip'
        network = patch.object(socket, 'create_connection', side_effect=AssertionError('Network forbidden'))
        self.network = network.start()
        self.addCleanup(network.stop)
        exports = patch.object(gui, 'export_gui_profiles', return_value=self.base / 'private-profiles' / 'VLESS-HY2.txt')
        self.exports = exports.start()
        self.addCleanup(exports.stop)

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def restore(self):
        return gui.restore_package(self.app, self.package, self.output, root=self.root)

    def assert_no_partial(self):
        self.assertEqual(list(self.output.rglob('*.partial')), [])
        self.assertFalse(self.target.exists())

    def symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation requires OS support/permission')

    def link_package(self):
        self.package.pop('parts')
        self.package['sourceUrl'] = 'https://github.com/example/app/releases/download/v1/dummy.zip'

    def test_link_default_only_displays_official_urls(self):
        self.link_package()
        with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'download') as get, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(gui.main(['--app', 'dummy', '--platform', 'windows-amd64']), 0)
        get.assert_not_called()
        self.exports.assert_not_called()
        self.assertIn(self.package['sourceUrl'], output.getvalue())
        self.assertIn('--download', output.getvalue())

    def test_link_requires_explicit_download_and_verifies_cache(self):
        self.link_package()
        with patch.object(gui, 'download') as get, self.assertRaisesRegex(ClientError, '--download'):
            self.restore()
        get.assert_not_called()
        def get(url, destination, limit):
            self.assertEqual(limit, len(self.data))
            destination.write_bytes(self.data)
        with patch.object(gui, 'download', side_effect=get) as download:
            self.assertEqual(gui.restore_package(self.app, self.package, self.output, root=self.root, allow_download=True), self.target)
            self.assertEqual(self.restore(), self.target)
            download.assert_called_once()
        self.assertEqual(self.target.read_bytes(), self.data)
        self.target.write_bytes(b'modified')
        with patch.object(gui, 'download') as get, self.assertRaisesRegex(ClientError, 'not be overwritten'):
            gui.restore_package(self.app, self.package, self.output, root=self.root, allow_download=True)
        get.assert_not_called()

    def test_bad_download_never_publishes_or_leaves_partial(self):
        self.link_package()
        def bad(url, destination, limit):
            destination.write_bytes(b'x' * len(self.data))
        with patch.object(gui, 'download', side_effect=bad), self.assertRaisesRegex(ClientError, 'checksum'):
            gui.restore_package(self.app, self.package, self.output, root=self.root, allow_download=True)
        self.assert_no_partial()

    def test_link_hosts_are_vetted(self):
        self.link_package()
        self.package['sourceUrl'] = 'https://example.test/not-official.zip'
        with self.assertRaisesRegex(ClientError, 'official HTTPS'):
            gui._validate_package(self.package)

    def test_manifest_and_multipart_round_trip_without_network_or_processes(self):
        self.assertEqual(gui.load_manifest(self.root), self.manifest)
        with patch.object(gui.subprocess, 'run', side_effect=AssertionError('Process forbidden')):
            self.assertEqual(self.restore(), self.target)
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertEqual(list(self.output.rglob('*.partial')), [])
        self.network.assert_not_called()

    def test_single_file_package_is_supported(self):
        source = self.bundle.parent / 'single.zip'
        source.write_bytes(self.data)
        self.package['parts'] = [{'path': source.relative_to(self.root).as_posix(), 'size': len(self.data), 'sha256': digest(self.data)}]
        self.restore()
        self.assertEqual(self.target.read_bytes(), self.data)

    def add_companion(self):
        data = b'dummy offline runtime'
        source = self.bundle / 'runtime.part001'
        source.write_bytes(data)
        companion = {'filename': 'runtime.exe', 'sha256': digest(data), 'size': len(data),
                     'sourceUrl': 'https://example.test/runtime.exe', 'installOrder': 1,
                     'description': 'Offline runtime. Install first if missing.',
                     'parts': [{'path': source.relative_to(self.root).as_posix(), 'sha256': digest(data), 'size': len(data)}]}
        self.package['companions'] = [companion]
        return companion, source, data

    def test_companion_restored_before_main_and_reused(self):
        companion, source, data = self.add_companion()
        self.save_manifest()
        self.assertEqual(gui.load_manifest(self.root), self.manifest)
        original = gui._copy_checked
        copied = []
        def record(path, *args, **kwargs):
            copied.append(path)
            return original(path, *args, **kwargs)
        with patch.object(gui, '_copy_checked', side_effect=record):
            self.assertEqual(self.restore(), self.target)
        self.assertEqual(copied[0], source)
        runtime = self.target.parent / companion['filename']
        self.assertEqual(runtime.read_bytes(), data)
        with patch.object(gui.tempfile, 'mkstemp', side_effect=AssertionError('Unexpected write')):
            self.restore()
        self.network.assert_not_called()

    def test_missing_or_tampered_companion_prevents_success_and_profile_export(self):
        companion, source, data = self.add_companion()
        original = gui.restore_package
        def restore_test_root(app, package, output_dir=None, *, root=None):
            return original(app, package, output_dir, root=self.root)
        for missing in (False, True):
            if missing:
                source.unlink()
            else:
                source.write_bytes(b'x' * len(data))
            with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'restore_package', side_effect=restore_test_root), redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
                self.assertEqual(gui.main(['--app', 'dummy', '--platform', 'windows-amd64', '--output-dir', str(self.output), '--export-profiles', '--no-open']), 1)
            self.assert_no_partial()
            self.assertNotIn('Verified', output.getvalue())
            self.exports.assert_not_called()

    def test_existing_tampered_companion_refuses_overwrite_and_main_reuse(self):
        companion, _, _ = self.add_companion()
        self.restore()
        runtime = self.target.parent / companion['filename']
        runtime.write_bytes(b'preserve existing runtime')
        with self.assertRaisesRegex(ClientError, 'not be overwritten'):
            self.restore()
        self.assertEqual(runtime.read_bytes(), b'preserve existing runtime')
        self.assertEqual(self.target.read_bytes(), self.data)

    def test_companion_validation_bounds_nesting_platform_and_filename_collisions(self):
        companion, _, _ = self.add_companion()
        for field, value in (('filename', self.package['filename'].upper()), ('filename', '../runtime.exe'),
                             ('platform', 'darwin-arm64'), ('companions', []), ('installOrder', True),
                             ('installOrder', 0), ('installOrder', 5), ('description', 'bad\x1bdescription')):
            changed = copy.deepcopy(companion)
            changed[field] = value
            self.package['companions'] = [changed]
            with self.subTest(field=field, value=value), self.assertRaises(ClientError):
                self.restore()
        for companions in ([companion] * 5, [companion, copy.deepcopy(companion)], 'invalid', [None]):
            self.package['companions'] = companions
            with self.assertRaises(ClientError):
                self.restore()
        self.assertFalse(self.output.exists())

    def test_companion_instructions_precede_main_installer(self):
        companion, _, _ = self.add_companion()
        with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'restore_package', return_value=self.target), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(gui.main(['--app', 'dummy', '--platform', 'windows-amd64', '--no-open']), 0)
        text = output.getvalue()
        self.assertIn('Install first (1): ' + companion['description'], text)
        self.assertIn(str(self.target.parent / companion['filename']), text)
        self.assertLess(text.index('Verified companion'), text.index('Verified installer'))

    def test_valid_existing_file_is_reused_without_writing(self):
        self.restore()
        timestamp = self.target.stat().st_mtime_ns
        with patch.object(gui.tempfile, 'mkstemp', side_effect=AssertionError('Unexpected output write')):
            self.assertEqual(self.restore(), self.target)
        self.assertEqual(self.target.stat().st_mtime_ns, timestamp)

    def test_different_existing_file_is_not_overwritten(self):
        self.restore()
        self.target.write_bytes(b'preserve user bytes')
        with self.assertRaisesRegex(ClientError, 'not be overwritten'):
            self.restore()
        self.assertEqual(self.target.read_bytes(), b'preserve user bytes')

    def test_existing_directory_is_not_overwritten(self):
        self.target.mkdir(parents=True)
        with self.assertRaisesRegex(ClientError, 'not be overwritten'):
            self.restore()
        self.assertTrue(self.target.is_dir())

    def test_tampered_part_same_size_is_rejected_and_partial_removed(self):
        source = self.root / self.package['parts'][1]['path']
        source.write_bytes(b'x' * source.stat().st_size)
        with self.assertRaisesRegex(ClientError, 'checksum'):
            self.restore()
        self.assert_no_partial()

    def test_part_size_mismatch_is_rejected_before_output(self):
        source = self.root / self.package['parts'][1]['path']
        source.write_bytes(b'truncated')
        with self.assertRaisesRegex(ClientError, 'size'):
            self.restore()
        self.assertFalse(self.output.exists())

    def test_combined_checksum_is_verified(self):
        self.package['sha256'] = 'a' * 64
        with self.assertRaisesRegex(ClientError, 'Assembled GUI checksum'):
            self.restore()
        self.assert_no_partial()

    def test_interruption_removes_partial_bytes(self):
        original = gui._copy_checked
        calls = 0
        def interrupted(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return original(*args, **kwargs)
        with patch.object(gui, '_copy_checked', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.restore()
        self.assert_no_partial()

    def test_publish_failure_cleans_partial(self):
        with patch.object(gui.os, 'link', side_effect=OSError('test failure')), self.assertRaises(OSError):
            self.restore()
        self.assert_no_partial()

    def test_publish_race_never_replaces_existing_file(self):
        def competing_writer(source, target):
            target.write_bytes(b'competing writer')
            raise FileExistsError
        with patch.object(gui.os, 'link', side_effect=competing_writer), self.assertRaisesRegex(ClientError, 'not be overwritten'):
            self.restore()
        self.assertEqual(self.target.read_bytes(), b'competing writer')
        self.assertEqual(list(self.output.rglob('*.partial')), [])

    def test_output_inside_repository_rejected_even_without_git_marker(self):
        self.output = self.root / 'output'
        with self.assertRaisesRegex(ClientError, 'outside the repository'):
            self.restore()
        self.assertFalse(self.output.exists())

    def test_output_inside_other_git_checkout_or_worktree_rejected(self):
        other = self.base / 'other'
        other.mkdir()
        marker = other / '.git'
        for directory in (True, False):
            if directory:
                marker.mkdir()
            else:
                marker.write_text('gitdir: elsewhere')
            self.output = other / 'output'
            with self.assertRaisesRegex(ClientError, 'outside Git'):
                self.restore()
            self.assertFalse(self.output.exists())
            if directory:
                marker.rmdir()
            else:
                marker.unlink()

    def test_output_symlink_is_rejected(self):
        elsewhere = self.base / 'elsewhere'
        elsewhere.mkdir()
        self.symlink(self.output, elsewhere, directory=True)
        with self.assertRaisesRegex(ClientError, 'symbolic links'):
            self.restore()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_part_symlink_is_rejected(self):
        part = self.root / self.package['parts'][0]['path']
        saved = part.read_bytes()
        part.unlink()
        elsewhere = self.base / 'elsewhere'
        elsewhere.write_bytes(saved)
        self.symlink(part, elsewhere)
        with self.assertRaisesRegex(ClientError, 'symbolic links'):
            self.restore()
        self.assertFalse(self.output.exists())

    def test_output_file_symlink_is_rejected_even_when_bytes_match(self):
        self.target.parent.mkdir(parents=True)
        elsewhere = self.base / 'elsewhere'
        elsewhere.write_bytes(self.data)
        self.symlink(self.target, elsewhere)
        with self.assertRaisesRegex(ClientError, 'symbolic links'):
            self.restore()
        self.assertEqual(elsewhere.read_bytes(), self.data)

    def test_manifest_symlink_is_rejected(self):
        elsewhere = self.base / 'elsewhere.json'
        elsewhere.write_bytes(self.manifest_path.read_bytes())
        self.manifest_path.unlink()
        self.symlink(self.manifest_path, elsewhere)
        with self.assertRaisesRegex(ClientError, 'symbolic links'):
            gui.load_manifest(self.root)

    def test_reparse_point_is_rejected(self):
        class Info:
            st_mode = 0o040700
            st_file_attributes = 0x400
        self.assertTrue(gui._is_link(Info()))

    def test_unsafe_part_paths_are_rejected(self):
        for path in ('/tmp/file', '../outside', 'vendor/gui/../outside', 'vendor/gui//file',
                     'C:/outside/file', 'vendor\\gui\\outside', 'vendor/gui/x/C:stream', 'vendor/gui/CON/part'):
            with self.subTest(path=path):
                self.package['parts'][0]['path'] = path
                with self.assertRaises(ClientError):
                    self.restore()
        self.assertFalse(self.output.exists())

    def test_unsafe_output_components_are_rejected(self):
        for field in ('id', 'version', 'filename'):
            entry = self.package if field == 'filename' else self.app
            original = entry[field]
            for value in ('../escape', '/absolute', 'C:\\outside', 'NUL.zip', 'COM1', 'name.', 'name ', 'x:stream'):
                with self.subTest(field=field, value=value):
                    entry[field] = value
                    with self.assertRaises(ClientError):
                        self.restore()
            entry[field] = original
        self.assertFalse(self.output.exists())

    def test_invalid_sizes_digests_and_part_totals_are_rejected(self):
        for field, value in (('size', True), ('size', -1), ('size', 0), ('size', '42'),
                             ('size', gui.MAX_PACKAGE_BYTES + 1), ('size', len(self.data) + 1),
                             ('sha256', 'abc'), ('sha256', None)):
            with self.subTest(field=field, value=value):
                package = copy.deepcopy(self.package)
                package[field] = value
                with self.assertRaises(ClientError):
                    gui.restore_package(self.app, package, self.output, root=self.root)
        self.assertFalse(self.output.exists())

    def test_part_size_bound_and_count_are_enforced(self):
        self.package['parts'][0]['size'] = gui.MAX_PART_BYTES + 1
        with self.assertRaisesRegex(ClientError, 'size'):
            self.restore()
        self.package['parts'] = [{}] * 257
        with self.assertRaisesRegex(ClientError, 'bounded'):
            self.restore()

    def test_manifest_size_bound_and_invalid_json(self):
        for data in (b'x' * (gui.MAX_MANIFEST_BYTES + 1), b'{broken', b'\xff'):
            self.manifest_path.write_bytes(data)
            with self.assertRaises(ClientError):
                gui.load_manifest(self.root)

    def test_manifest_schema_and_duplicate_entries(self):
        for mutate in (lambda m: m.update(schemaVersion=True), lambda m: m.update(schemaVersion=2),
                       lambda m: m.update(apps=[]), lambda m: m['apps'].append(copy.deepcopy(m['apps'][0])),
                       lambda m: m['apps'][0]['packages'].append(copy.deepcopy(m['apps'][0]['packages'][0])),
                       lambda m: m['apps'][0]['packages'][0].update(platform=[]),
                       lambda m: m['apps'][0].update(name='bad\x1bname'),
                       lambda m: m['apps'][0].update(sourceUrl='https://user:password@example.test')):
            original = copy.deepcopy(self.manifest)
            mutate(self.manifest)
            self.save_manifest()
            with self.assertRaises(ClientError):
                gui.load_manifest(self.root)
            self.manifest = original

    def test_package_requirements_are_validated_and_displayed(self):
        notes = ['Linux system libraries are not bundled.', 'Install required distribution packages separately.']
        self.package['requirements'] = notes
        self.save_manifest()
        self.assertEqual(gui.load_manifest(self.root)['apps'][0]['packages'][0]['requirements'], notes)
        with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'restore_package', return_value=self.target), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(gui.main(['--app', 'dummy', '--platform', 'windows-amd64']), 0)
        for note in notes:
            self.assertIn(note, output.getvalue())
        self.assertLess(output.getvalue().index(notes[0]), output.getvalue().index('Verified installer'))
        for invalid in ('not a list', ['bad\x1bnote'], ['note'] * 33, [None]):
            self.package['requirements'] = invalid
            self.save_manifest()
            with self.assertRaises(ClientError):
                gui.load_manifest(self.root)

    def test_gui_menu_shows_only_current_platform(self):
        other = copy.deepcopy(self.app)
        other['id'] = 'other'
        other['name'] = 'Other GUI'
        other['packages'][0]['platform'] = 'darwin-arm64'
        self.manifest['apps'].append(other)
        with patch('builtins.input', side_effect=['bad', '1']), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(gui.choose_package(self.manifest, 'windows-amd64'), (self.app, self.package))
        self.assertIn('Dummy GUI 1.2.3', output.getvalue())
        self.assertNotIn('Other GUI', output.getvalue())

    def test_gui_menu_cancel_eof_and_ctrl_c(self):
        for side_effect in (['0'], EOFError):
            with patch('builtins.input', side_effect=side_effect), redirect_stdout(io.StringIO()):
                self.assertIsNone(gui.choose_package(self.manifest, 'windows-amd64'))
        with patch('builtins.input', side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            gui.choose_package(self.manifest, 'windows-amd64')

    def test_missing_platform_fails_without_fallback(self):
        with self.assertRaisesRegex(ClientError, 'No GUI installer'):
            gui.choose_package(self.manifest, 'linux-arm64')

    def test_cli_no_open_default_and_explicit_open(self):
        for flags, expected_open in (([], False), (['--no-open'], False), (['--open-folder'], True)):
            with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'restore_package', return_value=self.target) as restore, patch.object(gui, 'open_folder') as opening, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(gui.main(['--app', 'dummy', '--platform', 'windows-amd64', '--output-dir', str(self.output), *flags]), 0)
            restore.assert_called_once_with(self.app, self.package, output_dir=self.output)
            self.assertEqual(opening.called, expected_open)
            self.assertIn(str(self.target), output.getvalue())
            self.assertIn('Nothing was installed or started', output.getvalue())

    def test_interactive_cli_opens_only_folder_and_no_open_suppresses(self):
        for flags, expected_open in (([], True), (['--no-open'], False)):
            with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'platform_id', return_value='windows-amd64'), patch.object(gui, 'restore_package', return_value=self.target), patch('builtins.input', return_value='1'), patch.object(gui, 'open_folder') as opening, redirect_stdout(io.StringIO()):
                self.assertEqual(gui.main(flags), 0)
            self.assertEqual(opening.called, expected_open)
            if expected_open:
                opening.assert_called_once_with(self.target.parent)

    def test_interactive_default_exports_to_fresh_private_directory(self):
        directories = []
        for _ in range(2):
            with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'platform_id', return_value='windows-amd64'), patch.object(gui, 'restore_package', return_value=self.target), patch('builtins.input', return_value='1'), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(gui.main(['--no-open']), 0)
            app_id, directory, profiles_file = self.exports.call_args.args
            self.assertEqual(profiles_file, gui.default_profiles_file())
            self.assertEqual(app_id, 'dummy')
            self.assertEqual(directory.parent, self.target.parent)
            self.assertTrue(directory.name.startswith('profiles-'))
            self.assertFalse(directory.exists())
            directories.append(directory)
            self.assertIn('Private VPN import file:', output.getvalue())
            self.assertIn('contains VPN credentials', output.getvalue())
            self.assertIn('select a configured profile', output.getvalue())
        self.assertNotEqual(*directories)

    def test_profile_export_flags_keep_automated_restoration_read_free(self):
        for options, expected in ((['--app', 'dummy'], False), (['--app', 'dummy', '--export-profiles'], True),
                                  (['--app', 'dummy', '--no-profiles'], False), (['--no-profiles'], False)):
            self.exports.reset_mock()
            with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'platform_id', return_value='windows-amd64'), patch.object(gui, 'restore_package', return_value=self.target), patch('builtins.input', return_value='1'), redirect_stdout(io.StringIO()):
                self.assertEqual(gui.main([*options, '--no-open']), 0)
            self.assertEqual(self.exports.called, expected)

    def test_profile_export_failure_does_not_open_folder_or_claim_success(self):
        self.exports.side_effect = ClientError('Cannot create private export')
        with patch.object(gui, 'load_manifest', return_value=self.manifest), patch.object(gui, 'platform_id', return_value='windows-amd64'), patch.object(gui, 'restore_package', return_value=self.target), patch('builtins.input', return_value='1'), patch.object(gui, 'open_folder') as opening, redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(gui.main([]), 1)
        opening.assert_not_called()
        self.assertNotIn('Private VPN import file:', output.getvalue())
        self.assertIn('Verified installer:', output.getvalue())

    def test_interactive_platform_override_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            gui.main(['--platform', 'linux-amd64'])
        self.assertEqual(error.exception.code, 2)

    def test_cli_errors_do_not_echo_unknown_private_values(self):
        with patch.object(gui, 'load_manifest', return_value=self.manifest), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(gui.main(['--app', 'private-not-bundled', '--platform', 'windows-amd64']), 1)
        self.assertNotIn('private-not-bundled', output.getvalue())

    def test_ctrl_c_cli_returns_130(self):
        with patch.object(gui, 'load_manifest', side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()):
            self.assertEqual(gui.main([]), 130)


class PlatformTests(unittest.TestCase):
    def test_platform_aliases(self):
        for system, machine, expected in (('Windows', 'AMD64', 'windows-amd64'), ('Darwin', 'x86_64', 'darwin-amd64'),
                                          ('Darwin', 'arm64', 'darwin-arm64'), ('Linux', 'aarch64', 'linux-arm64'),
                                          ('Linux', 'x86_64', 'linux-amd64')):
            with patch.object(gui.platform, 'system', return_value=system), patch.object(gui.platform, 'machine', return_value=machine):
                self.assertEqual(gui.platform_id(), expected)

    def test_unsupported_platform_has_no_unsafe_fallback(self):
        with patch.object(gui.platform, 'system', return_value='Linux'), patch.object(gui.platform, 'machine', return_value='riscv64'), self.assertRaises(ClientError):
            gui.platform_id()

    def test_open_folder_uses_only_os_folder_opener(self):
        folder = Path.home().resolve() / 'Downloads' / 'VPN-GUIs'
        for system, command in (('Darwin', 'open'), ('Linux', 'xdg-open')):
            with patch.object(gui.platform, 'system', return_value=system), patch.object(gui.subprocess, 'run') as run:
                gui.open_folder(folder)
            self.assertEqual(run.call_args.args[0], [command, str(folder)])
            self.assertNotIn('shell', run.call_args.kwargs)
        with patch.object(gui.platform, 'system', return_value='Windows'), patch.object(gui.os, 'startfile', create=True) as start:
            gui.open_folder(folder)
        start.assert_called_once_with(str(folder))

    def test_missing_folder_opener_is_nonfatal(self):
        with patch.object(gui.platform, 'system', return_value='Linux'), patch.object(gui.subprocess, 'run', side_effect=FileNotFoundError), redirect_stdout(io.StringIO()) as output:
            gui.open_folder(Path.home())
        self.assertIn('manually', output.getvalue())


if __name__ == '__main__':
    unittest.main()
