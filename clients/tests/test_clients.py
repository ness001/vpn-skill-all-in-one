"""Offline tests only; example.test profiles and mocked cores contain no real secrets."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core_install
import vpn
import vpn_common
from vpn_common import ClientError

VLESS = {
    "name": "vless", "server": "vless.example.test", "port": 443, "protocol": "vless",
    "uuid": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "flow": "", "network": "ws",
    "tls": True, "sni": "vless.example.test", "wsPath": "/example-ws", "wsHost": "vless.example.test",
    "allowInsecure": False,
}
HY2 = {"name": "hysteria2", "protocol": "hysteria2", "uri": "hysteria2://test%40only%3Apassword@hysteria2.example.test:443/?sni=tls.example.test&insecure=0#example"}
SECONDARY_HY2 = {"name": "secondary-hy2", "protocol": "hysteria2", "uri": "hysteria2://test-only-secondary-hy2@192.0.2.20:8443/?sni=vpn.example.test&insecure=0"}
FAKE_HASH = "a" * 64


class ConfigurationTests(unittest.TestCase):
    def test_vless_authenticated_tls_and_loopback(self):
        config = vpn.build_config("vless", VLESS, 10808, 10809)
        outbound = config["outbounds"][0]
        user = outbound["settings"]["vnext"][0]["users"][0]
        self.assertEqual(user, {"id": VLESS["uuid"], "encryption": "none"})
        self.assertNotIn("flow", user)
        self.assertEqual(outbound["streamSettings"]["wsSettings"]["path"], "/example-ws")
        self.assertEqual(outbound["streamSettings"]["tlsSettings"], {"serverName": VLESS["sni"], "allowInsecure": False})
        self.assertEqual({item["listen"] for item in config["inbounds"]}, {"127.0.0.1"})
        self.assertEqual(config["log"]["loglevel"], "none")
        self.assertEqual(len(config["outbounds"]), 1)

    def test_vless_rejects_unsafe_or_incompatible_fields(self):
        for field, value in (("tls", False), ("allowInsecure", True), ("flow", "xtls-rprx-vision"),
                             ("network", "tcp"), ("uuid", "not-a-uuid"), ("port", True),
                             ("wsHost", "example.test\r\nSecret: value"), ("wsPath", "relative")):
            with self.subTest(field=field), self.assertRaises(ClientError):
                vpn.build_config("vless", {**VLESS, field: value}, 10808, 10809)

    def test_hysteria2_auth_decoded_once_and_verified_tls(self):
        config = vpn.build_config("hysteria2", HY2, 12080, 12081)
        self.assertEqual(config["auth"], "test@only:password")
        self.assertEqual(config["server"], "hysteria2.example.test:443")
        self.assertEqual(config["tls"], {"sni": "tls.example.test", "insecure": False})
        self.assertEqual(config["socks5"], {"listen": "127.0.0.1:12080"})
        self.assertEqual(config["http"], {"listen": "127.0.0.1:12081"})
        self.assertNotIn("tun", config)
        self.assertNotIn("tcpForwarding", config)

    def test_secondary_hy2_preserves_ip_port_sni_and_strict_tls(self):
        config = vpn.build_config("secondary-hy2", SECONDARY_HY2, 10808, 10809)
        self.assertEqual(config["server"], "192.0.2.20:8443")
        self.assertEqual(config["tls"], {"sni": "vpn.example.test", "insecure": False})
        self.assertEqual(config["auth"], "test-only-secondary-hy2")
        self.assertEqual(config["socks5"]["listen"], "127.0.0.1:10808")
        self.assertEqual(config["http"]["listen"], "127.0.0.1:10809")
        with self.assertRaises(ClientError):
            vpn.build_config("secondary-hy2", {**SECONDARY_HY2, "uri": SECONDARY_HY2["uri"].replace("insecure=0", "insecure=1")}, 10808, 10809)
        with self.assertRaises(ClientError):
            vpn.build_config("invalid.id", SECONDARY_HY2, 10808, 10809)

    def test_hysteria2_username_password_ipv6_and_obfs(self):
        profile = {"protocol": "hysteria2", "uri": "hy2://user:pass%2521@[::1]:444/?obfs=salamander&obfs-password=fake%40only"}
        config = vpn.build_config("hysteria2", profile, 10808, 10809)
        self.assertEqual(config["auth"], "user:pass%21")
        self.assertEqual(config["server"], "[::1]:444")
        self.assertEqual(config["obfs"]["salamander"]["password"], "fake@only")

    def test_hysteria2_rejects_insecure_unknown_and_duplicate_options(self):
        for query in ("insecure=1", "insecure=true", "allowInsecure=1", "sni=a&sni=b", "alpn=h2", "obfs=other", "obfs-password=orphan"):
            with self.subTest(query=query), self.assertRaises(ClientError):
                vpn.build_config("hysteria2", {"protocol": "hysteria2", "uri": f"hy2://fake@hysteria2.example.test/?{query}"}, 10808, 10809)
        for uri in ("hy2://hysteria2.example.test", "http://fake@hysteria2.example.test", "hy2://fake@hysteria2.example.test:99999", "hy2://fake@hysteria2.example.test:0", "hy2://fake@hysteria2.example.test/path"):
            with self.subTest(uri=uri), self.assertRaises(ClientError):
                vpn.build_config("hysteria2", {"protocol": "hysteria2", "uri": uri}, 10808, 10809)

    def test_proxy_port_validation(self):
        for socks, http in ((1, 1), (0, 10809), (10808, 65536), (True, 10809)):
            with self.subTest(ports=(socks, http)), self.assertRaises(ClientError):
                vpn.build_config("vless", VLESS, socks, http)

    def test_occupied_port_detected(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            number = listener.getsockname()[1]
            with self.assertRaisesRegex(ClientError, "unavailable"):
                vpn.check_ports(number, number + 1 if number < 65535 else number - 1)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bundle = self.directory / "vpn-profiles.json"
        self.write_bundle({"schemaVersion": 1, "profiles": {"vless": VLESS, "hysteria2": HY2}})

    def write_bundle(self, value):
        self.bundle.write_text(json.dumps(value), encoding="utf-8")

    def test_load_both_profiles_without_external_key(self):
        self.assertEqual(vpn.load_profile(self.bundle, "vless"), VLESS)
        self.assertEqual(vpn.load_profile(self.bundle, "hysteria2"), HY2)

    def test_optional_secondary_hy2_loads_only_its_own_entry(self):
        self.assertIsNone(vpn.load_profile(self.bundle, "secondary-hy2", optional=True))
        with self.assertRaisesRegex(ClientError, "not configured"):
            vpn.load_profile(self.bundle, "secondary-hy2")
        self.write_bundle({"schemaVersion": 1, "profiles": {"vless": VLESS, "secondary-hy2": SECONDARY_HY2, "hysteria2": HY2}})
        for name, profile in (("vless", VLESS), ("secondary-hy2", SECONDARY_HY2), ("hysteria2", HY2)):
            self.assertEqual(vpn.load_profile(self.bundle, name), profile)
        for invalid in (None, {}, {**SECONDARY_HY2, "name": "hysteria2"}):
            self.write_bundle({"schemaVersion": 1, "profiles": {"secondary-hy2": invalid}})
            with self.subTest(invalid=invalid), self.assertRaises(ClientError):
                vpn.load_profile(self.bundle, "secondary-hy2", optional=True)

    def test_secondary_hy2_doctor_and_mobile_export_remain_local_and_private(self):
        self.write_bundle({"schemaVersion": 1, "profiles": {"vless": VLESS, "secondary-hy2": SECONDARY_HY2, "hysteria2": HY2}})
        output = io.StringIO()
        with patch.object(vpn, "resolve_core", return_value=Path("fake-core")) as resolve, patch.object(vpn, "check_ports"), patch.object(vpn, "Popen") as execute, contextlib.redirect_stdout(output):
            self.assertEqual(vpn.main(["doctor", "secondary-hy2", "--profiles-file", str(self.bundle)]), 0)
        resolve.assert_called_once_with("hysteria2", None, None)
        execute.assert_not_called()
        destination = self.directory / "private-hy2" / "android.txt"
        with patch.object(vpn, "resolve_core") as resolve, contextlib.redirect_stdout(output):
            self.assertEqual(vpn.main(["export-mobile", "--profile", "secondary-hy2", "--device", "android", "--profiles-file", str(self.bundle), "--out", str(destination)]), 0)
        resolve.assert_not_called()
        self.assertEqual(destination.read_text().strip(), SECONDARY_HY2["uri"])
        self.assertNotIn(SECONDARY_HY2["uri"], output.getvalue())
        self.assertNotIn("test-only-secondary-hy2", output.getvalue())

    def test_all_cli_commands_accept_secondary_hy2(self):
        for command in ("fetch-core", "connect", "doctor"):
            self.assertEqual(vpn.parser().parse_args([command, "secondary-hy2"]).profile, "secondary-hy2")
        self.write_bundle({"schemaVersion": 1, "profiles": {"secondary-hy2": SECONDARY_HY2}})
        with patch.object(vpn, "fetch_core") as fetch:
            self.assertEqual(vpn.main(["fetch-core", "secondary-hy2", "--profiles-file", str(self.bundle)]), 0)
        fetch.assert_called_once_with("hysteria2", None, online=False)

    def test_corrupted_bundle_sanitized(self):
        for invalid in (b'{"DO-NOT-PRINT":', b'\xff'):
            self.bundle.write_bytes(invalid)
            with self.assertRaisesRegex(ClientError, "Invalid profile bundle") as caught:
                vpn.load_profile(self.bundle, "vless")
            self.assertNotIn("DO-NOT-PRINT", str(caught.exception))

    def test_schema_and_missing_profile(self):
        for value in ({"schemaVersion": 2}, {"schemaVersion": True}, {"schemaVersion": 1.0}, {"schemaVersion": 1, "profiles": []}, [], {"schemaVersion": 1, "profiles": {}}, {"schemaVersion": 1, "profiles": {"vless": {"name": "hysteria2"}}}, {"schemaVersion": 1, "profiles": {"vless": {}}}):
            self.write_bundle(value)
            with self.subTest(value=value), self.assertRaises(ClientError):
                vpn.load_profile(self.bundle, "vless")

    def test_missing_and_oversized_bundle(self):
        self.bundle.unlink()
        with self.assertRaisesRegex(ClientError, "Cannot read"):
            vpn.load_profile(self.bundle, "vless")
        self.bundle.write_bytes(b"x" * (vpn.MAX_CONFIG_BYTES + 1))
        with self.assertRaisesRegex(ClientError, "size limit"):
            vpn.load_profile(self.bundle, "vless")

    def test_unknown_profile_rejected(self):
        with self.assertRaisesRegex(ClientError, "not configured"):
            vpn.load_profile(self.bundle, "unknown")

    def test_doctor_does_not_execute_core_or_print_secrets(self):
        output = io.StringIO()
        with patch.object(vpn, "resolve_core", return_value=Path("fake-core")), patch.object(vpn, "check_ports"), patch.object(vpn, "Popen") as execute, contextlib.redirect_stdout(output):
            status = vpn.main(["doctor", "vless", "--profiles-file", str(self.bundle)])
        self.assertEqual(status, 0)
        execute.assert_not_called()
        self.assertIn("No core executed", output.getvalue())
        self.assertNotIn(VLESS["uuid"], output.getvalue())
        self.assertNotIn(VLESS["server"], output.getvalue())

    def test_export_cli_works_without_a_key_or_core(self):
        destination = self.directory / "private-export" / "android.txt"
        output = io.StringIO()
        with patch.object(vpn, "resolve_core") as core, contextlib.redirect_stdout(output):
            status = vpn.main(["export-mobile", "--profile", "hysteria2", "--device", "android", "--profiles-file", str(self.bundle), "--output", str(destination)])
        self.assertEqual(status, 0)
        self.assertEqual(destination.read_text().strip(), HY2["uri"])
        self.assertNotIn(HY2["uri"], output.getvalue())
        core.assert_not_called()

    def test_default_bundle_and_no_key_option(self):
        for operation in ("doctor", "connect"):
            args = vpn.parser().parse_args([operation, "vless"])
            self.assertEqual(args.profiles_file, vpn.ROOT / "profiles" / "vpn-profiles.json")
            self.assertFalse(hasattr(args, "key_file"))
        args = vpn.parser().parse_args(["export-mobile", "--profile", "hysteria2", "--device", "android", "--out", "dummy.txt"])
        self.assertEqual(args.output, Path("dummy.txt"))
        self.assertEqual(args.profiles_file, vpn.ROOT / "profiles" / "vpn-profiles.json")

    def test_unexpected_exception_details_never_print(self):
        output = io.StringIO()
        with patch.object(vpn, "load_profile", side_effect=OSError("secret auth-token /private/profiles")), contextlib.redirect_stderr(output):
            status = vpn.main(["doctor", "vless", "--profiles-file", str(self.bundle)])
        self.assertEqual(status, 1)
        self.assertIn("OSError", output.getvalue())
        self.assertNotIn("auth-token", output.getvalue())
        self.assertNotIn("/private/profiles", output.getvalue())


class MobileExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_vless_uri_preserves_authenticated_ws_tls(self):
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(vpn.mobile_uri("vless", VLESS, "android"))
        self.assertEqual(parsed.scheme, "vless")
        self.assertEqual(parsed.username, VLESS["uuid"])
        query = parse_qs(parsed.query)
        self.assertEqual(query["path"], [VLESS["wsPath"]])
        self.assertEqual(query["host"], [VLESS["wsHost"]])
        self.assertEqual(query["security"], ["tls"])
        self.assertNotIn("flow", query)

    def test_hysteria2_uri_selects_device_and_preserves_verification(self):
        iphone = "hysteria2://iphone-example-only@hysteria2.example.test/?insecure=0&sni=tls.example.test"
        profile = {**HY2, "mobileUris": {"android": HY2["uri"], "iphone": iphone}}
        self.assertEqual(vpn.mobile_uri("hysteria2", profile, "iphone"), iphone)
        self.assertEqual(vpn.mobile_uri("hysteria2", profile, "android"), HY2["uri"])
        self.assertEqual(vpn.mobile_uri("hysteria2", HY2, "iphone"), HY2["uri"])
        with self.assertRaises(ClientError):
            vpn.mobile_uri("hysteria2", {**HY2, "mobileUris": {"android": "hy2://fake@example.test/?insecure=1"}}, "android")

    def test_secondary_hy2_mobile_uris_use_device_credentials_without_changing_endpoint(self):
        iphone = SECONDARY_HY2["uri"].replace("test-only-secondary-hy2", "test-only-vless-iphone")
        android = SECONDARY_HY2["uri"].replace("test-only-secondary-hy2", "test-only-vless-android")
        profile = {**SECONDARY_HY2, "mobileUris": {"android": android, "iphone": iphone}}
        self.assertEqual(vpn.mobile_uri("secondary-hy2", profile, "iphone"), iphone)
        self.assertEqual(vpn.mobile_uri("secondary-hy2", profile, "android"), android)
        self.assertEqual(vpn.mobile_uri("secondary-hy2", SECONDARY_HY2, "iphone"), SECONDARY_HY2["uri"])
        with self.assertRaises(ClientError):
            vpn.mobile_uri("secondary-hy2", {**SECONDARY_HY2, "mobileUris": {"android": android.replace("insecure=0", "insecure=1")}}, "android")

    def test_export_creates_private_parent_and_never_prints_uri(self):
        destination = self.directory / "hysteria2-private" / "android.txt"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            vpn.export_mobile("hysteria2", HY2, "android", destination)
        self.assertEqual(destination.read_text().strip(), HY2["uri"])
        self.assertNotIn(HY2["uri"], output.getvalue())
        self.assertNotIn("test@only", output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            vpn.export_mobile("vless", VLESS, "iphone", destination.parent / "vless.txt")
        self.assertTrue((destination.parent / "vless.txt").exists())
        with self.assertRaisesRegex(ClientError, "already exists"):
            vpn.export_mobile("hysteria2", HY2, "android", destination)
        self.assertEqual(destination.read_text().strip(), HY2["uri"])

    def test_export_refuses_repository_and_other_git_repository(self):
        with patch.object(vpn, "ROOT", self.directory), self.assertRaisesRegex(ClientError, "outside"):
            vpn.export_mobile("vless", VLESS, "android", self.directory / "private" / "out.txt")
        (self.directory / ".git").mkdir()
        with self.assertRaisesRegex(ClientError, "Git repository"):
            vpn.export_mobile("vless", VLESS, "android", self.directory / "private" / "out.txt")

    def test_export_does_not_restrict_existing_public_directory(self):
        parent = self.directory / "existing"
        parent.mkdir()
        if os.name != "nt":
            parent.chmod(0o755)
        with self.assertRaisesRegex(ClientError, "user-only|mode 700"):
            vpn.export_mobile("vless", VLESS, "android", parent / "out.txt")
        self.assertFalse((parent / "out.txt").exists())


class LifecycleTests(unittest.TestCase):
    def test_private_cleanup_retries_transient_windows_locks(self):
        directory = MagicMock()
        directory.cleanup.side_effect = [PermissionError('file locked'), None]
        with patch.object(vpn_common.time, 'sleep') as sleep:
            vpn_common.cleanup_private_directory(directory)
        self.assertEqual(directory.cleanup.call_count, 2)
        sleep.assert_called_once()

    def test_private_cleanup_failure_is_bounded_and_not_silent(self):
        directory = MagicMock()
        directory.cleanup.side_effect = PermissionError('private-secret-path')
        with self.assertRaisesRegex(vpn_common.CleanupError, 'Cleanup did not complete') as caught:
            vpn_common.cleanup_private_directory(directory, timeout=0)
        self.assertEqual(directory.cleanup.call_count, 1)
        self.assertNotIn('private-secret-path', str(caught.exception))

    def test_private_directory_and_file_cleaned(self):
        with vpn_common.private_directory() as directory:
            path = directory / "config.json"
            vpn_common.private_write(path, b"example-only")
            self.assertTrue(path.exists())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(directory.exists())

    def test_spawn_failure_still_cleans_private_config(self):
        paths = []
        def fail(command, **kwargs):
            paths.append(Path(command[-1]))
            self.assertTrue(paths[0].is_file())
            raise OSError("simulated failure")
        with patch.object(vpn, "check_ports"), patch.object(vpn, "Popen", side_effect=fail), self.assertRaises(OSError):
            vpn.run_core("vless", vpn.build_config("vless", VLESS, 10808, 10809), Path("fake-core"), 10808, 10809, 1)
        self.assertFalse(paths[0].parent.exists())

    def test_ctrl_c_stops_only_owned_child_and_removes_config(self):
        child = MagicMock()
        child.poll.return_value = None
        child.wait.side_effect = [KeyboardInterrupt(), 0]
        paths = []
        def spawn(command, **kwargs):
            paths.append(Path(command[-1]))
            config = json.loads(paths[0].read_text())
            self.assertEqual(config["auth"], "test@only:password")
            self.assertNotIn("test@only:password", " ".join(command))
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            return child
        with patch.object(vpn, "check_ports"), patch.object(vpn, "wait_ready"), patch.object(vpn, "Popen", side_effect=spawn), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            vpn.run_core("hysteria2", vpn.build_config("hysteria2", HY2, 10808, 10809), Path("fake-core"), 10808, 10809, 1)
        child.terminate.assert_called_once_with()
        child.kill.assert_not_called()
        self.assertFalse(paths[0].parent.exists())

    def test_secondary_hy2_runs_hysteria_command_with_private_config_and_cleanup(self):
        child = MagicMock()
        paths = []
        def spawn(command, **kwargs):
            self.assertEqual(command[1:3], ["client", "--config"])
            paths.append(Path(command[-1]))
            config = json.loads(paths[-1].read_text())
            self.assertEqual(config["server"], "192.0.2.20:8443")
            self.assertEqual(config["tls"], {"sni": "vpn.example.test", "insecure": False})
            self.assertNotIn(config["auth"], " ".join(command))
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            return child
        with patch.object(vpn, "check_ports"), patch.object(vpn, "wait_ready"), patch.object(vpn, "Popen", side_effect=spawn), patch.object(vpn, "stop_child") as stop:
            with vpn.running_core("hysteria2", vpn.build_config("secondary-hy2", SECONDARY_HY2, 10808, 10809), Path("fake-core"), 10808, 10809, 1) as running:
                self.assertIs(running, child)
                self.assertTrue(paths[0].exists())
        stop.assert_called_once_with(child)
        self.assertFalse(paths[0].parent.exists())

    def test_readiness_failure_stops_child_and_removes_config(self):
        child = MagicMock()
        child.poll.return_value = None
        with patch.object(vpn, "check_ports"), patch.object(vpn, "wait_ready", side_effect=ClientError("timeout")), patch.object(vpn, "Popen", return_value=child) as spawn, self.assertRaisesRegex(ClientError, "timeout"):
            vpn.run_core("vless", {}, Path("fake-core"), 10808, 10809, 1)
        child.terminate.assert_called_once_with()
        self.assertFalse(Path(spawn.call_args.args[0][-1]).parent.exists())

    def test_stop_kills_only_after_graceful_timeout(self):
        child = MagicMock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired("fake", 5), 0]
        vpn.stop_child(child)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()

    def test_exited_child_is_not_signalled(self):
        child = MagicMock()
        child.poll.return_value = 0
        vpn.stop_child(child)
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_readiness_bounded_and_early_exit_reported(self):
        child = MagicMock()
        child.poll.return_value = 7
        with self.assertRaisesRegex(ClientError, "status 7"):
            vpn.wait_ready(child, 10808, 10809, 1)
        child.poll.return_value = None
        with patch.object(vpn.time, "monotonic", side_effect=[0, 2]), self.assertRaisesRegex(ClientError, "timed out"):
            vpn.wait_ready(child, 10808, 10809, 1)

    def test_readiness_checks_both_local_listeners(self):
        child = MagicMock()
        child.poll.return_value = None
        connection = MagicMock()
        with patch.object(vpn.socket, "create_connection", return_value=connection) as connect:
            vpn.wait_ready(child, 10808, 10809, 1)
        self.assertEqual([call.args[0] for call in connect.call_args_list], [("127.0.0.1", 10808), ("127.0.0.1", 10809)])

    def test_invalid_timeout_never_spawns(self):
        for value in (-1, 0, 121, float("inf"), float("nan")):
            with self.subTest(timeout=value), patch.object(vpn, "Popen") as spawn, self.assertRaises(ClientError):
                vpn.run_core("vless", {}, Path("fake-core"), 10808, 10809, value)
            spawn.assert_not_called()


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bundled = self.directory / "vendor" / "cores"
        bundle = patch.object(core_install, "BUNDLED", self.bundled)
        bundle.start()
        self.addCleanup(bundle.stop)

    def local_core(self, profile="vless", system="windows-amd64", base=None):
        directory, name = core_install.install_location(profile, system, self.bundled if base is None else base)
        directory.mkdir(parents=True)
        core = directory / name
        core.write_bytes(b"fake executable, never executed")
        core.chmod(0o700)
        release = core_install.RELEASES[profile]
        manifest = {
            "schemaVersion": 1, "profile": profile, "project": release["project"],
            "tag": release["tag"], "platform": system, "asset": release["assets"][system],
            "assetSha256": FAKE_HASH, "binarySha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        }
        (directory / "verified.json").write_text(json.dumps(manifest))
        return core

    def pin(self, binary, archive=None):
        payload = binary if archive is None else archive
        pin = {"assetSize": len(payload), "assetSha256": hashlib.sha256(payload).hexdigest(),
               "binarySha256": hashlib.sha256(binary).hexdigest()}
        mock = patch.object(core_install, "pinned_asset", return_value=pin)
        mock.start()
        self.addCleanup(mock.stop)

    def metadata(self, profile="vless", system="windows-amd64", digest=FAKE_HASH):
        release = core_install.RELEASES[profile]
        asset = release["assets"][system]
        return {
            "tag_name": release["tag"], "draft": False, "prerelease": False,
            "assets": [{"name": asset, "size": 100,
                        "browser_download_url": f"https://github.com/{release['project']}/releases/download/{release['tag']}/{asset}",
                        "digest": f"sha256:{digest}" if digest else None}],
        }

    def test_public_core_manifest_has_pinned_links_without_release_bytes(self):
        for entry in json.loads((core_install.ROOT / 'vendor/manifest.json').read_text())['cores']:
            pin = core_install.pinned_asset(entry['profile'], entry['platform'])
            self.assertEqual(pin['assetSha256'], entry['assetSha256'])
            self.assertNotIn('path', entry)
            self.assertNotIn('verifiedManifest', entry)
        self.assertFalse((core_install.ROOT / 'vendor/cores').exists())

    def test_tampered_legacy_bundle_blocks_even_explicit_download(self):
        self.local_core('hysteria2').write_bytes(b'tampered')
        with patch.object(core_install, 'platform_id', return_value='windows-amd64'), patch.object(core_install, 'download') as get, self.assertRaisesRegex(ClientError, 'checksum'):
            core_install.fetch_core('hysteria2', tools=self.directory / 'cache', online=True)
        get.assert_not_called()

    def test_platform_mapping(self):
        for system, machine, expected in (("Windows", "AMD64", "windows-amd64"), ("Darwin", "x86_64", "darwin-amd64"), ("Darwin", "arm64", "darwin-arm64")):
            with patch.object(core_install.platform, "system", return_value=system), patch.object(core_install.platform, "machine", return_value=machine):
                self.assertEqual(core_install.platform_id(), expected)
        with patch.object(core_install.platform, "system", return_value="Linux"), self.assertRaises(ClientError):
            core_install.platform_id()

    def test_release_digest_pinned_and_explicit_must_match(self):
        asset = core_install.RELEASES["vless"]["assets"]["windows-amd64"]
        _, digest = core_install.release_digest(self.metadata(), "vless", asset, None)
        self.assertEqual(digest, FAKE_HASH)
        with self.assertRaisesRegex(ClientError, "disagrees"):
            core_install.release_digest(self.metadata(), "vless", asset, "b" * 64)
        for field, value in (("prerelease", True), ("draft", True), ("tag_name", "latest")):
            metadata = self.metadata()
            metadata[field] = value
            with self.assertRaisesRegex(ClientError, "pinned stable"):
                core_install.release_digest(metadata, "vless", asset, None)

    def test_missing_digest_fails_closed(self):
        asset = core_install.RELEASES["vless"]["assets"]["windows-amd64"]
        with self.assertRaisesRegex(ClientError, "no published"):
            core_install.release_digest(self.metadata(digest=None), "vless", asset, None)
        _, digest = core_install.release_digest(self.metadata(digest=None), "vless", asset, FAKE_HASH)
        self.assertEqual(digest, FAKE_HASH)

    def test_download_hosts_are_https_only(self):
        for url in ("http://github.com/x", "https://github.com.evil.test/x", "https://evil.test/x", "https://u:p@github.com/x", "https://github.com:444/x"):
            with self.subTest(url=url), self.assertRaises(ClientError):
                core_install.validate_download_url(url)
        core_install.validate_download_url("https://release-assets.githubusercontent.com/example")

    def test_download_refuses_large_body_and_redirect_target(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {}
        response.geturl.return_value = "https://github.com/example"
        response.read.side_effect = [b"1234", b"5678", b""]
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(core_install.urllib.request, "build_opener", return_value=opener), self.assertRaisesRegex(ClientError, "size limit"):
            core_install.download("https://github.com/example", self.directory / "too-large", 5)
        with self.assertRaisesRegex(ClientError, "official HTTPS"):
            core_install.SafeRedirect().redirect_request(None, None, 302, None, {}, "http://evil.example.test/file")

    def test_release_asset_wrong_host_missing_or_ambiguous(self):
        asset = core_install.RELEASES["vless"]["assets"]["windows-amd64"]
        for mode in ("url", "missing", "duplicate"):
            metadata = self.metadata()
            if mode == "url":
                metadata["assets"][0]["browser_download_url"] = "https://evil.example.test/core.exe"
            elif mode == "missing":
                metadata["assets"] = []
            else:
                metadata["assets"] *= 2
            with self.subTest(mode=mode), self.assertRaises(ClientError):
                core_install.release_digest(metadata, "vless", asset, None)

    def test_archive_only_extracts_expected_binary(self):
        archive = self.directory / "core.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("xray.exe", b"fake executable")
            package.writestr("README.md", b"not installed")
        output = self.directory / "xray.exe"
        core_install.extract_binary(archive, output, "xray.exe")
        self.assertEqual(output.read_bytes(), b"fake executable")
        self.assertFalse((self.directory / "README.md").exists())

    def test_traversal_absolute_symlink_and_duplicate_archive_rejected(self):
        for name in ("../outside", "/absolute", "C:/absolute", "..\\outside", "link"):
            archive = self.directory / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("xray.exe", b"fake")
                info = zipfile.ZipInfo(name)
                if name == "link":
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                package.writestr(info, b"target")
            with self.subTest(name=name), self.assertRaisesRegex(ClientError, "Unsafe"):
                core_install.extract_binary(archive, self.directory / "out", "xray.exe")

    def test_archive_missing_duplicate_binary_and_size_limit(self):
        for mode in ("missing", "duplicate", "oversized"):
            archive = self.directory / "invalid.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("other" if mode == "missing" else "xray.exe", b"example")
                if mode == "duplicate":
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        package.writestr("xray.exe", b"duplicate")
            with self.subTest(mode=mode), patch.object(core_install, "MAX_UNPACKED", 1 if mode == "oversized" else 1024), self.assertRaises(ClientError):
                core_install.extract_binary(archive, self.directory / "out", "xray.exe")

    def test_external_binary_rehashed_and_missing_hash_rejected(self):
        core = self.directory / "fake-core"
        core.write_bytes(b"fake executable, never executed")
        core.chmod(0o700)
        with self.assertRaisesRegex(ClientError, "requires"):
            core_install.resolve_core("vless", str(core), None)
        digest = hashlib.sha256(core.read_bytes()).hexdigest()
        self.assertEqual(core_install.resolve_core("vless", str(core), digest), core.resolve())
        core.write_bytes(b"tampered")
        with self.assertRaisesRegex(ClientError, "checksum"):
            core_install.resolve_core("vless", str(core), digest)

    def test_bundled_cores_verified_offline_for_all_six_targets(self):
        tools = self.directory / "tools"
        for profile in ("vless", "hysteria2"):
            for system in ("windows-amd64", "darwin-amd64", "darwin-arm64"):
                core = self.local_core(profile, system)
                output = io.StringIO()
                with self.subTest(profile=profile, system=system), patch.object(core_install, "platform_id", return_value=system), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")) as download, contextlib.redirect_stdout(output):
                    self.assertEqual(core_install.fetch_core(profile, tools=tools), core)
                    self.assertEqual(core_install.resolve_core(profile, None, None, tools), core)
                    download.assert_not_called()
                    self.assertIn("Verified bundled", output.getvalue())
        self.assertFalse(tools.exists())

    def test_secondary_hy2_reuses_exact_hysteria2_bundle_on_every_supported_platform(self):
        tools = self.directory / "tools"
        for system in ("windows-amd64", "darwin-amd64", "darwin-arm64"):
            core = self.local_core("hysteria2", system)
            manifest = core.parent / "verified.json"
            before = manifest.read_bytes()
            with self.subTest(system=system), patch.object(core_install, "platform_id", return_value=system), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(core_install.install_location("hysteria2", system, self.bundled), core_install.install_location("hysteria2", system, self.bundled))
                self.assertEqual(core_install.resolve_core("hysteria2", None, None, tools), core)
                self.assertEqual(core_install.fetch_core("hysteria2", tools=tools), core)
                self.assertEqual(core_install.resolve_core("hysteria2", None, None, tools), core)
                self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(set(core_install.RELEASES), {"vless", "hysteria2"})
        self.assertFalse(tools.exists())

    def test_secondary_hy2_alias_never_weakens_manifest_or_checksum_validation(self):
        core = self.local_core("hysteria2")
        tools = self.directory / "tools"
        self.local_core("hysteria2", base=tools)
        path = core.parent / "verified.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")):
            for field, value in (("profile", "secondary-hy2"), ("profile", "vless"), ("profile", "new"), ("project", "other/core"), ("tag", "latest"), ("platform", "darwin-arm64"), ("asset", "other.exe"), ("binarySha256", "b" * 64)):
                path.write_text(json.dumps({**manifest, field: value}))
                with self.subTest(field=field, value=value), self.assertRaises(ClientError):
                    core_install.resolve_core("hysteria2", None, None, tools)
            path.write_bytes(original)
            core.write_bytes(b"tampered")
            with self.assertRaisesRegex(ClientError, "checksum"):
                core_install.fetch_core("hysteria2", tools=tools)
            core.unlink()
            with self.assertRaisesRegex(ClientError, "incomplete"):
                core_install.resolve_core("hysteria2", None, None, tools)
            with self.assertRaisesRegex(ClientError, "Choose"):
                core_install.resolve_core("unknown", None, None, tools)

    def test_secondary_hy2_online_fetch_records_canonical_hysteria2_cache_and_reuses_it(self):
        binary = b"dummy shared Hysteria executable, never executed"
        digest = hashlib.sha256(binary).hexdigest()
        self.pin(binary)
        def download(url, destination, limit):
            destination.write_bytes(json.dumps(self.metadata("hysteria2", digest=digest)).encode() if "api.github.com" in url else binary)
        tools = self.directory / "tools"
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=download) as get, contextlib.redirect_stdout(io.StringIO()):
            core = core_install.fetch_core("hysteria2", tools=tools, online=True)
            self.assertEqual(json.loads((core.parent / "verified.json").read_text())["profile"], "hysteria2")
            self.assertEqual(core_install.resolve_core("hysteria2", None, None, tools), core)
            self.assertEqual(core_install.resolve_core("hysteria2", None, None, tools), core)
            self.assertEqual(core_install.fetch_core("hysteria2", tools=tools, online=True), core)
            self.assertEqual(get.call_count, 2)
            core.write_bytes(b"tampered")
            with self.assertRaisesRegex(ClientError, "checksum"):
                core_install.resolve_core("hysteria2", None, None, tools)

    def test_bundle_preferred_over_existing_cache(self):
        core = self.local_core()
        tools = self.directory / "tools"
        cached = self.local_core(base=tools)
        cached.write_bytes(b"bad cache must not override bundle")
        with patch.object(core_install, "platform_id", return_value="windows-amd64"):
            self.assertEqual(core_install.resolve_core("vless", None, None, tools), core)

    def test_bundle_rehashed_every_use_and_corruption_cannot_fall_back(self):
        core = self.local_core()
        tools = self.directory / "tools"
        self.local_core(base=tools)
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")) as download, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(core_install.fetch_core("vless", tools=tools), core)
            core.write_bytes(b"tampered")
            with self.assertRaisesRegex(ClientError, "checksum"):
                core_install.resolve_core("vless", None, None, tools)
            with self.assertRaisesRegex(ClientError, "checksum"):
                core_install.fetch_core("vless", tools=tools)
            download.assert_not_called()

    def test_missing_bundled_binary_cannot_fall_back_to_cache(self):
        core = self.local_core()
        tools = self.directory / "tools"
        self.local_core(base=tools)
        core.unlink()
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")), self.assertRaisesRegex(ClientError, "Bundled core is incomplete"):
            core_install.fetch_core("vless", tools=tools)

    def test_bundled_manifest_requires_exact_identity(self):
        core = self.local_core()
        path = core.parent / "verified.json"
        manifest = json.loads(path.read_text())
        for field, value in (("schemaVersion", True), ("schemaVersion", 1.0), ("profile", "old"), ("project", "other/core"), ("tag", "latest"), ("platform", "darwin-arm64"), ("asset", "other.zip")):
            path.write_text(json.dumps({**manifest, field: value}))
            with self.subTest(field=field, value=value), patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")), self.assertRaisesRegex(ClientError, "Bundled core metadata"):
                core_install.fetch_core("vless", tools=self.directory / "tools")

    def test_bundled_manifest_malformed_missing_or_invalid_hash_fails_closed(self):
        core = self.local_core()
        path = core.parent / "verified.json"
        manifest = json.loads(path.read_text())
        for content in (b"invalid json", b"[]", b"null", b"{}", json.dumps({**manifest, "binarySha256": None}).encode(), json.dumps({**manifest, "assetSha256": "bad"}).encode()):
            path.write_bytes(content)
            with self.subTest(content=content), patch.object(core_install, "platform_id", return_value="windows-amd64"), self.assertRaises(ClientError):
                core_install.resolve_core("vless", None, None, self.directory / "tools")
        path.unlink()
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), self.assertRaisesRegex(ClientError, "metadata is missing or invalid"):
            core_install.resolve_core("vless", None, None, self.directory / "tools")

    def test_missing_bundle_and_cache_never_download_automatically(self):
        tools = self.directory / "tools"
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")) as download:
            with self.assertRaisesRegex(ClientError, "no download attempted.*--online"):
                core_install.fetch_core("vless", tools=tools)
            download.assert_not_called()
        self.assertFalse(tools.exists())

    def test_sha256_does_not_opt_in_to_network(self):
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=AssertionError("Network forbidden")), self.assertRaisesRegex(ClientError, "--online explicitly"):
            core_install.fetch_core("vless", FAKE_HASH, tools=self.directory / "tools")

    def test_external_core_explicitly_overrides_corrupt_bundle(self):
        self.local_core().write_bytes(b"bad bundle")
        core = self.directory / "external"
        core.write_bytes(b"trusted external, never executed")
        core.chmod(0o700)
        self.assertEqual(core_install.resolve_core("vless", str(core), hashlib.sha256(core.read_bytes()).hexdigest()), core.resolve())

    def test_cli_online_option_is_explicit_and_only_for_fetch(self):
        self.assertFalse(vpn.parser().parse_args(["fetch-core", "vless"]).online)
        self.assertTrue(vpn.parser().parse_args(["fetch-core", "hysteria2", "--online"]).online)
        for command in ("doctor", "connect"):
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                vpn.parser().parse_args([command, "vless", "--online"])
        with patch.object(vpn, "fetch_core") as fetch:
            self.assertEqual(vpn.main(["fetch-core", "hysteria2", "--online", "--sha256", FAKE_HASH]), 0)
            fetch.assert_called_once_with("hysteria2", FAKE_HASH, online=True)

    def test_installer_verifies_and_reuses_binary_without_execution(self):
        binary = b"fake hysteria, never execute"
        digest = hashlib.sha256(binary).hexdigest()
        self.pin(binary)
        def download(url, destination, limit):
            destination.write_bytes(json.dumps(self.metadata("hysteria2", digest=digest)).encode() if "api.github.com" in url else binary)
        tools = self.directory / "tools"
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=download) as get, contextlib.redirect_stdout(io.StringIO()):
            installed = core_install.fetch_core("hysteria2", tools=tools, online=True)
            self.assertEqual(installed.read_bytes(), binary)
            self.assertEqual(core_install.resolve_core("hysteria2", None, None, tools), installed)
            self.assertEqual(core_install.fetch_core("hysteria2", tools=tools), installed)
            self.assertEqual(get.call_count, 2)
            installed.write_bytes(b"modified")
            with self.assertRaisesRegex(ClientError, "checksum"):
                core_install.resolve_core("hysteria2", None, None, tools)

    def test_online_download_remains_explicit_when_bundle_exists(self):
        bundled = self.local_core("hysteria2")
        binary = b"fresh official release fixture, never executed"
        digest = hashlib.sha256(binary).hexdigest()
        self.pin(binary)
        def download(url, destination, limit):
            destination.write_bytes(json.dumps(self.metadata("hysteria2", digest=digest)).encode() if "api.github.com" in url else binary)
        tools = self.directory / "tools"
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=download) as get, contextlib.redirect_stdout(io.StringIO()):
            downloaded = core_install.fetch_core("hysteria2", tools=tools, online=True)
            self.assertEqual(downloaded.read_bytes(), binary)
            self.assertEqual(get.call_count, 2)
            self.assertNotEqual(downloaded, bundled)
            self.assertEqual(core_install.resolve_core("hysteria2", None, None, tools), bundled)
            self.assertEqual(core_install.fetch_core("hysteria2", tools=tools, online=True), downloaded)
            self.assertEqual(get.call_count, 2)
            with self.assertRaisesRegex(ClientError, "disagrees"):
                core_install.fetch_core("hysteria2", FAKE_HASH, tools=tools, online=True)

    def test_online_explicit_digest_without_published_hash(self):
        binary = b"manual trusted fixture, never executed"
        digest = hashlib.sha256(binary).hexdigest()
        self.pin(binary)
        def download(url, destination, limit):
            destination.write_bytes(json.dumps(self.metadata("hysteria2", digest=None)).encode() if "api.github.com" in url else binary)
        tools = self.directory / "tools"
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=download), contextlib.redirect_stdout(io.StringIO()):
            core = core_install.fetch_core("hysteria2", digest, tools=tools, online=True)
            self.assertEqual(core.read_bytes(), binary)
            self.assertEqual(core_install.resolve_core("hysteria2", None, None, tools), core)

    def test_online_xray_verifies_archive_and_records_executable_hash(self):
        binary = b"fake xray, never execute"
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("xray.exe", binary)
        archive_bytes = archive.getvalue()
        digest = hashlib.sha256(archive_bytes).hexdigest()
        self.pin(binary, archive_bytes)
        def download(url, destination, limit):
            destination.write_bytes(json.dumps(self.metadata(digest=digest)).encode() if "api.github.com" in url else archive_bytes)
        tools = self.directory / "tools"
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=download), contextlib.redirect_stdout(io.StringIO()):
            core = core_install.fetch_core("vless", tools=tools, online=True)
            manifest = json.loads((core.parent / "verified.json").read_text())
            self.assertEqual(manifest["assetSha256"], digest)
            self.assertEqual(manifest["binarySha256"], hashlib.sha256(binary).hexdigest())
            self.assertNotEqual(manifest["assetSha256"], manifest["binarySha256"])
            self.assertEqual(core_install.resolve_core("vless", None, None, tools), core)

    def test_installed_manifest_pinned_metadata_checked(self):
        tools = self.directory / "tools"
        directory, binary_name = core_install.install_location("hysteria2", "windows-amd64", tools)
        directory.mkdir(parents=True)
        binary = directory / binary_name
        binary.write_bytes(b"fake executable")
        binary.chmod(0o700)
        release = core_install.RELEASES["hysteria2"]
        manifest = {
            "schemaVersion": 1, "profile": "hysteria2", "project": release["project"],
            "tag": release["tag"], "platform": "windows-amd64",
            "asset": release["assets"]["windows-amd64"], "assetSha256": FAKE_HASH,
            "binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        }
        path = directory / "verified.json"
        for field in ("schemaVersion", "profile", "project", "tag", "platform", "asset"):
            path.write_text(json.dumps({**manifest, field: "changed"}))
            with self.subTest(field=field), patch.object(core_install, "platform_id", return_value="windows-amd64"), self.assertRaisesRegex(ClientError, "metadata"):
                core_install.resolve_core("hysteria2", None, None, tools)
        path.write_text(json.dumps({**manifest, "binarySha256": "invalid"}))
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), self.assertRaisesRegex(ClientError, "64-character"):
            core_install.resolve_core("hysteria2", None, None, tools)

    def test_cached_profile_label_verified_read_only_for_both_cores(self):
        tools = self.directory / "tools"
        for profile in ("vless", "hysteria2"):
            directory, binary_name = core_install.install_location(profile, "windows-amd64", tools)
            directory.mkdir(parents=True)
            binary = directory / binary_name
            binary.write_bytes(b"fake cached executable")
            binary.chmod(0o700)
            release = core_install.RELEASES[profile]
            manifest = {
                "schemaVersion": 1, "profile": profile, "project": release["project"],
                "tag": release["tag"], "platform": "windows-amd64",
                "asset": release["assets"]["windows-amd64"], "assetSha256": FAKE_HASH,
                "binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            }
            path = directory / "verified.json"
            path.write_text(json.dumps(manifest))
            before = path.read_bytes()
            output = io.StringIO()
            with self.subTest(profile=profile), patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download") as download, contextlib.redirect_stdout(output):
                self.assertEqual(core_install.fetch_core(profile, tools=tools), binary)
                download.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
                self.assertIn("no download needed", output.getvalue())
                for field in ("project", "tag", "platform", "asset"):
                    path.write_text(json.dumps({**manifest, field: "changed"}))
                    with self.subTest(field=field), self.assertRaisesRegex(ClientError, "metadata"):
                        core_install.resolve_core(profile, None, None, tools)
                path.write_bytes(before)
                binary.write_bytes(b"tampered")
                with self.assertRaisesRegex(ClientError, "checksum"):
                    core_install.resolve_core(profile, None, None, tools)

    def test_download_hash_mismatch_never_installs(self):
        self.pin(b"expected original")
        def download(url, destination, limit):
            destination.write_bytes(json.dumps(self.metadata("hysteria2")).encode() if "api.github.com" in url else b"invalid content")
        tools = self.directory / "tools"
        with patch.object(core_install, "platform_id", return_value="windows-amd64"), patch.object(core_install, "download", side_effect=download), self.assertRaisesRegex(ClientError, "checksum|disagrees"):
            core_install.fetch_core("hysteria2", tools=tools, online=True)
        destination, _ = core_install.install_location("hysteria2", "windows-amd64", tools)
        self.assertFalse(destination.exists())
        self.assertEqual(list(destination.parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
