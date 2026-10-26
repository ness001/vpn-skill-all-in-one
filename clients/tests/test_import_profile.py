"""Offline installer-export conversion; all credentials are synthetic."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import import_profile
import vpn
import vpn_common

spec = importlib.util.spec_from_file_location("import_test_render", Path(__file__).resolve().parents[2] / "admin/installer/render.py")
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)

UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
AUTH = "dummy:@/%?#&+=!password"


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "client.json"
        self.output = self.root / "private-bundle" / "vpn-profiles.json"

    def exports(self, protocol):
        credentials = {"uuid": UUID, "ws_path": "/synthetic-path"} if protocol == "vless" else {"username": "dummy-user", "password": AUTH}
        return render.client_config({"profile": protocol, "domain": "vpn.example.test"}, credentials)

    def run_cli(self, extra=()):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            status = import_profile.main(["--input", str(self.source), "--name", "edge-1", "--output", str(self.output), *extra])
        for secret in (UUID, AUTH, "dummy-user", "vpn.example.test", str(self.source), str(self.output)):
            self.assertNotIn(secret, stream.getvalue())
        return status, stream.getvalue()

    def rejected(self):
        status, _ = self.run_cli()
        self.assertEqual(status, 1)
        self.assertFalse(self.output.exists())

    def test_actual_installer_uri_and_native_exports_both_protocols(self):
        for protocol in ("vless", "hysteria2"):
            uri, native = self.exports(protocol)
            for content in (uri, native):
                with self.subTest(protocol=protocol, native=content == native):
                    self.source.write_text(content)
                    self.assertEqual(self.run_cli()[0], 0)
                    bundle = json.loads(self.output.read_text())
                    self.assertEqual(bundle["schemaVersion"], 1)
                    self.assertEqual(set(bundle["profiles"]), {"edge-1"})
                    profile = vpn.load_profile(self.output, "edge-1")
                    self.assertEqual(profile["name"], "edge-1")
                    self.assertEqual(profile["protocol"], protocol)
                    config = vpn.build_config("edge-1", profile, 10808, 10809)
                    if protocol == "hysteria2":
                        self.assertEqual(config["auth"], "dummy-user:" + AUTH)
                    else:
                        self.assertEqual(profile["uuid"], UUID)
                        self.assertEqual(profile["wsPath"], "/synthetic-path")
                    self.output.unlink()

    def test_supported_uri_settings_percent_encoding_and_ipv6_preserved(self):
        uris = [self.exports("vless")[0].strip().replace("vpn.example.test:443", "[2001:db8::1]:8443").replace("%2Fsynthetic-path", "%2Fsynthetic%20path%3Fx%3D1%26y%3D2"),
                self.exports("hysteria2")[0].strip().replace("hysteria2://", "hy2://").replace("vpn.example.test:443", "[2001:db8::1]:8443").replace("#Hysteria2", "&alpn=h3&obfs=salamander&obfs-password=dummy%2521#Hysteria2")]
        for uri in uris:
            self.source.write_text("﻿" + uri + "\n")
            profile = import_profile.input_profile(self.source, "edge-1")
            config = vpn.build_config("edge-1", profile, 10808, 10809)
            if profile["protocol"] == "hysteria2":
                self.assertEqual(profile["uri"], uri)
                self.assertEqual(config["auth"], "dummy-user:" + AUTH)
                self.assertEqual(config["obfs"]["salamander"]["password"], "dummy%21")
            else:
                self.assertEqual(profile["server"], "2001:db8::1")
                self.assertEqual(profile["port"], 8443)
                self.assertEqual(profile["sni"], "vpn.example.test")
                self.assertEqual(profile["wsPath"], "/synthetic path?x=1&y=2")

    def test_native_hysteria_ipv6_sni_and_literal_percent_auth(self):
        config = json.loads(self.exports("hysteria2")[1])
        config["server"] = "[2001:db8::1]:8443"
        config["tls"]["sni"] = "tls.example.test"
        self.source.write_text(json.dumps(config))
        profile = import_profile.input_profile(self.source, "other")
        normalized = vpn.build_config("other", profile, 10808, 10809)
        self.assertEqual(normalized["server"], config["server"])
        self.assertEqual(normalized["auth"], config["auth"])
        self.assertEqual(normalized["tls"], config["tls"])

    def test_native_unsupported_insecure_and_ambiguous_inputs(self):
        native = json.loads(self.exports("hysteria2")[1])
        variants = [[], None, {"schemaVersion": 1, "profiles": {}}, {**native, "bandwidth": {"up": "1 mbps"}}, {**native, "obfs": {}},
                    {**native, "tls": {"insecure": True}}, {**native, "tls": {"insecure": 0}},
                    {**native, "tls": {"ca": "dummy"}}, {**native, "tls": {"sni": None}},
                    {**native, "auth": ""}, {**native, "server": "dummy@vpn.example.test:443"},
                    {**native, "server": "vpn.example.test:99999"}, {**native, "server": "vpn.example.test"}]
        xray = json.loads(self.exports("vless")[1])
        variants += [{"outbounds": xray["outbounds"] * 2}]
        for field, value in (("tlsSettings", {"allowInsecure": True}), ("tlsSettings", {"fingerprint": "chrome"}), ("wsSettings", {"headers": {"Authorization": "dummy"}})):
            changed = copy.deepcopy(xray)
            changed["outbounds"][0]["streamSettings"][field] = value
            variants.append(changed)
        for value in variants:
            self.source.write_text(json.dumps(value))
            self.rejected()

    def test_uri_unknown_duplicate_insecure_malformed_options(self):
        vless = self.exports("vless")[0].strip()
        hy2 = self.exports("hysteria2")[0].strip()
        variants = [vless.replace("security=tls", "security=none"), vless.replace("type=ws", "type=tcp"),
                    vless.replace("?", "?fp=chrome&"), vless.replace("?", "?security=tls&"),
                    vless.replace(UUID, "dummy"), vless.replace("%2F", "%ZZ"), vless.replace("%2F", "%FF"),
                    hy2.replace("insecure=0", "insecure=1"), hy2.replace("?", "?alpn=h2&"),
                    hy2.replace("?", "?mport=443-8443&"), hy2 + "\n" + vless, hy2.replace("%40", " ")]
        for value in variants:
            self.source.write_text(value)
            self.rejected()

    def test_corrupt_duplicate_oversized_missing_input(self):
        for value in (b'{"auth":"dummy", "auth":"other"}', b'{"dummy":', b'\xff', b'null', b'x' * (vpn_common.MAX_CONFIG_BYTES + 1)):
            self.source.write_bytes(value)
            self.rejected()
        self.source.unlink()
        self.rejected()

    def test_names_and_parser_values_are_sanitized(self):
        self.source.write_text(self.exports("vless")[0])
        for extra in (["--name", "../dummy"], ["--unknown", AUTH], ["--name", "dummy\nvalue"], ["--name", "-dummy"]):
            self.assertEqual(self.run_cli(extra)[0], 1)
            self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten(self):
        self.source.write_text(self.exports("vless")[0])
        self.output.parent.mkdir(mode=0o700)
        self.output.write_bytes(b"original")
        self.assertEqual(self.run_cli()[0], 1)
        self.assertEqual(self.output.read_bytes(), b"original")

    def test_git_outputs_rejected_before_reading(self):
        for kind in ("directory", "file", "bare"):
            root = self.root / kind
            root.mkdir()
            if kind == "directory":
                (root / ".git").mkdir()
            elif kind == "file":
                (root / ".git").write_text("gitdir: dummy")
            else:
                (root / "HEAD").touch()
                (root / "refs").mkdir()
                (root / "objects").mkdir()
            with patch.object(import_profile, "input_profile") as read:
                with self.assertRaises(vpn_common.ClientError):
                    import_profile.import_profile(self.source, root / "private/bundle.json", "edge-1")
                read.assert_not_called()
        with self.assertRaises(vpn_common.ClientError):
            import_profile.import_profile(self.source, vpn_common.ROOT / "private.json", "edge-1")

    def test_symlink_input_and_output_parent_rejected(self):
        self.source.write_text(self.exports("vless")[0])
        link = self.root / "link"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(vpn_common.ClientError):
            import_profile.input_profile(link, "edge-1")
        link.unlink()
        link.symlink_to(self.root / "missing")
        self.output = link / "bundle.json"
        self.rejected()

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_private_modes_and_existing_parent_permissions_unchanged(self):
        self.source.write_text(self.exports("vless")[0])
        original = stat.S_IMODE(self.root.stat().st_mode)
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.output.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), original)
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_existing_nonprivate_parent_rejected_without_chmod(self):
        self.source.write_text(self.exports("vless")[0])
        self.output.parent.mkdir(mode=0o755)
        self.rejected()
        self.assertEqual(stat.S_IMODE(self.output.parent.stat().st_mode), 0o755)

    def test_write_and_link_failures_leave_no_partial_output(self):
        self.source.write_text(self.exports("vless")[0])
        for operation in ("private_write", "os.link"):
            with patch("import_profile." + operation, side_effect=OSError(AUTH)):
                self.rejected()
            self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_concurrent_output_is_not_overwritten(self):
        self.source.write_text(self.exports("vless")[0])
        link = os.link
        def race(source, destination):
            destination.write_bytes(b"original")
            link(source, destination)
        with patch.object(import_profile.os, "link", side_effect=race):
            self.assertEqual(self.run_cli()[0], 1)
        self.assertEqual(self.output.read_bytes(), b"original")
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])


if __name__ == "__main__":
    unittest.main()
