"""Official GUI links and explicit private exports; no downloads or installers."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui
from vpn_common import ClientError


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.base = Path(self.temporary).resolve()
        self.exports = self.enterContext(patch.object(gui, 'export_gui_profiles', return_value=self.base / 'imports' / 'VPN.txt'))
        self.network = self.enterContext(patch.object(socket, 'create_connection', side_effect=AssertionError('Network forbidden')))
        self.process = self.enterContext(patch.object(gui.subprocess, 'run', side_effect=AssertionError('Process forbidden')))

    def test_official_release_pages_without_network_profiles_or_processes(self):
        for app_id, (_, url) in gui.APPS.items():
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(gui.main(['--app', app_id]), 0)
            self.assertIn(url, output.getvalue())
            self.assertIn('No downloads, profile exports or installation performed', output.getvalue())
        self.exports.assert_not_called()
        self.network.assert_not_called()
        self.process.assert_not_called()

    def test_menu_is_read_free_and_selection_retry_cancel_eof(self):
        with patch('builtins.input', side_effect=['bad', '1']), redirect_stdout(io.StringIO()):
            self.assertEqual(gui.main([]), 0)
        self.exports.assert_not_called()
        for effect in (['0'], EOFError):
            with patch('builtins.input', side_effect=effect), redirect_stdout(io.StringIO()):
                self.assertIsNone(gui.choose_app())

    def test_explicit_export_uses_supplied_profiles_and_fresh_directory(self):
        directories = []
        for _ in range(2):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(gui.main(['--app', 'clash-verge-rev', '--profiles-file', str(self.base / 'private.json'), '--output-dir', str(self.base), '--export-profiles']), 0)
            app_id, directory, source = self.exports.call_args.args
            self.assertEqual(app_id, 'clash-verge-rev')
            self.assertEqual(source, self.base / 'private.json')
            self.assertEqual(directory.parent, self.base)
            self.assertTrue(directory.name.startswith('profiles-'))
            directories.append(directory)
            self.assertIn('contains VPN credentials', output.getvalue())
            self.assertIn('local YAML', output.getvalue())
        self.assertNotEqual(*directories)
        self.process.assert_not_called()

    def test_only_explicit_folder_open_after_successful_export(self):
        with patch.object(gui, 'open_folder') as opening, redirect_stdout(io.StringIO()):
            self.assertEqual(gui.main(['--app', 'v2rayn', '--export-profiles', '--open-folder']), 0)
        opening.assert_called_once_with(self.exports.return_value.parent)
        self.exports.side_effect = ClientError('Cannot create private export')
        with patch.object(gui, 'open_folder') as opening, redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(gui.main(['--app', 'v2rayn', '--export-profiles', '--open-folder']), 1)
        opening.assert_not_called()
        self.assertNotIn('Private VPN import file:', output.getvalue())

    def test_unsupported_application_is_not_echoed(self):
        with redirect_stderr(io.StringIO()) as output:
            self.assertEqual(gui.main(['--app', 'private-value']), 1)
        self.assertNotIn('private-value', output.getvalue())
        self.exports.assert_not_called()

    def test_open_requires_export_and_removed_download_is_rejected(self):
        for options in (['--open-folder'], ['--app', 'v2rayn', '--download']):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                gui.main(options)
            self.assertEqual(error.exception.code, 2)

    def test_interrupt_returns_130(self):
        with patch('builtins.input', side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()):
            self.assertEqual(gui.main([]), 130)

    def test_open_folder_uses_only_os_folder_opener(self):
        folder = self.base / 'imports'
        self.process.side_effect = None
        for system, command in (('Darwin', 'open'), ('Linux', 'xdg-open')):
            with patch.object(gui.platform, 'system', return_value=system):
                gui.open_folder(folder)
            self.assertEqual(self.process.call_args.args[0], [command, str(folder)])
            self.assertNotIn('shell', self.process.call_args.kwargs)
        with patch.object(gui.platform, 'system', return_value='Windows'), patch.object(gui.os, 'startfile', create=True) as start:
            gui.open_folder(folder)
        start.assert_called_once_with(str(folder))


if __name__ == '__main__':
    unittest.main()
