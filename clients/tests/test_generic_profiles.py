"""Region-neutral profiles work offline without any legacy profile pair."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import core_install
import gui
import qr
import vpn
from vpn_common import ClientError

VLESS = {'name': 'edge-1', 'protocol': 'vless', 'network': 'ws', 'tls': True,
         'server': 'vpn.example.invalid', 'port': 443, 'sni': 'vpn.example.invalid',
         'uuid': '00000000-0000-4000-8000-000000000001', 'wsHost': 'vpn.example.invalid', 'wsPath': '/vpn'}
HY2 = {'name': 'edge-1', 'protocol': 'hysteria2',
       'uri': 'hysteria2://dummy@vpn.example.invalid:443/?insecure=0'}


class GenericProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name) / 'synthetic.json'

    def write(self, profile):
        self.bundle.write_text(json.dumps({'schemaVersion': 1, 'profiles': {'edge-1': profile}}))

    def test_arbitrary_single_identity_resolves_protocol_for_cli_and_qr(self):
        for profile in (VLESS, HY2):
            self.write(profile)
            self.assertEqual(vpn.profile_names(self.bundle), ('edge-1',))
            loaded = vpn.load_profile(self.bundle, 'edge-1')
            self.assertEqual(vpn.resolve_protocol('edge-1', loaded), profile['protocol'])
            with patch.object(vpn, 'resolve_core', return_value=Path('dummy-core')) as resolve, patch.object(vpn, 'check_ports'), patch.object(vpn, 'Popen') as execute, redirect_stdout(io.StringIO()):
                self.assertEqual(vpn.main(['doctor', 'edge-1', '--profiles-file', str(self.bundle)]), 0)
            resolve.assert_called_once_with(profile['protocol'], None, None)
            execute.assert_not_called()
            self.assertTrue(qr.input_uri(self.bundle, 'edge-1').startswith(profile['protocol'] + '://'))
            with patch('builtins.input', return_value='1'), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.choose_profile(self.bundle), 'edge-1')
            self.assertIn('1  edge-1', output.getvalue())
            self.assertIn('2  Desktop GUI installers', output.getvalue())
            self.assertIn('(VLESS)' if profile['protocol'] == 'vless' else '(Hysteria2)', output.getvalue())
            self.assertNotIn('HY2', output.getvalue())

    def test_core_protocols_have_stable_cache_mapping(self):
        for canonical, legacy in (('vless', 'vless'), ('hysteria2', 'hysteria2')):
            self.assertEqual(core_install.core_profile(canonical), legacy)
            self.assertEqual(core_install.install_location(canonical, 'darwin-arm64'), core_install.install_location(legacy, 'darwin-arm64'))
            self.assertEqual(vpn.resolve_protocol(legacy), canonical)
        with self.assertRaises(ClientError):
            vpn.resolve_protocol('secondary-hy2')
        self.assertEqual(vpn.resolve_protocol('secondary-hy2', HY2), 'hysteria2')

    def test_unsafe_or_missing_protocol_rejected_without_values_in_error(self):
        for name in ('../private', 'secret\nvalue', '-option', 'node.json', 'x' * 65):
            with self.assertRaises(ClientError) as caught:
                vpn.profile_id(name)
            self.assertNotIn(name, str(caught.exception))
        with self.assertRaises(ClientError):
            vpn.resolve_protocol('edge-1', {'uri': HY2['uri']})

    def test_public_vless_requires_explicit_protocol(self):
        profile = {key: value for key, value in VLESS.items() if key != 'protocol'}
        with self.assertRaises(ClientError):
            vpn.build_config('vless', profile, 10808, 10809)
        with self.assertRaises(ClientError):
            vpn.mobile_uri('vless', profile, 'android')

    def test_generic_fetch_uses_protocol_without_network(self):
        self.write(HY2)
        with patch.object(vpn, 'fetch_core') as fetch:
            self.assertEqual(vpn.main(['fetch-core', 'edge-1', '--profiles-file', str(self.bundle)]), 0)
        fetch.assert_called_once_with('hysteria2', None, online=False)

    def test_gui_is_a_valid_profile_id_not_a_menu_command(self):
        with patch.object(app, 'connect') as connect, patch.object(app, 'gui_main') as launch, redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['gui']), 0)
        connect.assert_called_once()
        launch.assert_not_called()

    def test_public_help_does_not_require_geographic_choices(self):
        for parser in (app.parser(), vpn.parser(), gui.parser(), qr.parser()):
            self.assertNotIn('west us', parser.format_help().lower())
            self.assertNotIn('wus', parser.format_help().lower())
            self.assertNotIn('hong kong', parser.format_help().lower())

    def test_gui_and_app_preserve_explicit_profiles_path(self):
        with patch.dict(os.environ, {'VPN_PROFILES_FILE': 'environment.json'}):
            self.assertEqual(gui.parser().parse_args([]).profiles_file, Path('environment.json'))
            self.assertEqual(gui.parser().parse_args(['--profiles-file', 'explicit.json']).profiles_file, Path('explicit.json'))
            with patch.object(app, 'choose_profile', return_value='__gui__'), patch.object(app, 'gui_main', return_value=0) as launch:
                self.assertEqual(app.main(['--profiles-file', 'explicit.json']), 0)
            launch.assert_called_once_with(['--profiles-file', 'explicit.json'])


if __name__ == '__main__':
    unittest.main()
