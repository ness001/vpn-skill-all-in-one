"""Isolated browser arguments and owned-child cleanup; no browser or network."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import browser
import vpn_common
from vpn_common import ClientError


class BrowserTests(unittest.TestCase):
    def test_isolated_profile_and_local_proxy(self):
        args = browser.command_for(Path('/Applications/Browser With Spaces'), Path('/private/profile with spaces'), 10809)
        self.assertEqual(args[0], str(Path('/Applications/Browser With Spaces')))
        self.assertIn('--user-data-dir=' + str(Path('/private/profile with spaces')), args)
        self.assertIn('--proxy-server=http://127.0.0.1:10809', args)
        self.assertIn('--disable-sync', args)
        self.assertIn('--disable-background-mode', args)
        self.assertIn('--disable-quic', args)
        self.assertEqual(args[-1], 'about:blank')
        self.assertFalse(any('ignore-certificate' in value or 'no-sandbox' in value for value in args))

    def test_invalid_port(self):
        for port in (0, -1, 65536):
            with self.assertRaises(ClientError):
                browser.command_for(Path('browser'), Path('private'), port)

    def test_missing_browser_fails_clearly(self):
        with patch.object(Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(ClientError, 'Chrome or Edge'):
                browser.browser_path('Darwin')

    def test_unsupported_system(self):
        with self.assertRaises(ClientError):
            browser.browser_path('Other')

    def test_known_windows_install_prefers_chrome(self):
        with patch.dict(os.environ, {'PROGRAMFILES(X86)': r'C:\Program Files (x86)'}), patch.object(Path, 'is_file', return_value=True):
            self.assertEqual(browser.browser_path('Windows').name, 'chrome.exe')

    def test_mac_user_chrome_preferred_to_system_edge(self):
        chrome = Path.home() / 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        edge = Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')
        with patch.object(Path, 'is_file', autospec=True, side_effect=lambda path: path in (chrome, edge)):
            self.assertEqual(browser.browser_path('Darwin'), chrome)

    def test_edge_fallback(self):
        with patch.object(Path, 'is_file', autospec=True, side_effect=lambda path: path.name == 'Microsoft Edge'):
            self.assertEqual(browser.browser_path('Darwin').name, 'Microsoft Edge')

    def test_ctrl_c_closes_owned_browser_before_deleting_profile(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            @contextmanager
            def private():
                try:
                    yield Path(directory)
                finally:
                    events.append('profile-cleanup')
            child = MagicMock()
            with patch.object(browser, 'browser_path', return_value=Path('dummy')), patch.object(browser, 'private_directory', private), patch.object(browser, 'WindowsJob') as job, patch.object(browser.subprocess, 'Popen', return_value=child) as spawn, patch.object(browser, 'stop_browser', side_effect=lambda *args: events.append('stop-browser')) as stop:
                with self.assertRaises(KeyboardInterrupt):
                    with browser.running_browser(10809) as result:
                        self.assertIs(result, child)
                        raise KeyboardInterrupt
                stop.assert_called_once_with(child, job.return_value if os.name == 'nt' else None)
                self.assertIn('--user-data-dir=' + directory, spawn.call_args.args[0])
                self.assertEqual(spawn.call_args.kwargs['stdout'], subprocess.DEVNULL)
                self.assertEqual(spawn.call_args.kwargs['stderr'], subprocess.DEVNULL)
            self.assertEqual(events, ['stop-browser', 'profile-cleanup'])

    def test_spawn_failure_closes_job_and_private_directory(self):
        paths = []
        def fail(command, **kwargs):
            paths.append(Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--user-data-dir='))))
            raise OSError('dummy start failure')
        with patch.object(browser, 'browser_path', return_value=Path('dummy')), patch.object(browser, 'WindowsJob') as job, patch.object(vpn_common, 'restrict_directory'), patch.object(browser.subprocess, 'Popen', side_effect=fail), self.assertRaises(OSError):
            with browser.running_browser(10809):
                pass
        self.assertFalse(paths[0].exists())
        if os.name == 'nt':
            job.return_value.close.assert_called_once()

    def test_windows_job_cleanup_targets_only_job(self):
        child, job = MagicMock(), MagicMock()
        with patch.object(browser, 'stop_child') as stop:
            browser.stop_browser(child, job)
        job.close.assert_called_once()
        stop.assert_called_once_with(child)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Objects')
    def test_real_windows_job_owns_and_stops_only_test_process(self):
        job = browser.WindowsJob()
        child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x4)
        try:
            job.attach_and_resume(child)
            self.assertIsNone(child.poll())
        finally:
            browser.stop_browser(child, job)
        self.assertIsNotNone(child.poll())
        self.assertIsNone(job.handle)
        job.close()

    def test_posix_cleanup_targets_spawned_process_group(self):
        child = MagicMock(pid=987654)
        with patch.object(browser.os, 'killpg', create=True) as killpg, patch.object(browser, 'stop_child') as stop, patch.object(browser.signal, 'SIGKILL', 9, create=True):
            browser.stop_browser(child, None)
        self.assertEqual([call.args[0] for call in killpg.call_args_list], [child.pid, child.pid])
        stop.assert_called_once_with(child)


if __name__ == '__main__':
    unittest.main()
