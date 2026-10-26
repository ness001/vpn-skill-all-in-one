"""Local-only tests: no root, network, real credentials or server changes."""

import contextlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

import install
import render

VLESS = {"uuid": "12345678-1234-4123-8123-123456789012", "ws_path": "/example-test-path"}
HY2 = {"password": "example-only-password-not-a-real-credential"}


class RenderingTests(unittest.TestCase):
    def target(self, profile):
        return render.validate_target(profile, "VPN.Example.com", "8.8.8.8", "admin@example.com")

    def test_target_normalizes_domain_and_validates_semantics(self):
        self.assertEqual(self.target("vless")["domain"], "vpn.example.com")
        for address in ("192.168.1.1", "127.0.0.1", "169.254.169.254", "168.63.129.16", "224.1.1.1", "203.0.113.1", "::1", "8.8.8.999", "100.64.1.1"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                render.validate_target("vless", "vpn.example.com", address)
        for domain in ("localhost", "8.8.8.8", "a.example.com\n}", "https://vpn.example.com", "*.example.com", "-bad.example.com"):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                render.validate_target("hysteria2", domain, "8.8.8.8")
        with self.assertRaises(ValueError):
            render.validate_target("vless", "vpn.example.com", "8.8.8.8", "x@example.com\nadmin off")

    def test_credentials_reject_injection_and_unknown_fields_without_echo(self):
        self.assertEqual(render.validate_credentials("vless", VLESS), VLESS)
        self.assertEqual(render.validate_credentials("hysteria2", HY2), HY2)
        for profile, credentials in (("vless", {**VLESS, "ws_path": "/attack\n}"}), ("vless", {**VLESS, "uuid": "secret-invalid"}),
                                     ("hysteria2", {"password": "secret\ninvalid"}), ("hysteria2", {**HY2, "extra": "secret"}),
                                     ("hysteria2", {**HY2, "username": "user:other"})):
            with self.subTest(profile=profile), self.assertRaises(ValueError) as error:
                render.validate_credentials(profile, credentials)
            self.assertNotIn("secret", str(error.exception))

    def test_generated_credentials_are_valid_and_fresh(self):
        for profile in ("vless", "hysteria2"):
            a = render.new_credentials(profile)
            b = render.new_credentials(profile)
            self.assertNotEqual(a, b)
            self.assertEqual(render.validate_credentials(profile, a), a)

    def test_vless_loopback_strict_tls_and_private_blocks(self):
        config = render.xray_config(VLESS)
        inbound = config["inbounds"][0]
        self.assertEqual((inbound["listen"], inbound["port"]), ("127.0.0.1", 39761))
        self.assertEqual(inbound["streamSettings"]["wsSettings"]["path"], VLESS["ws_path"])
        self.assertEqual(config["routing"]["domainStrategy"], "IPOnDemand")
        self.assertIn("168.63.129.16/32", config["routing"]["rules"][0]["ip"])
        self.assertEqual(config["outbounds"][0]["settings"]["domainStrategy"], "UseIPv4")
        caddy = render.caddy_config(self.target("vless"), VLESS)
        self.assertIn("admin off", caddy)
        self.assertIn("protocols h1 h2", caddy)
        self.assertNotIn("h3", caddy)
        self.assertIn("127.0.0.1:39761", caddy)
        uri, client = render.client_config(self.target("vless"), VLESS)
        parsed = urlsplit(uri.strip())
        self.assertEqual(parsed.scheme, "vless")
        self.assertEqual(parse_qs(parsed.query)["path"], [VLESS["ws_path"]])
        self.assertFalse(json.loads(client)["outbounds"][0]["streamSettings"]["tlsSettings"]["allowInsecure"])

    def test_hy2_ipv4_acme_private_blocks_and_strict_client(self):
        config = render.hy2_config(self.target("hysteria2"), HY2)
        self.assertEqual(config["acme"]["type"], "tls")
        self.assertEqual(config["acme"]["tls"]["altPort"], 443)
        self.assertEqual(config["outbounds"][0]["direct"]["mode"], "4")
        self.assertNotIn("reject(::ffff:0:0/96)", config["acl"]["inline"])
        self.assertEqual(config["acl"]["inline"][-1], "direct(all)")
        uri, client = render.client_config(self.target("hysteria2"), {**HY2, "username": "android"})
        self.assertEqual(unquote(urlsplit(uri.strip()).username), "android:" + HY2["password"])
        self.assertFalse(json.loads(client)["tls"]["insecure"])
        self.assertEqual(json.loads(client)["socks5"]["listen"], "127.0.0.1:1080")

    def test_acl_denies_metadata_and_private_not_public_ipv4(self):
        networks = [ipaddress.ip_network(value) for value in render.DENIED_NETWORKS]
        for address in ("10.1.2.3", "127.0.0.1", "169.254.169.254", "168.63.129.16", "192.168.1.1", "fc00::1", "fe80::1"):
            self.assertTrue(any(ipaddress.ip_address(address) in network for network in networks))
        for address in ("8.8.8.8", "1.1.1.1"):
            self.assertFalse(any(ipaddress.ip_address(address) in network for network in networks))

    def test_units_unprivileged_no_shell_and_capabilities(self):
        for core in ("xray", "caddy", "hy2"):
            unit = render.unit(core)
            self.assertIn(f"User={core}\n", unit)
            self.assertIn("NoNewPrivileges=true", unit)
            self.assertIn("ProtectSystem=strict", unit)
            self.assertIn("StandardOutput=append:/var/lib/personal-vpn-installer/", unit)
            self.assertNotIn("User=root", unit)
            self.assertNotIn("CAP_NET_ADMIN", unit)
            if core == "xray":
                self.assertNotIn("CAP_NET_BIND_SERVICE", unit)
            else:
                self.assertIn("AmbientCapabilities=CAP_NET_BIND_SERVICE", unit)

    def test_neutral_protocols_render_consistent_configs(self):
        for protocol, alias, credentials, label in (("vless", "vless", VLESS, "VLESS"),
                                                    ("hysteria2", "hysteria2", HY2, "Hysteria2")):
            with self.subTest(protocol=protocol):
                self.assertEqual(render.storage_profile(protocol), alias)
                target = self.target(protocol)
                self.assertEqual(target["profile"], protocol)
                self.assertEqual(render.validate_credentials(protocol, credentials), credentials)
                self.assertEqual(render.validate_credentials(protocol, render.new_credentials(protocol)).keys(), credentials.keys())
                uri, config = render.client_config(target, credentials)
                legacy_uri, legacy_config = render.client_config(self.target(alias), credentials)
                self.assertEqual(urlsplit(uri.strip()).fragment, label)
                self.assertEqual(urlsplit(legacy_uri.strip()).fragment, label)
                self.assertEqual(uri.split("#")[0], legacy_uri.split("#")[0])
                self.assertEqual(config, legacy_config)
        with self.assertRaises(ValueError):
            render.validate_target("unsupported", "vpn.example.com", "8.8.8.8")

    def test_service_config_paths_remain_compatible(self):
        for core, config in (("xray", "/vless/xray/config.json"), ("caddy", "/vless/caddy/Caddyfile"),
                             ("hy2", "/hysteria2/config.json")):
            self.assertIn(render.CONFIG_ROOT + config, render.unit(core))

    def test_all_release_pins_official_and_fixed(self):
        for core, release in install.RELEASES.items():
            self.assertTrue(re.fullmatch(r"[a-f0-9]{64}", release["sha256"]), core)
            self.assertTrue(release["url"].startswith("https://github.com/"))
            self.assertIn(render.VERSIONS[core], release["url"])
            self.assertNotIn("/latest/", release["url"])


class OrchestrationTests(unittest.TestCase):
    def args(self, *extra):
        return install.parse_args(["--profile", "hysteria2", "--domain", "vpn.example.com", "--public-ip", "8.8.8.8", "--yes", *extra])

    def test_dry_run_never_installs_resolves_or_generates_secrets(self):
        for profile in render.PROFILES:
            with mock.patch.object(install.Installer, "install", side_effect=AssertionError("install called")), \
                 mock.patch.object(socket_module := install.socket, "getaddrinfo", side_effect=AssertionError("network called")), \
                 mock.patch.object(render, "new_credentials", side_effect=AssertionError("secrets generated")), \
                 mock.patch.object(install.os, "umask", side_effect=AssertionError("umask changed")), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                code = install.main(["--profile", profile, "--domain", "vpn.example.com", "--public-ip", "8.8.8.8", "--yes", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn("DRY RUN", output.getvalue())
            self.assertNotIn(HY2["password"], output.getvalue())

    def test_neutral_profiles_select_legacy_cores_and_paths(self):
        for protocol, alias, cores in (("vless", "vless", ["xray", "caddy"]), ("hysteria2", "hysteria2", ["hy2"])):
            args = install.parse_args(["--profile", protocol, "--domain", "vpn.example.com", "--public-ip", "8.8.8.8", "--yes"])
            installer = install.Installer(args)
            self.assertEqual(installer.profile, alias)
            self.assertEqual(installer.cores, cores)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                install.plan(args)
            self.assertIn(f"{render.CLIENT_ROOT}/{alias}/", output.getvalue())

    def test_platform_support_matrix_and_required_checks(self):
        cases = [
            ("ubuntu", "22.04", "x86_64", True, 0, (3, 10), "linux", None, None),
            ("ubuntu", "24.04", "x86_64", True, 0, (3, 12), "linux", None, None),
            ("ubuntu", "22.04", "amd64", True, 0, (3, 10), "linux", None, None),
            ("ubuntu", "20.04", "x86_64", True, 0, (3, 10), "linux", None, "Only fresh Ubuntu"),
            ("ubuntu", "24.10", "x86_64", True, 0, (3, 12), "linux", None, "Only fresh Ubuntu"),
            ("debian", "24.04", "x86_64", True, 0, (3, 12), "linux", None, "Only fresh Ubuntu"),
            ("ubuntu", "24.04", "aarch64", True, 0, (3, 12), "linux", None, "x86_64"),
            ("ubuntu", "22.04", "i686", True, 0, (3, 10), "linux", None, "x86_64"),
            ("ubuntu", "22.04", "x86_64", False, 0, (3, 10), "linux", None, "systemd"),
            ("ubuntu", "24.04", "x86_64", True, 1000, (3, 12), "linux", None, "requires root"),
            ("ubuntu", "22.04", "x86_64", True, 0, (3, 9), "linux", None, "Python 3.10"),
            ("ubuntu", "24.04", "x86_64", True, 0, (3, 12), "darwin", None, "requires root"),
        ]
        tools = ("apt-get", "systemctl", "systemd-analyze", "ss", "useradd", "runuser")
        cases += [("ubuntu", "22.04", "x86_64", True, 0, (3, 10), "linux", tool, tool) for tool in tools]
        for distro, version, machine, systemd, uid, python, host, missing, error in cases:
            with self.subTest(distro=distro, version=version, machine=machine, systemd=systemd,
                              uid=uid, python=python, host=host, missing=missing):
                installer = install.Installer(self.args())
                with mock.patch.object(install.sys, "platform", host), \
                     mock.patch.object(install.sys, "version_info", python), \
                     mock.patch.object(install.os, "geteuid", return_value=uid, create=True), \
                     mock.patch.object(install.platform, "machine", return_value=machine), \
                     mock.patch.object(Path, "read_text", return_value=f'ID="{distro}"\nVERSION_ID="{version}"\n'), \
                     mock.patch.object(Path, "is_dir", return_value=systemd), \
                     mock.patch.object(install.shutil, "which", side_effect=lambda name: None if name == missing else f"/usr/bin/{name}") as which, \
                     mock.patch.object(install, "ensure_no_symlinks") as symlinks:
                    if error:
                        with self.assertRaisesRegex(install.InstallError, error):
                            installer.inspect_platform()
                        symlinks.assert_not_called()
                    else:
                        installer.inspect_platform()
                        self.assertEqual([call.args[0] for call in which.call_args_list], list(tools))
                        self.assertEqual(symlinks.call_count, 6)

    def test_alias_retry_preserves_saved_target_and_state(self):
        for requested, saved in (("vless", "vless"), ("vless", "vless"), ("hysteria2", "hysteria2"), ("hysteria2", "hysteria2")):
            with self.subTest(requested=requested, saved=saved), tempfile.TemporaryDirectory() as temporary:
                state_dir = Path(temporary)
                args = install.parse_args(["--profile", requested, "--domain", "vpn.example.com", "--public-ip", "8.8.8.8", "--yes"])
                installer = install.Installer(args)
                saved_target = {**args.target, "profile": saved}
                state = {"owner": install.OWNER, "target": saved_target, "status": "installing",
                         "files": {}, "users": {}, "directories": {}}
                marker = state_dir / "state.json"
                marker.write_text(json.dumps(state))
                marker_info = mock.Mock(st_uid=0, st_mode=0o100600, st_size=marker.stat().st_size)
                directory_info = mock.Mock(st_uid=0, st_mode=0o40700)
                with mock.patch.object(install, "STATE", state_dir), mock.patch.object(install, "MARKER", marker), \
                     mock.patch.object(Path, "stat", autospec=True, side_effect=lambda path, **kwargs: marker_info if path == marker else directory_info), \
                     mock.patch.object(install, "ensure_no_symlinks"), \
                     mock.patch.object(installer, "verify_owned") as verify:
                    self.assertTrue(installer.existing_state())
                verify.assert_called_once()
                self.assertEqual(installer.target, saved_target)
                self.assertEqual(json.loads(marker.read_text()), state)

    def test_https_download_downgrade_refused_before_following(self):
        handler = install.HTTPSOnlyRedirect()
        with self.assertRaises(install.InstallError):
            handler.redirect_request(None, None, 302, "redirect", {}, "http://example.com/core")

    def test_dry_run_rejects_invalid_public_target_without_installing(self):
        with mock.patch.object(install.Installer, "install", side_effect=AssertionError("install called")), \
             contextlib.redirect_stderr(io.StringIO()) as output:
            result = install.main(["--profile", "hysteria2", "--domain", "vpn.example.com", "--public-ip", "127.0.0.1", "--yes", "--dry-run"])
        self.assertEqual(result, 1)
        self.assertIn("public unicast IPv4", output.getvalue())

    def test_migration_bad_json_error_does_not_echo_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            path.write_text('SECRET-INVALID-JSON')
            path.chmod(0o600)
            with self.assertRaises(install.InstallError) as error:
                install.private_source(path, False)
            self.assertNotIn("SECRET", str(error.exception))

    def test_yes_needs_complete_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            install.parse_args(["--yes", "--dry-run", "--profile", "hysteria2"])
        self.assertEqual(result.exception.code, 2)

    def test_migration_file_validation_no_content_printing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            path.write_text(json.dumps(HY2))
            path.chmod(0o600)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = install.main(["--profile", "hysteria2", "--domain", "vpn.example.com", "--public-ip", "8.8.8.8", "--credentials-file", str(path), "--dry-run", "--yes"])
            self.assertEqual(result, 0)
            self.assertNotIn(HY2["password"], output.getvalue())

    def test_existing_credentials_reused_not_rotated(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(install, "STATE", Path(temporary)):
            path = Path(temporary) / "credentials.json"
            path.write_text(json.dumps(HY2))
            installer = install.Installer(self.args())
            installer.state = {"files": {str(path): {}}}
            with mock.patch.object(render, "new_credentials", side_effect=AssertionError("rotated")), \
                 mock.patch.object(installer, "put_file", side_effect=AssertionError("rewritten")):
                self.assertEqual(installer.credentials(), HY2)

    def test_different_migration_credentials_refused(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(install, "STATE", Path(temporary)):
            path = Path(temporary) / "credentials.json"
            path.write_text(json.dumps(HY2))
            migration = Path(temporary) / "migration.json"
            migration.write_text(json.dumps({"password": "different-example-password"}))
            migration.chmod(0o600)
            installer = install.Installer(self.args("--credentials-file", str(migration)))
            installer.state = {"files": {str(path): {}}}
            with self.assertRaises(install.InstallError):
                installer.credentials()

    def test_completed_run_no_install_restart_or_network(self):
        installer = install.Installer(self.args())
        installer.state = {"status": "complete"}
        with mock.patch.object(installer, "inspect_platform"), mock.patch.object(installer, "existing_state"), \
             mock.patch.object(installer, "credentials"), mock.patch.object(installer, "summary") as summary, \
             mock.patch.object(installer, "check_dns", side_effect=AssertionError("DNS called")), \
             mock.patch.object(installer, "start", side_effect=AssertionError("restarted")), \
             mock.patch.object(installer, "run", side_effect=AssertionError("system write")):
            installer.install()
        summary.assert_called_once_with(existing=True)

    def test_dns_wrong_A_or_any_AAAA_rejected(self):
        installer = install.Installer(self.args())
        row = lambda value: (None, None, None, None, (value, 443))
        with mock.patch.object(install.socket, "getaddrinfo", return_value=[row("1.1.1.1")]), self.assertRaises(install.InstallError):
            installer.check_dns()
        with mock.patch.object(install.socket, "getaddrinfo", side_effect=[[row("8.8.8.8")], [row("2001:4860:4860::8888")]]), self.assertRaises(install.InstallError):
            installer.check_dns()

    def test_occupied_foreign_port_rejected(self):
        installer = install.Installer(self.args())
        output = subprocess.CompletedProcess([], 0, 'LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("other",pid=99,fd=1))\n')
        with mock.patch.object(installer, "run", return_value=output), self.assertRaises(install.InstallError):
            installer.check_ports()

    def test_active_firewall_unchanged_without_explicit_flag(self):
        installer = install.Installer(self.args())
        with mock.patch.object(install.shutil, "which", return_value="/usr/sbin/ufw"), \
             mock.patch.object(installer, "run", return_value=subprocess.CompletedProcess([], 0, "Status: active\n")) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            installer.configure_firewall()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["ufw", "status"])

    def test_explicit_firewall_adds_only_profile_ports(self):
        for active in (True, False):
            installer = install.Installer(self.args("--configure-firewall"))
            with mock.patch.object(install.shutil, "which", return_value="/usr/sbin/ufw"), \
                 mock.patch.object(installer, "run", return_value=subprocess.CompletedProcess([], 0, f"Status: {'active' if active else 'inactive'}\n")) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                installer.configure_firewall()
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(len(commands), 3 if active else 1)
            self.assertFalse(any("enable" in command or "reset" in command or "22" in command for command in commands))
            if active:
                self.assertEqual(commands[1][3], "tcp")
                self.assertEqual(commands[2][3], "udp")

    @unittest.skipUnless(os.name == "posix", "Linux ownership semantics")
    def test_directory_mode_not_reduced_by_private_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            installer = install.Installer(self.args())
            installer.state = {"directories": {}}
            old = os.umask(0o077)
            try:
                with mock.patch.object(installer, "write_state"), mock.patch.object(install.os, "chown"):
                    path = Path(temporary) / "managed"
                    installer.make_directory(path, 0o755)
                self.assertEqual(path.stat().st_mode & 0o777, 0o755)
            finally:
                os.umask(old)


if __name__ == "__main__":
    unittest.main()
