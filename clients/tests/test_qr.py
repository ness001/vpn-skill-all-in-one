"""Offline QR tests use dummy credentials only; image/decoder dependencies are optional."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qr
import vpn
import vpn_common

VLESS = {
    "name": "vless", "server": "vpn.example.test", "port": 443, "protocol": "vless",
    "uuid": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "network": "ws", "tls": True,
    "sni": "tls.example.test", "wsPath": "/dummy ws?x=1&y=2", "wsHost": "ws.example.test",
}
HY2 = "hysteria2://dummy%40user:dummy%2521@hy.example.test:8443/?sni=tls.example.test&insecure=0&alpn=h3&obfs=salamander&obfs-password=dummy%2Bsecret#HY2"
VLESS_URI = vpn.mobile_uri("vless", VLESS, "android")
HAS_QR = importlib.util.find_spec("qrcode") is not None and importlib.util.find_spec("PIL") is not None
HAS_DECODER = importlib.util.find_spec("zxingcpp") is not None


class QRTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "input.txt"
        self.destination = self.root / "private-qr" / "phone.png"
        self.source.write_text(VLESS_URI + "\n", encoding="utf-8")

    def write_json(self, value):
        self.source.write_text(json.dumps(value), encoding="utf-8")

    def run_cli(self, extra=()):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = qr.main(["--input", str(self.source), "--output", str(self.destination), *extra])
        return status, output.getvalue()

    def assert_cli_rejected(self, extra=()):
        status, output = self.run_cli(extra)
        self.assertEqual(status, 1)
        for private in (VLESS["uuid"], VLESS["server"], "dummy", VLESS_URI, HY2):
            self.assertNotIn(private, output)
        self.assertFalse(self.destination.exists())

    def test_uri_files_preserve_exact_supported_settings(self):
        for uri in (VLESS_URI, HY2, HY2.replace("hysteria2://", "hy2://"),
                    VLESS_URI.replace("vpn.example.test:443", "[2001:db8::1]:443")):
            with self.subTest(scheme=urlsplit(uri).scheme):
                self.source.write_text("﻿" + uri + "\n", encoding="utf-8")
                self.assertEqual(qr.input_uri(self.source), uri)

    def test_label_only_replaces_fragment(self):
        value = qr.input_uri(self.source, label="WA phone / 测试")
        self.assertEqual(value.split("#")[0], VLESS_URI.split("#")[0])
        self.assertEqual(unquote(urlsplit(value).fragment), "WA phone / 测试")

    def test_bundle_profile_and_device_selection(self):
        for name in ("vless", "secondary-hy2", "hysteria2"):
            profile = VLESS if name == "vless" else {
                "name": name, "protocol": "hysteria2", "uri": HY2, "mobileUris": {"iphone": HY2.replace("dummy%40user", "iphone-dummy")},
            }
            self.write_json({"schemaVersion": 1, "profiles": {name: profile}})
            for device in ("android", "desktop", "iphone"):
                with self.subTest(name=name, device=device):
                    self.assertEqual(qr.input_uri(self.source, name, device), vpn.mobile_uri(name, profile, device))

    def test_bundle_requires_profile(self):
        self.write_json({"schemaVersion": 1, "profiles": {"vless": VLESS}})
        self.assert_cli_rejected()

    def test_bundle_invalid_schema_is_sanitized(self):
        for version in (2, True, 1.0, "dummy"):
            self.write_json({"schemaVersion": version, "profiles": {"vless": VLESS}})
            self.assert_cli_rejected(["--profile", "vless"])

    def test_profile_selector_rejected_for_uri_or_xray(self):
        self.assert_cli_rejected(["--profile", "vless"])
        self.write_json(vpn.xray_config(VLESS, 10808, 10809))
        self.assert_cli_rejected(["--profile", "vless"])

    def test_xray_with_direct_and_routing_only_exports_connection(self):
        config = vpn.xray_config(VLESS, 10808, 10809)
        config["outbounds"].append({"tag": "direct", "protocol": "freedom"})
        config["routing"] = {"rules": [{"ip": ["geoip:cn"], "outboundTag": "direct"}]}
        config["dns"] = {"servers": ["localhost"]}
        self.write_json(config)
        uri = qr.input_uri(self.source, label="WA")
        self.assertEqual(uri, VLESS_URI.split("#")[0] + "#WA")
        self.assertNotIn("geoip", uri)

    def test_xray_modern_host_and_defaults(self):
        config = vpn.xray_config(VLESS, 10808, 10809)
        stream = config["outbounds"][0]["streamSettings"]
        stream["wsSettings"] = {"host": VLESS["wsHost"]}
        stream["tlsSettings"] = {}
        self.write_json(config)
        query = parse_qs(urlsplit(qr.input_uri(self.source)).query)
        self.assertEqual(query["path"], ["/"])
        self.assertEqual(query["host"], [VLESS["wsHost"]])
        self.assertEqual(query["sni"], [VLESS["server"]])

    def test_xray_ambiguity_and_malformed_shapes_rejected(self):
        valid = vpn.xray_config(VLESS, 10808, 10809)
        variants = [{"outbounds": []}, {"outbounds": [None]},
                    {"outbounds": valid["outbounds"] * 2}, {"outbounds": {}}]
        for field, value in (("vnext", []), ("vnext", [{}]), ("vnext", None)):
            config = copy.deepcopy(valid)
            config["outbounds"][0]["settings"][field] = value
            variants.append(config)
        for value in variants:
            self.write_json(value)
            self.assert_cli_rejected()

    def test_xray_security_and_unrepresentable_options_rejected(self):
        cases = [
            (("streamSettings", "security"), "none"),
            (("streamSettings", "network"), "tcp"),
            (("streamSettings", "tlsSettings", "allowInsecure"), True),
            (("streamSettings", "tlsSettings", "allowInsecure"), 0),
            (("streamSettings", "tlsSettings", "fingerprint"), "chrome"),
            (("streamSettings", "tlsSettings", "disableSystemRoot"), True),
            (("streamSettings", "wsSettings", "headers", "Authorization"), "dummy"),
            (("streamSettings", "wsSettings", "host"), "conflict.example.test"),
            (("settings", "vnext", 0, "users", 0, "id"), "dummy"),
            (("settings", "vnext", 0, "users", 0, "encryption"), "dummy"),
            (("settings", "vnext", 0, "users", 0, "flow"), "xtls-rprx-vision"),
            (("settings", "vnext", 0, "users"), []),
            (("proxySettings",), {"tag": "another-hop"}),
        ]
        for keys, value in cases:
            config = vpn.xray_config(VLESS, 10808, 10809)
            node = config["outbounds"][0]
            for key in keys[:-1]:
                node = node[key]
            node[keys[-1]] = value
            self.write_json(config)
            with self.subTest(keys=keys):
                self.assert_cli_rejected()

    def test_insecure_duplicate_unknown_and_invalid_uris_rejected(self):
        uris = [VLESS_URI.replace("security=tls", "security=none"), VLESS_URI.replace(":443?", ":0?"),
                VLESS_URI.replace(":443?", ":99999?"), VLESS_URI.replace("type=ws", "type=tcp"),
                VLESS_URI.replace("encryption=none", "encryption=dummy"), VLESS_URI.replace(VLESS["uuid"], "dummy"),
                VLESS_URI.replace("?", "?security=tls&", 1), VLESS_URI.replace("?", "?allowInsecure=1&", 1),
                HY2.replace("insecure=0", "insecure=1"), HY2.replace("alpn=h3", "alpn=h2"),
                VLESS_URI + "\n" + HY2, "vless://dummy@vpn.example.test/?dummy"]
        for index, uri in enumerate(uris):
            self.source.write_text(uri, encoding="utf-8")
            with self.subTest(index=index):
                self.assert_cli_rejected()

    def test_corrupt_oversized_or_missing_input_is_sanitized(self):
        for content in (b'{"dummy":', b'\xff', b'[]', b'null', b'x' * (qr.MAX_CONFIG_BYTES + 1)):
            self.source.write_bytes(content)
            self.assert_cli_rejected()
        self.source.unlink()
        self.assert_cli_rejected()

    def test_cli_defaults_and_unknown_arguments_do_not_echo_values(self):
        args = qr.parser().parse_args(["--input", "input", "--output", "output.png"])
        self.assertEqual(args.device, "android")
        self.assertIsNone(args.profile)
        for extra in (["--unknown", "dummy-private"], ["--device", "dummy-private"],
                      ["--profile", "dummy-private"], ["--label", "dummy\nprivate"]):
            self.assert_cli_rejected(extra)

    def test_arbitrary_config_and_decoder_errors_are_sanitized(self):
        for operation in ("input_uri", "png_bytes"):
            for exception in (RuntimeError("dummy-private"), vpn_common.ClientError("dummy-private")):
                with patch.object(qr, operation, side_effect=exception):
                    self.assert_cli_rejected()

    def test_missing_dependency_is_actionable_without_install(self):
        with patch.dict(sys.modules, {"qrcode": None}):
            status, output = self.run_cli()
        self.assertEqual(status, 1)
        self.assertIn("requirements-qr.txt", output)
        self.assertIn("nothing was downloaded", output)
        self.assertFalse(self.destination.exists())

    def test_output_inside_git_rejected_before_reading(self):
        for kind in ("directory", "file", "bare", "root"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if kind == "directory":
                    (root / ".git").mkdir()
                elif kind == "file":
                    (root / ".git").write_text("gitdir: dummy", encoding="utf-8")
                elif kind == "bare":
                    (root / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
                    (root / "objects").mkdir()
                    (root / "refs").mkdir()
                with patch.object(qr, "ROOT", root if kind == "root" else qr.ROOT), patch.object(qr, "input_uri") as read:
                    with self.assertRaises(qr.QRExportError):
                        qr.export_qr(self.source, root / "private" / "phone.png")
                    read.assert_not_called()

    def test_existing_output_and_wrong_extension_rejected(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(b"original")
        self.assert_cli_rejected_without_removal()
        self.assertEqual(self.destination.read_bytes(), b"original")
        self.destination = self.destination.with_suffix(".txt")
        self.assert_cli_rejected()

    def assert_cli_rejected_without_removal(self):
        status, output = self.run_cli()
        self.assertEqual(status, 1)
        self.assertNotIn(VLESS["uuid"], output)

    def test_symlink_input_output_and_parent_rejected(self):
        link = self.root / "link"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("Symlink creation not available to this account")
        with self.assertRaises(qr.QRExportError):
            qr.input_uri(link)
        with self.assertRaises(qr.QRExportError):
            qr._output_path(link)
        link.unlink()
        link.symlink_to(self.root / "missing")
        with self.assertRaises(qr.QRExportError):
            qr._output_path(link / "phone.png")

    def test_windows_junction_attribute_rejected(self):
        info = type("Info", (), {"st_mode": stat.S_IFDIR, "st_file_attributes": 0x400})()
        with patch.object(Path, "lstat", return_value=info), self.assertRaises(qr.QRExportError):
            qr._check_path(self.destination)

    def test_new_private_child_does_not_restrict_existing_parent(self):
        with patch.object(qr, "png_bytes", return_value=b"dummy-png"), patch.object(
                vpn_common, "restrict_directory", wraps=vpn_common.restrict_directory) as restrict:
            qr.export_qr(self.source, self.destination)
        paths = [call.args[0] for call in restrict.call_args_list]
        self.assertIn(self.destination.parent, paths)
        self.assertNotIn(self.root, paths)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)

    def test_write_failure_leaves_no_partial_output(self):
        def fail(path, data):
            path.write_bytes(b"partial")
            raise OSError("dummy-private")
        with patch.object(qr, "png_bytes", return_value=b"dummy-png"), patch.object(qr, "private_write", side_effect=fail):
            self.assert_cli_rejected()
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_link_failure_leaves_no_partial_output(self):
        with patch.object(qr, "png_bytes", return_value=b"dummy-png"), patch.object(qr.os, "link", side_effect=OSError("dummy-private")):
            self.assert_cli_rejected()
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_output_created_during_publication_is_not_overwritten(self):
        real_link = os.link
        def raced(source, destination):
            destination.write_bytes(b"original")
            return real_link(source, destination)
        with patch.object(qr, "png_bytes", return_value=b"dummy-png"), patch.object(qr.os, "link", side_effect=raced):
            self.assert_cli_rejected_without_removal()
        self.assertEqual(self.destination.read_bytes(), b"original")
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    @unittest.skipUnless(HAS_QR, "Optional qrcode/Pillow not installed")
    def test_real_png_without_decoder_and_private_cli_notice(self):
        with patch.dict(sys.modules, {"zxingcpp": None}):
            status, output = self.run_cli(["--label", "WA"])
        self.assertEqual(status, 0)
        self.assertEqual(self.destination.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn(str(self.destination), output)
        self.assertIn("Connection only; configure China bypass in phone app", output)
        self.assertNotIn(VLESS["uuid"], output)

    @unittest.skipUnless(HAS_QR and HAS_DECODER, "Optional QR decoder not installed")
    def test_png_roundtrip_for_both_protocols(self):
        from PIL import Image
        import zxingcpp
        for uri in (VLESS_URI, HY2):
            with Image.open(io.BytesIO(qr.png_bytes(uri))) as image:
                results = zxingcpp.read_barcodes(image)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].text, uri)

    @unittest.skipUnless(HAS_QR and HAS_DECODER, "Optional QR decoder not installed")
    def test_decoder_failure_or_mismatch_never_publishes(self):
        import zxingcpp
        for result in ([], [type("Result", (), {"text": "dummy-wrong"})()]):
            with patch.object(zxingcpp, "read_barcodes", return_value=result):
                self.assert_cli_rejected()
        with patch.object(zxingcpp, "read_barcodes", side_effect=RuntimeError("dummy-private")):
            self.assert_cli_rejected()


if __name__ == "__main__":
    unittest.main()
