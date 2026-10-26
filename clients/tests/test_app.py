"""Single-entry UX tests with dummy profiles, offline cores and no real browser."""
from contextlib import contextmanager, ExitStack, redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import core_install
import vpn
from vpn_common import ClientError

VLESS = {
    "name": "vless", "server": "vless.example.test", "port": 443, "protocol": "vless",
    "uuid": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "flow": "", "network": "ws",
    "tls": True, "sni": "vless.example.test", "wsPath": "/example-ws", "wsHost": "vless.example.test",
    "allowInsecure": False,
}
HY2 = {"name": "hysteria2", "protocol": "hysteria2", "uri": "hysteria2://test-only@hysteria2.example.test:443/?insecure=0"}
SECONDARY_HY2 = {"name": "secondary-hy2", "protocol": "hysteria2", "uri": "hysteria2://test-only-secondary-hy2@192.0.2.20:8443/?sni=vpn.example.test&insecure=0"}


class MenuTests(unittest.TestCase):
    def setUp(self):
        load = patch.object(app, 'load_profile', side_effect=lambda _, name: {'vless': VLESS, 'secondary-hy2': SECONDARY_HY2, 'hysteria2': HY2}[name])
        self.load = load.start()
        self.addCleanup(load.stop)
        names = patch.object(app, 'profile_names', return_value=('vless', 'secondary-hy2', 'hysteria2'))
        self.names = names.start()
        self.addCleanup(names.stop)

    def test_menu_preserves_profiles_and_adds_separate_secondary_hy2(self):
        for choice, expected in (("1", "vless"), ("2", "secondary-hy2"), ("3", "hysteria2"), ("4", "__gui__"), ("5", None)):
            output = io.StringIO()
            with patch('builtins.input', return_value=choice), redirect_stdout(output):
                self.assertEqual(app.choose_profile(), expected)
            self.assertIn('1  vless (VLESS)', output.getvalue())
            self.assertIn('2  secondary-hy2 (Hysteria2)', output.getvalue())
            self.assertIn('3  hysteria2 (Hysteria2)', output.getvalue())
            self.assertIn('4  Desktop GUI installers', output.getvalue())
            self.assertIn('5  Exit', output.getvalue())

    def test_menu_only_lists_configured_profiles(self):
        self.names.return_value = ('hysteria2',)
        with patch('builtins.input', return_value='1'), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.choose_profile(), 'hysteria2')
        self.assertIn('1  hysteria2 (Hysteria2)', output.getvalue())
        self.assertNotIn('VLESS', output.getvalue())

    def test_unreadable_bundle_still_allows_gui(self):
        self.names.side_effect = ClientError('Cannot read the shared profile bundle')
        with patch('builtins.input', return_value='1'), redirect_stdout(io.StringIO()):
            self.assertEqual(app.choose_profile(), '__gui__')

    def test_menu_checks_requested_bundle_without_printing_profile(self):
        bundle = Path('dummy-profile-path')
        with patch('builtins.input', return_value='5'), redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(app.choose_profile(bundle))
        self.names.assert_called_once_with(bundle)
        self.assertEqual(self.load.call_count, 3)
        self.assertNotIn(SECONDARY_HY2['uri'], output.getvalue())

    def test_invalid_selection_retries_and_eof_exits(self):
        with patch('builtins.input', side_effect=['bad', '3']), redirect_stdout(io.StringIO()):
            self.assertEqual(app.choose_profile(), 'hysteria2')
        with patch('builtins.input', side_effect=EOFError), redirect_stdout(io.StringIO()):
            self.assertIsNone(app.choose_profile())

    def test_exit_never_loads_a_profile_or_connects(self):
        with patch.object(app, 'choose_profile', return_value=None), patch.object(app, 'connect') as connect:
            self.assertEqual(app.main([]), 0)
        connect.assert_not_called()

    def test_gui_choice_runs_before_profile_or_core_checks(self):
        with patch.object(app, 'choose_profile', return_value='__gui__'), patch.object(app, 'gui_main', return_value=0) as gui, patch.object(app, 'connect') as connect, patch.object(app, 'load_profile') as load, patch.object(app, 'resolve_core') as core:
            self.assertEqual(app.main([]), 0)
        gui.assert_called_once_with(['--profiles-file', str(app.default_profiles_file())])
        connect.assert_not_called()
        load.assert_not_called()
        core.assert_not_called()

    def test_gui_status_is_preserved(self):
        for status in (1, 130):
            with patch.object(app, 'choose_profile', return_value='__gui__'), patch.object(app, 'gui_main', return_value=status):
                self.assertEqual(app.main([]), status)

    def test_ctrl_c_during_main_menu_is_preserved(self):
        with patch('builtins.input', side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()):
            self.assertEqual(app.main([]), 130)

    def test_direct_profile_never_prompts(self):
        with patch.object(app, 'choose_profile') as menu, patch.object(app, 'connect') as connect, redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['vless', '--no-browser']), 0)
        menu.assert_not_called()
        self.assertEqual(connect.call_args.args[0].profile, 'vless')
        self.assertTrue(connect.call_args.args[0].no_browser)

    def test_automation_options_require_profile(self):
        for option in ('--check', '--no-browser'):
            with patch.object(app, 'choose_profile') as menu, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                app.main([option])
            self.assertEqual(error.exception.code, 2)
            menu.assert_not_called()

    def test_minimum_python(self):
        with patch.object(app.sys, 'version_info', (3, 10)), patch.object(app, 'connect') as connect, redirect_stderr(io.StringIO()) as output:
            self.assertEqual(app.main(['hysteria2']), 1)
        self.assertIn('https://www.python.org/downloads/', output.getvalue())
        connect.assert_not_called()

    def test_error_details_are_sanitized(self):
        with patch.object(app, 'connect', side_effect=OSError('private-secret')), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(app.main(['hysteria2']), 1)
        self.assertNotIn('private-secret', output.getvalue())


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'dummy-profiles.json'
        self.bundle.write_text(json.dumps({'schemaVersion': 1, 'profiles': {'vless': VLESS, 'secondary-hy2': SECONDARY_HY2, 'hysteria2': HY2}}))
        self.output = io.StringIO()

    def arguments(self, profile='vless', *extra):
        return app.parser().parse_args([profile, '--profiles-file', str(self.bundle), *extra])

    def session_mocks(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(redirect_stdout(self.output))
        stack.enter_context(redirect_stderr(self.output))
        stack.enter_context(patch.object(app, 'resolve_core', return_value=Path('dummy-core')))
        core = stack.enter_context(patch.object(app, 'running_core')).return_value.__enter__.return_value
        browser = stack.enter_context(patch.object(app, 'running_browser')).return_value.__enter__.return_value
        wait = stack.enter_context(patch.object(app, 'wait_session'))
        return core, browser, wait

    def test_select_runs_existing_validators_then_browser(self):
        for profile in ('vless', 'secondary-hy2', 'hysteria2'):
            with self.subTest(profile=profile):
                core, browser, wait = self.session_mocks()
                app.connect(self.arguments(profile))
                wait.assert_called_once_with(core, browser)
        self.assertNotIn(VLESS['uuid'], self.output.getvalue())
        self.assertNotIn(HY2['uri'], self.output.getvalue())
        self.assertIn('Website access is not yet verified', self.output.getvalue())

    def test_no_browser_keeps_local_proxy_instructions(self):
        core, _, wait = self.session_mocks()
        with patch.object(app, 'running_browser') as browser:
            app.connect(self.arguments('hysteria2', '--no-browser'))
        browser.assert_not_called()
        wait.assert_called_once_with(core, None)
        self.assertIn('127.0.0.1:10808', self.output.getvalue())
        self.assertIn('127.0.0.1:10809', self.output.getvalue())

    def test_browser_missing_or_start_failure_keeps_proxy_alive(self):
        for error in (ClientError('Browser missing'), OSError('private path')):
            core, _, wait = self.session_mocks()
            with patch.object(app, 'running_browser', side_effect=error):
                app.connect(self.arguments())
            wait.assert_called_once_with(core, None)
        self.assertIn('127.0.0.1:10809', self.output.getvalue())
        self.assertNotIn('private path', self.output.getvalue())

    def test_browser_cleanup_failure_is_not_treated_as_missing_browser(self):
        _, _, wait = self.session_mocks()
        with patch.object(app, 'running_browser', side_effect=app.CleanupError('cleanup failed')), self.assertRaises(app.CleanupError):
            app.connect(self.arguments())
        wait.assert_not_called()
        self.assertNotIn('Temporary VPN configuration and browser profile removed', self.output.getvalue())

    def test_check_never_opens_browser_or_enters_foreground_wait(self):
        _, _, wait = self.session_mocks()
        with patch.object(app, 'check_forwarding') as check, patch.object(app, 'running_browser') as browser:
            app.connect(self.arguments('hysteria2', '--check'))
        check.assert_called_once_with(10809)
        browser.assert_not_called()
        wait.assert_not_called()

    def test_ctrl_c_stops_browser_before_core_and_removes_config(self):
        events, paths = [], []
        core = MagicMock()
        core.poll.return_value = None
        def spawn(command, **kwargs):
            paths.append(Path(command[-1]))
            self.assertTrue(paths[0].exists())
            return core
        @contextmanager
        def browser(port):
            try:
                yield MagicMock()
            finally:
                events.append('browser stopped')
        with patch.object(app, 'resolve_core', return_value=Path('dummy-core')), patch.object(vpn, 'check_ports'), patch.object(vpn, 'wait_ready'), patch.object(vpn, 'Popen', side_effect=spawn), patch.object(vpn, 'stop_child', side_effect=lambda child: events.append('core stopped')), patch.object(app, 'running_browser', browser), patch.object(app, 'wait_session', side_effect=KeyboardInterrupt), redirect_stdout(self.output):
            status = app.main(['vless', '--profiles-file', str(self.bundle)])
        self.assertEqual(status, 130)
        self.assertEqual(events, ['browser stopped', 'core stopped'])
        self.assertFalse(paths[0].parent.exists())

    def test_core_readiness_failure_never_opens_browser(self):
        core, _, _ = self.session_mocks()
        with patch.object(app, 'running_core', side_effect=ClientError('timeout')), patch.object(app, 'running_browser') as browser, self.assertRaises(ClientError):
            app.connect(self.arguments())
        browser.assert_not_called()

    def test_fresh_clone_connect_verifies_bundled_cores_without_network_or_install(self):
        bundled = self.root / 'vendor' / 'cores'
        for profile in ('vless', 'hysteria2'):
            directory, name = core_install.install_location(profile, 'windows-amd64', bundled)
            directory.mkdir(parents=True)
            core = directory / name
            core.write_bytes(b'dummy executable never executed')
            core.chmod(0o700)
            release = core_install.RELEASES[profile]
            (directory / 'verified.json').write_text(json.dumps({
                'schemaVersion': 1, 'profile': profile, 'project': release['project'], 'tag': release['tag'],
                'platform': 'windows-amd64', 'asset': release['assets']['windows-amd64'],
                'assetSha256': 'a' * 64, 'binarySha256': hashlib.sha256(core.read_bytes()).hexdigest(),
            }))
            with patch.object(core_install, 'BUNDLED', bundled), patch.object(core_install, 'platform_id', return_value='windows-amd64'), patch.object(core_install, 'download', side_effect=AssertionError('Network forbidden')) as download, patch.object(app, 'running_core') as running, patch.object(app, 'wait_session'), redirect_stdout(self.output):
                app.connect(self.arguments(profile, '--no-browser'))
                self.assertEqual(running.call_args.args[2], core)
                core.write_bytes(b'corrupted')
                with self.assertRaisesRegex(ClientError, 'checksum'):
                    app.connect(self.arguments(profile, '--no-browser'))
                self.assertEqual(running.call_count, 1)
            download.assert_not_called()
        self.assertFalse((self.root / '.venv').exists())
        self.assertNotIn(VLESS['uuid'], self.output.getvalue())

    def test_missing_secondary_hy2_never_falls_back_to_hysteria2_or_starts_core(self):
        self.bundle.write_text(json.dumps({'schemaVersion': 1, 'profiles': {'vless': VLESS, 'hysteria2': HY2}}))
        with patch.object(app, 'resolve_core') as resolve, patch.object(app, 'running_core') as start, self.assertRaisesRegex(ClientError, 'not configured'):
            app.connect(self.arguments('secondary-hy2'))
        resolve.assert_not_called()
        start.assert_not_called()

    def test_invalid_profile_never_starts_anything(self):
        self.bundle.write_text(json.dumps({'schemaVersion': 1, 'profiles': {'vless': {**VLESS, 'uuid': 'bad'}}}))
        with patch.object(app, 'resolve_core') as resolve, patch.object(app, 'running_core') as start, self.assertRaises(ClientError):
            app.connect(self.arguments())
        resolve.assert_not_called()
        start.assert_not_called()


class WaitTests(unittest.TestCase):
    def test_browser_close_ends_session(self):
        core, browser = MagicMock(), MagicMock()
        core.poll.return_value = None
        browser.poll.return_value = 0
        app.wait_session(core, browser)

    def test_core_exit_detected_even_while_browser_running(self):
        core, browser = MagicMock(), MagicMock()
        core.poll.return_value = 7
        browser.poll.return_value = None
        with self.assertRaisesRegex(ClientError, 'status 7'):
            app.wait_session(core, browser)

    def test_browser_failure_leaves_proxy_running(self):
        core, browser = MagicMock(), MagicMock()
        core.poll.return_value = None
        browser.poll.return_value = 1
        with patch.object(app.time, 'sleep', side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()) as output, self.assertRaises(KeyboardInterrupt):
            app.wait_session(core, browser)
        self.assertIn('Local proxies remain available', output.getvalue())
        core.terminate.assert_not_called()


class CheckTests(unittest.TestCase):
    def test_check_forces_explicit_proxy_and_verified_tls(self):
        child = MagicMock()
        child.wait.return_value = 0
        child.poll.return_value = 0
        with patch.object(app.subprocess, 'Popen') as start, redirect_stdout(io.StringIO()) as output:
            start.return_value.__enter__.return_value = child
            app.check_forwarding(12345)
        args = start.call_args.args[0]
        self.assertEqual(args[-1], '12345')
        self.assertIn('set_tunnel', args[-2])
        self.assertIn('ssl.create_default_context()', args[-2])
        self.assertIn("request('HEAD'", args[-2])
        self.assertEqual(start.call_args.kwargs['stdout'], subprocess.DEVNULL)
        child.wait.assert_called_once_with(timeout=20)
        self.assertIn('HTTPS check passed', output.getvalue())

    def test_check_timeout_stops_probe_and_does_not_claim_success(self):
        child = MagicMock()
        child.wait.side_effect = [subprocess.TimeoutExpired('dummy', 20), 0]
        child.poll.return_value = None
        with patch.object(app.subprocess, 'Popen') as start, redirect_stdout(io.StringIO()) as output, self.assertRaisesRegex(ClientError, 'timed out'):
            start.return_value.__enter__.return_value = child
            app.check_forwarding(12345)
        child.kill.assert_called_once()
        self.assertNotIn('passed', output.getvalue())

    def test_failed_check_is_sanitized(self):
        child = MagicMock()
        child.wait.return_value = 1
        child.poll.return_value = 1
        with patch.object(app.subprocess, 'Popen') as start, self.assertRaisesRegex(ClientError, 'TLS verification remains enabled'):
            start.return_value.__enter__.return_value = child
            app.check_forwarding(12345)


class SetupEntryTests(unittest.TestCase):
    def test_public_setup_uses_separate_skills_not_desktop_shortcuts(self):
        root = Path(__file__).resolve().parents[2]
        self.assertFalse((root / 'VPN.cmd').exists())
        self.assertFalse((root / 'VPN.command').exists())
        for name in ('vpn-server-setup', 'vpn-client-setup'):
            skill = root / 'skills' / name / 'SKILL.md'
            self.assertIn(f'name: {name}', skill.read_text())
        self.assertFalse((root / 'skills/vpn-setup').exists())


if __name__ == '__main__':
    unittest.main()
