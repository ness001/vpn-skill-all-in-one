"""GUI exports use synthetic bundles, never real credentials."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_profiles
from vpn_common import ClientError

VLESS = {"name": "vless", "protocol": "vless", "network": "ws", "tls": True, "allowInsecure": False,
       "server": "vpn.example.invalid", "port": 443, "uuid": "00000000-0000-4000-8000-000000000001",
       "sni": "vpn.example.invalid", "wsHost": "vpn.example.invalid", "wsPath": "/test path", "flow": ""}
HY2 = {"name": "hysteria2", "protocol": "hysteria2", "uri": "hysteria2://android%3Adummy-password@hy.example.invalid:443/?sni=hy.example.invalid&insecure=0"}
SECONDARY_HY2 = {"name": "secondary-hy2", "protocol": "hysteria2", "uri": "hysteria2://test-only-hy2@192.0.2.20:8443/?sni=vpn.example.test&insecure=0"}


class GuiProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'synthetic.json'

    def write_bundle(self, profiles):
        self.bundle.write_text(json.dumps({'schemaVersion': 1, 'profiles': profiles}))

    def export(self, app, target='private'):
        return gui_profiles.export_gui_profiles(app, self.root / target, self.bundle)

    def test_clash_preserves_protocols_auth_and_tls(self):
        config = gui_profiles.clash_config({'vless': VLESS, 'hysteria2': HY2})
        self.assertFalse(config['allow-lan'])
        self.assertFalse(config['ipv6'])
        self.assertEqual(config['bind-address'], '127.0.0.1')
        self.assertNotIn('external-controller', config)
        self.assertEqual(config['proxies'][1]['password'], 'android:dummy-password')
        self.assertTrue(all(not p['skip-cert-verify'] for p in config['proxies']))
        self.assertEqual(config['proxy-groups'][0]['proxies'], ['vless (VLESS)', 'hysteria2 (Hysteria2)'])
        self.assertEqual(config['rules'], [
            'DOMAIN-SUFFIX,localhost,DIRECT', 'IP-CIDR,127.0.0.0/8,DIRECT,no-resolve',
            'IP-CIDR6,::1/128,DIRECT,no-resolve', 'GEOIP,CN,DIRECT', 'MATCH,VPN',
        ])

    def test_three_entries_keep_protocol_and_bundle_order(self):
        self.write_bundle({'vless': VLESS, 'hysteria2': HY2, 'secondary-hy2': {**SECONDARY_HY2, 'mobileUris': {'android': 'not-desktop-auth'}}})
        path = self.export('v2rayn')
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual([unquote(line.split('#')[1]) for line in lines], ['vless (VLESS)', 'hysteria2 (Hysteria2)', 'secondary-hy2 (Hysteria2)'])
        self.assertEqual(lines[2].split('#')[0], SECONDARY_HY2['uri'])
        self.assertEqual(path.name, 'VPN-v2rayN.txt')

    def test_single_generic_profile_and_multiple_same_protocol_entries(self):
        for protocol, original in (('vless', VLESS), ('hysteria2', HY2)):
            for count in (1, 2):
                profiles = {f'node-{i}': {**original, 'name': f'node-{i}', 'protocol': protocol} for i in range(count)}
                self.write_bundle(profiles)
                for app in ('v2rayn', 'clash-verge-rev'):
                    path = self.export(app, f'{protocol}-{count}-{app}')
                    if app == 'v2rayn':
                        self.assertEqual(len(path.read_text().splitlines()), count)
                        self.assertIn('node-0', path.read_text())
                    else:
                        config = json.loads(path.read_text())
                        self.assertEqual(len(config['proxies']), count)
                        self.assertEqual(config['proxies'][0]['type'], protocol)
                        self.assertEqual(path.name, 'VPN-Clash.yaml')
                    self.assertNotIn('vless (VLESS)', unquote(path.read_text()))
                    self.assertNotIn('hysteria2 (Hysteria2)', unquote(path.read_text()))

    def test_invalid_tls_rejected_before_writing(self):
        self.write_bundle({'node': {**HY2, 'name': 'node', 'protocol': 'hysteria2', 'uri': HY2['uri'].replace('insecure=0', 'insecure=1')}})
        for app in ('v2rayn', 'clash-verge-rev'):
            with self.assertRaises(ClientError):
                self.export(app, app)
            self.assertFalse((self.root / app).exists())

    def test_private_exports_and_no_overwrite(self):
        self.write_bundle({'vless': VLESS})
        path = self.export('clash-verge-rev')
        self.assertEqual(json.loads(path.read_text())['proxies'][0]['name'], 'vless (VLESS)')
        with self.assertRaises(ClientError):
            self.export('clash-verge-rev')

    def test_export_creates_missing_parent_directories(self):
        self.write_bundle({'vless': VLESS})
        path = self.export('v2rayn', 'Downloads/VPN-GUIs/profiles-new')
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.root / 'Downloads/VPN-GUIs/profiles-new')
        if sys.platform != 'win32':
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_empty_and_unknown_gui_rejected(self):
        self.write_bundle({})
        for app in ('unknown', 'v2rayn', 'clash-verge-rev'):
            with self.assertRaises(ClientError):
                self.export(app)
        self.assertFalse((self.root / 'private').exists())


if __name__ == '__main__':
    unittest.main()
