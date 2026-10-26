"""Official acquisition guidance without retained third-party catalogs."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ReleaseLinkTests(unittest.TestCase):
    def test_removed_catalogs_and_builders_stay_absent(self):
        self.assertFalse((ROOT / 'vendor').exists())
        for name in ('vendor_refresh.py', 'gui_refresh.py', 'gui_source_bundle.py', 'gui-selection.json'):
            self.assertFalse((ROOT / 'admin/tools' / name).exists())

    def test_client_skill_links_to_official_releases(self):
        text = (ROOT / 'skills/vpn-client-setup/SKILL.md').read_text()
        for project in ('XTLS/Xray-core', 'HyNetworks/hysteria', '2dust/v2rayN', 'clash-verge-rev/clash-verge-rev'):
            self.assertIn(f'https://github.com/{project}/releases', text)
        self.assertNotIn('vendor/manifest.json', text)
        self.assertNotIn('gui_refresh.py', text)


if __name__ == '__main__':
    unittest.main()
