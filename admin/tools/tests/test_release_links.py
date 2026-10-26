"""Metadata-only release maintenance and public artifact boundary checks."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'admin/tools'))
import gui_refresh
import gui_source_bundle
import vendor_refresh


class ReleaseLinkTests(unittest.TestCase):
    def test_gui_metadata_does_not_download_packages(self):
        app = {'project': 'example/app', 'version': 'v1'}
        package = {'asset': 'app.zip', 'platform': 'windows-amd64'}
        metadata = {'assets': [{'name': 'app.zip', 'size': 123,
            'digest': 'sha256:' + 'a' * 64,
            'browser_download_url': 'https://github.com/example/app/releases/download/v1/app.zip'}]}
        with patch.object(gui_refresh, 'download') as get:
            result = gui_refresh.package_link(app, package, metadata)
        get.assert_not_called()
        self.assertNotIn('parts', result)
        self.assertEqual(result['size'], 123)
        metadata['assets'][0]['browser_download_url'] = 'https://example.test/app.zip'
        with self.assertRaises(ValueError):
            gui_refresh.package_link(app, package, metadata)

    def test_core_metadata_does_not_download_executables(self):
        release = vendor_refresh.RELEASES['hysteria2']
        metadata = {'tag_name': release['tag'], 'draft': False, 'prerelease': False,
            'assets': [{'name': asset, 'size': 123, 'digest': 'sha256:' + 'a' * 64,
                'browser_download_url': f"https://github.com/{release['project']}/releases/download/{release['tag']}/{asset}"}
                for asset in release['assets'].values()]}
        with patch.object(vendor_refresh, 'download') as get:
            records = vendor_refresh.core_links('hysteria2', metadata)
        get.assert_not_called()
        self.assertEqual(len(records), 3)
        for item in records:
            self.assertNotIn('path', item)
            self.assertNotIn('binarySha256', item)
            self.assertEqual(item['assetSha256'], 'a' * 64)

    def test_source_generation_is_links_only(self):
        result = gui_source_bundle.acquire(gui_source_bundle.SOURCES[0])
        self.assertTrue(result['sourceUrl'].startswith('https://codeload.github.com/'))
        self.assertNotIn('path', result)

    def test_public_manifests_have_no_local_release_references(self):
        manifest = json.loads((ROOT / 'vendor/gui/manifest.json').read_text())
        for app in manifest['apps']:
            for package in app['packages']:
                self.assertNotIn('parts', package)
                for companion in package.get('companions', []):
                    self.assertNotIn('parts', companion)
                    self.assertTrue(companion['sourceUrl'].startswith('https://msedge.sf.dl.delivery.mp.microsoft.com/'))
        sources = json.loads((ROOT / 'vendor/gui/sources/manifest.json').read_text())
        for source in sources['sources']:
            self.assertNotIn('path', source)
        for path in (ROOT / 'vendor').rglob('*'):
            if path.is_file():
                self.assertNotIn('.part', path.name)
                self.assertFalse(path.name.endswith(('.exe', '.dmg', '.deb', '.tar.gz')))


if __name__ == '__main__':
    unittest.main()
