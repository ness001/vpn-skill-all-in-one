"""Profile location is explicit and independent of a private parent repository."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import gui_profiles
import vpn
import vpn_common


class ProfilePathTests(unittest.TestCase):
    def test_standalone_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(vpn_common.default_profiles_file(), vpn_common.ROOT / 'profiles/vpn-profiles.json')

    def test_environment_and_explicit_cli_override(self):
        external = str(Path.home() / 'private profiles/vpn-profiles.json')
        with patch.dict(os.environ, {'VPN_PROFILES_FILE': external}):
            self.assertEqual(app.parser().parse_args(['vless']).profiles_file, Path(external))
            self.assertEqual(app.parser().parse_args(['vless', '--profiles-file', 'explicit.json']).profiles_file, Path('explicit.json'))
            # Stop before any profile access while exercising the real CLI parser.
            with patch.object(vpn, 'load_profile', side_effect=vpn.ClientError('dummy')) as load:
                vpn.main(['doctor', 'vless'])
                self.assertEqual(load.call_args.args[0], Path(external))
                vpn.main(['doctor', 'vless', '--profiles-file', 'explicit.json'])
                self.assertEqual(load.call_args.args[0], Path('explicit.json'))

    def test_gui_export_uses_environment_or_explicit_path(self):
        with patch.dict(os.environ, {'VPN_PROFILES_FILE': 'external.json'}):
            with patch.object(gui_profiles, 'profile_names', side_effect=vpn.ClientError('dummy')) as load:
                for explicit, expected in ((None, 'external.json'), (Path('explicit.json'), 'explicit.json')):
                    with self.assertRaises(vpn.ClientError):
                        gui_profiles.export_gui_profiles('v2rayn', Path('unused'), explicit)
                    self.assertEqual(load.call_args.args[0], Path(expected))


if __name__ == '__main__':
    unittest.main()
