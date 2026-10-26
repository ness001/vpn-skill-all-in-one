"""Offline diagnostics tests; no Azure, guest commands or real credentials."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("diagnose_vpn", TOOLS / "diagnose_vpn.py")
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
CONFIG = {"subscription": "00000000-0000-0000-0000-000000000001", "resourceGroup": "test-group", "vm": "test-vm",
          "guestPython": "/usr/bin/python3", "cpuCredits": True,
          "services": [{"unit": unit, "port": port, "transport": transport} for unit, port, transport in
                       (("proxy.service", 18080, "tcp"), ("quic.service", 18443, "udp"), ("web.service", 443, "tcp"))],
          "logDirectories": {"vless": "/var/log/test/vless", "hy2": "/var/log/test/hy2"}, "historicalLog": None}
SOURCE = diag.render_guest(CONFIG, 30).split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
guest = types.ModuleType("guest_diagnostics")
exec(compile(SOURCE, "guest_diagnostics.sh", "exec"), guest.__dict__)


def parse_guest(response):
    return diag.parse_guest(response, CONFIG)


def parse_args(argv):
    with patch.object(diag, "load_config", return_value=CONFIG):
        return diag.parse_args(["--mode", "azure", "--config", "/private/test.json"] + argv)


def main(argv):
    with patch.object(diag, "load_config", return_value=CONFIG):
        return diag.main(["--mode", "azure", "--config", "/private/test.json"] + argv)


def guest_summary():
    log = {"files": 1, "eligibleFiles": 1, "agedOutSkipped": 0, "bytesOnDisk": 64,
           "sampledBytes": 64, "oldestBucketUtc": "2026-09-23T00:00:00Z",
           "newestWriteUtc": "2026-09-23T00:29:59Z", "privateModes": True,
           "scanComplete": True, "windowStartCovered": True, "unparsed": 0,
           "severity": {"info": 1}, "warningCauses": {}, "resetOperations": {},
           "resetPublicDestinations": 0, "resetPublicCountCapped": False,
           "rejected": [], "rejectedOmitted": 0}
    return {"schema": 1, "status": "observations_only", "utc": "2026-09-23T00:30:00Z",
            "requestedSinceUtc": "2026-09-23T00:00:00Z", "bucketSeconds": 10,
            "logs": {"vless": dict(log), "hy2": dict(log)},
            "services": [{"unit": unit, "active": True, "mainPid": 111, "children": [222],
                          "port": port, "transport": transport, "listener": True, "owned": True}
                         for unit, port, transport in ((row["unit"], row["port"], row["transport"]) for row in CONFIG["services"])],
            "resources": {"memory": {"MemTotalKiB": 2048000, "MemFreeKiB": 1024000},
                          "logDiskFreeMiB": 5000, "udpCountersSinceBootNotWindow": {}},
            "historicalLog": {"present": False, "scanned": False}}


def guest_response(data):
    return {"value": [{"code": "ProvisioningState/succeeded", "message": diag.MARKER + json.dumps(data, separators=(",", ":"))}]}


class ConfigTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "target.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return diag.load_config(path)

    def test_explicit_target_required(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            diag.parse_args(["--dry-run"])
        with self.assertRaises(diag.DiagnosticError):
            diag.load_config(Path("/missing/target.json"))
        for key in ("subscription", "resourceGroup", "vm", "services"):
            data = dict(CONFIG)
            del data[key]
            with self.subTest(key=key), self.assertRaises(diag.DiagnosticError):
                self.load(data)

    def test_rejects_invalid_and_injected_config(self):
        cases = [("subscription", "not-a-subscription"), ("vm", "--help"), ("resourceGroup", "group; id"),
                 ("guestPython", "/usr/bin/python3;id"), ("guestPython", "/usr/bin/../python"),
                 ("historicalLog", "/var/log/log\nPY\nid"), ("services", []), ("cpuCredits", "true"),
                 ("logDirectories", {"hy2": "/tmp/$(id)"}), ("logDirectories", {"unknown": "/var/log/unknown"}),
                 ("services", [{"unit": "--help", "port": 443, "transport": "tcp"}]),
                 ("services", [{"unit": "proxy.service", "port": True, "transport": "tcp"}]),
                 ("services", [{"unit": "proxy.service", "port": 443, "transport": "quic"}])]
        for key, value in cases:
            with self.subTest(key=key, value=value), self.assertRaises(diag.DiagnosticError):
                self.load(dict(CONFIG, **{key: value}))

    def test_guest_configuration_roundtrips_without_code_interpolation(self):
        loaded = self.load(CONFIG)
        source = diag.render_guest(loaded, 7)
        self.assertNotIn("__GUEST_", source)
        self.assertNotIn(CONFIG["services"][0]["unit"], source)
        module = types.ModuleType("configured_guest")
        python = source.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        exec(compile(python, "guest", "exec"), module.__dict__)
        self.assertEqual(module.SERVICES, CONFIG["services"])
        self.assertEqual(module.LOG_DIRECTORIES, CONFIG["logDirectories"])
        self.assertEqual(module.MINUTES, 7)

    def test_generic_deployment_reports_unconfigured_logs(self):
        config = {key: value for key, value in CONFIG.items() if key not in ("logDirectories", "historicalLog", "guestPython", "cpuCredits")}
        config = self.load(config)
        self.assertEqual(config["guestPython"], "/usr/bin/python3")
        self.assertFalse(config["cpuCredits"])
        source = diag.render_guest(config, 1).split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        module = types.ModuleType("generic_guest")
        exec(compile(source, "guest", "exec"), module.__dict__)
        fixture = guest_summary()
        with patch.object(module, "services", return_value=fixture["services"]), patch.object(module, "resources", return_value=fixture["resources"]):
            data = module.collect()
        self.assertEqual(data["status"], "incomplete")
        self.assertTrue(all(row == {"error": "log_support_not_configured"} for row in data["logs"].values()))
        self.assertEqual(diag.parse_guest(guest_response(data), config), data)
        with patch.object(diag, "azure", return_value={"value": [{"name": {"value": "Percentage CPU"}, "timeseries": [{"data": [{"timeStamp": "2026-09-23T00:00:00Z", "average": 1}]}]}]}) as azure:
            result = diag.metrics("az", 1, config)
        self.assertEqual(result["status"], "available")
        self.assertFalse(result["creditsRequested"])
        self.assertNotIn("CPU Credits Remaining", azure.call_args.args[1])


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.config = {key: value for key, value in CONFIG.items()
                       if key not in ("subscription", "resourceGroup", "vm", "cpuCredits")}

    def test_local_config_needs_no_azure_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.json"
            path.write_text(json.dumps(self.config), encoding="utf-8")
            loaded = diag.load_config(path, "local")
            self.assertEqual(loaded["services"], self.config["services"])
            self.assertNotIn("subscription", loaded)
            with self.assertRaises(diag.DiagnosticError):
                diag.load_config(path, "azure")
            path.write_text(json.dumps(dict(self.config, vm="accidental-remote")), encoding="utf-8")
            with self.assertRaises(diag.DiagnosticError):
                diag.load_config(path, "local")

    def invoke(self, *options):
        with patch.object(diag, "load_config", return_value=self.config), redirect_stdout(io.StringIO()) as out:
            code = diag.main(["--mode", "local", "--config", "/private/local.json", *options])
        return code, json.loads(out.getvalue())

    def test_local_dry_run_never_collects_or_looks_up_azure(self):
        with patch.object(diag, "local_guest", side_effect=AssertionError), patch.object(diag.shutil, "which", side_effect=AssertionError), patch.object(diag.subprocess, "run", side_effect=AssertionError):
            code, result = self.invoke("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(result["guestRunCommands"], 0)
        self.assertEqual(result["localCollectors"], 1)
        self.assertEqual(result["monitorQueries"], 0)
        self.assertEqual(result["target"], {"scope": "this_server"})

    def test_local_uses_same_template_and_validates_private_output(self):
        data = guest_summary()
        response = subprocess.CompletedProcess([], 0, "private-noise\n" + diag.MARKER + json.dumps(data), "private-error")
        with patch.object(diag.subprocess, "run", return_value=response) as command:
            self.assertEqual(diag.local_guest(7, self.config), data)
        self.assertEqual(command.call_args.args[0], ["/bin/sh"])
        self.assertIn("MINUTES = 7", command.call_args.kwargs["input"])
        self.assertNotIn(self.config["services"][0]["unit"], command.call_args.kwargs["input"])
        data["rawLog"] = "private-host.example"
        response.stdout = diag.MARKER + json.dumps(data)
        with patch.object(diag.subprocess, "run", return_value=response), self.assertRaises(diag.DiagnosticError):
            diag.local_guest(7, self.config)

    def test_local_metrics_unavailable_not_azure_dependency_failure(self):
        with patch.object(diag, "local_guest", return_value=guest_summary()), patch.object(diag.shutil, "which", side_effect=AssertionError), patch.object(diag, "azure", side_effect=AssertionError):
            code, result = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "observations_only")
        self.assertEqual(result["metrics"]["status"], "unavailable")
        self.assertIsNone(result["metrics"]["cpu"])

    def test_permission_failures_are_incomplete_and_sanitized(self):
        response = subprocess.CompletedProcess([], 1, "private-host", "permission denied private-key")
        with patch.object(diag.subprocess, "run", return_value=response):
            code, result = self.invoke()
        self.assertEqual(code, 2)
        self.assertNotIn("private", json.dumps(result))
        self.assertIn("read_permissions", result["error"])


class CliTests(unittest.TestCase):
    def test_default_window_and_range(self):
        self.assertEqual(parse_args([]).minutes, 30)
        for value in ("0", "31", "1;whoami", "-1"):
            with self.subTest(value=value), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                parse_args(["--minutes", value])

    def test_dry_run_has_no_effects(self):
        with patch.object(diag, "azure", side_effect=AssertionError("no Azure")), patch.object(diag, "guest", side_effect=AssertionError("no guest")), patch.object(diag.shutil, "which", side_effect=AssertionError("no CLI lookup")), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--dry-run", "--minutes", "2"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["guestRunCommands"], 1)
        self.assertEqual(data["monitorQueries"], 1)
        self.assertNotIn("hysteria2", output.getvalue().lower())

    def test_output_rejects_outside_and_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(diag, "runtime_root", return_value=Path(directory)):
            allowed = Path(directory) / ".local" / "diagnostics"
            allowed.mkdir(parents=True)
            existing = allowed / "existing.json"
            existing.write_text("keep", encoding="utf-8")
            for value in (Path("outside.json"), Path(".local/diagnostics/../other.json"), existing):
                with self.assertRaises(ValueError):
                    diag.output_path(value)
            self.assertEqual(diag.output_path(Path(".local/diagnostics/new.json")), allowed / "new.json")
            self.assertEqual(existing.read_text(), "keep")

    def test_guest_uses_one_fixed_command_and_temporary_file(self):
        captured = []
        def fake_azure(az, arguments, config, timeout):
            captured.append(arguments)
            path = Path(arguments[-1][1:])
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("MINUTES = 7", text)
            self.assertNotIn("__WINDOW_MINUTES__", text)
            self.assertNotIn("\r", text)
            self.assertNotIn(str(diag.ROOT), str(path))
            return guest_response(guest_summary())
        with patch.object(diag, "azure", side_effect=fake_azure):
            diag.guest("az", 7, CONFIG)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][:3], ["vm", "run-command", "invoke"])
        self.assertIn(CONFIG["resourceGroup"], captured[0])
        self.assertIn(CONFIG["vm"], captured[0])
        self.assertNotIn("--parameters", captured[0])
        self.assertFalse(Path(captured[0][-1][1:]).exists())

    def test_azure_explicit_subscription_and_no_shell(self):
        fake = subprocess.CompletedProcess([], 0, '{"value":[]}', "")
        with patch.object(diag.subprocess, "run", return_value=fake) as command:
            diag.azure("az.cmd", ["monitor", "metrics", "list"], CONFIG)
        args, kwargs = command.call_args
        self.assertIn(CONFIG["subscription"], args[0])
        self.assertFalse(kwargs.get("shell", False))

    def test_azure_errors_never_include_raw_output(self):
        fake = subprocess.CompletedProcess([], 1, "private-uuid", "private-host.example/password")
        with patch.object(diag.subprocess, "run", return_value=fake), self.assertRaises(diag.DiagnosticError) as error:
            diag.azure("az", [], CONFIG)
        self.assertNotIn("private", str(error.exception))

    def test_guest_failure_marker_even_with_successful_azure(self):
        for message in ('VPN_DIAGNOSTICS={"schema":1,"status":"error","error":"private"}',
                        'VPN_DIAGNOSTICS={"schema":1}', 'VPN_DIAGNOSTICS={', "unrelated successful output"):
            with self.subTest(message=message), self.assertRaises(diag.DiagnosticError):
                parse_guest({"value": [{"message": message, "code": "ProvisioningState/succeeded"}]})
        with self.assertRaises(diag.DiagnosticError):
            parse_guest({"value": [{"code": "ProvisioningState/failed", "message": ""}]})

    def test_guest_accepts_complete_summary_and_fixed_failures(self):
        data = guest_summary()
        self.assertEqual(parse_guest(guest_response(data)), data)
        data["status"] = "incomplete"
        data["logs"]["hy2"] = {"error": "logs_unavailable_or_unsafe"}
        data["services"] = {"error": "read_failed"}
        data["resources"] = {"error": "read_failed"}
        self.assertEqual(parse_guest(guest_response(data)), data)

    def test_guest_rejects_missing_sections_and_fields(self):
        for path in (("logs",), ("services",), ("resources",), ("historicalLog",),
                     ("logs", "hy2"), ("logs", "vless", "sampledBytes"),
                     ("logs", "vless", "warningCauses"), ("services", 0, "owned"),
                     ("resources", "memory", "MemTotalKiB")):
            data = guest_summary()
            target = data
            for key in path[:-1]:
                target = target[key]
            del target[path[-1]]
            with self.subTest(path=path), self.assertRaises(diag.DiagnosticError):
                parse_guest(guest_response(data))

    def test_guest_rejects_unexpected_fields_at_every_depth(self):
        for path in ((), ("logs",), ("logs", "hy2"), ("logs", "hy2", "severity"),
                     ("logs", "hy2", "warningCauses"), ("logs", "hy2", "resetOperations"),
                     ("services", 0), ("resources",), ("resources", "memory"),
                     ("resources", "udpCountersSinceBootNotWindow"), ("historicalLog",)):
            data = guest_summary()
            target = data
            for key in path:
                target = target[key]
            target["private-host.example"] = "private-auth-value"
            with self.subTest(path=path):
                with self.assertRaises(diag.DiagnosticError) as error:
                    parse_guest(guest_response(data))
                self.assertNotIn("private", str(error.exception))

    def test_guest_rejects_invalid_types_and_uncontrolled_strings(self):
        cases = [(('schema',), True), (('utc',), 'private-host.example'),
                 (('utc',), '2026-99-23T00:30:00Z'), (('bucketSeconds',), True),
                 (('logs', 'hy2', 'files'), -1), (('logs', 'hy2', 'sampledBytes'), 1.5),
                 (('logs', 'hy2', 'severity', 'info'), True),
                 (('logs', 'hy2', 'privateModes'), 'private-auth-value'),
                 (('logs', 'hy2', 'resetPublicCountCapped'), 0),
                 (('logs', 'hy2', 'rejected'), [{'class': 'private-host.example', 'port': 443, 'count': 1}]),
                 (('logs', 'hy2', 'rejected'), [{'class': 'loopback', 'port': 70000, 'count': 1}]),
                 (('services', 0, 'unit'), 'private-host.example'),
                 (('services', 0, 'children'), ['private-auth-value']),
                 (('services', 0, 'port'), 8080), (('services', 0, 'transport'), 'udp'),
                 (('resources', 'logDiskFreeMiB'), float('nan')),
                 (('historicalLog', 'scanned'), True)]
        for path, value in cases:
            data = guest_summary()
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path, value=value), self.assertRaises(diag.DiagnosticError):
                parse_guest(guest_response(data))

    def test_guest_accepts_explicitly_truncated_summary_only_as_incomplete(self):
        data = guest_summary()
        data.update(status="incomplete", summaryTruncated=True)
        for summary in data["logs"].values():
            for key in ("warningCauses", "rejected", "severity"):
                del summary[key]
        self.assertEqual(parse_guest(guest_response(data)), data)
        data["status"] = "observations_only"
        with self.assertRaises(diag.DiagnosticError):
            parse_guest(guest_response(data))

    def test_guest_rejects_malformed_envelopes(self):
        for response in (None, [], {}, {"value": None}, {"value": {}}, {"value": [None]},
                         {"value": [{"message": []}]}):
            with self.subTest(response=response), self.assertRaises(diag.DiagnosticError):
                parse_guest(response)

    def test_guest_requires_all_fixed_services(self):
        for change in (lambda rows: rows.pop(), lambda rows: rows.__setitem__(1, rows[0])):
            data = guest_summary()
            change(data["services"])
            with self.assertRaises(diag.DiagnosticError):
                parse_guest(guest_response(data))

    def test_guest_rejects_false_complete_status(self):
        for path in (("logs", "hy2", "scanComplete"), ("logs", "vless", "privateModes"),
                     ("services", 0, "active"), ("services", 0, "listener"), ("services", 0, "owned")):
            data = guest_summary()
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = False
            with self.subTest(path=path), self.assertRaises(diag.DiagnosticError):
                parse_guest(guest_response(data))
            data["status"] = "incomplete"
            self.assertEqual(parse_guest(guest_response(data)), data)

    def test_rejected_guest_data_never_reaches_stdout_or_saved_output(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(diag, "runtime_root", return_value=Path(directory)):
            data = guest_summary()
            data["rawLog"] = "private-host.example private-auth-value"
            with patch.object(diag.shutil, "which", return_value="az"), patch.object(diag, "azure", return_value=guest_response(data)), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--logs-only", "--output", ".local/diagnostics/test.json"]), 2)
            saved = (Path(directory) / ".local/diagnostics/test.json").read_text(encoding="utf-8")
            for text in (output.getvalue(), saved):
                self.assertNotIn("private-host", text)
                self.assertNotIn("private-auth", text)
                self.assertNotIn("guest", json.loads(text))
                self.assertEqual(json.loads(text)["status"], "incomplete")

    def test_incomplete_guest_is_not_healthy(self):
        with patch.object(diag.shutil, "which", return_value="az"), patch.object(diag, "guest", return_value={"schema": 1, "status": "incomplete"}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--logs-only"]), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "incomplete")

    def test_guest_failure_preserves_independent_metrics(self):
        for failure in (diag.DiagnosticError("guest_summary_invalid_schema"), RuntimeError("private-auth-value")):
            with self.subTest(failure=type(failure).__name__), patch.object(diag.shutil, "which", return_value="az"), patch.object(diag, "guest", side_effect=failure), patch.object(diag, "metrics", return_value={"status": "available"}) as metrics, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([]), 2)
            metrics.assert_called_once_with("az", 30, CONFIG)
            result = json.loads(output.getvalue())
            self.assertEqual(result["metrics"]["status"], "available")
            self.assertNotIn("guest", result)
            self.assertNotIn("private-auth-value", output.getvalue())

    def test_metrics_failure_preserves_guest_summary(self):
        data = guest_summary()
        with patch.object(diag.shutil, "which", return_value="az"), patch.object(diag, "guest", return_value=data), patch.object(diag, "metrics", side_effect=diag.DiagnosticError("azure_cli_unavailable_or_timeout")), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["guest"], data)
        self.assertNotIn("metrics", result)

    def test_logs_only_failure_still_skips_metrics(self):
        with patch.object(diag.shutil, "which", return_value="az"), patch.object(diag, "guest", side_effect=diag.DiagnosticError("guest_command_failed")), patch.object(diag, "metrics") as metrics, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--logs-only"]), 2)
        metrics.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["metrics"]["status"], "skipped")

    def test_metrics_use_only_nonnull_bins(self):
        rows = [{"timeStamp": "2026-09-23T00:00:00Z", "average": 3},
                {"timeStamp": "2026-09-23T00:05:00Z", "average": None},
                {"timeStamp": "2026-09-23T00:10:00Z", "average": 9}]
        response = {"value": [{"name": {"value": name}, "timeseries": [{"data": rows}]} for name in ("Percentage CPU", "CPU Credits Remaining")]}
        with patch.object(diag, "azure", return_value=response):
            result = diag.metrics("az", 30, CONFIG)
        self.assertEqual(result["cpu"]["bins"], 2)
        self.assertEqual(result["cpu"]["meanBinAverage"], 6)
        self.assertEqual(result["cpu"]["peakBinAverage"], 9)
        self.assertEqual(result["creditsRemaining"]["latestBinAverage"], 9)


class GuestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.directory = Path(self.root) / "hy2"
        self.directory.mkdir()
        self.now = 18000

    def log(self, content, bucket=17990, counter=1):
        path = self.directory / ("%d-%d.log" % (bucket, counter))
        path.write_bytes(content)
        return path

    def summarize(self):
        return guest.summarize("hy2", self.now, self.root)

    def test_info_eof_not_warning_and_sensitive_content_absent(self):
        records = [dict(level="info", msg="EOF", reqAddr="secret.example:443", id="sensitive-uuid"),
                   dict(level="warn", msg="TCP error", error="read tcp 192.0.2.1:1->8.8.8.8:443: connection reset by peer", reqAddr="8.8.8.8:443"),
                   dict(level="warn", msg="TCP error", error="rejected", reqAddr="127.0.0.1:8080")]
        self.log(b"\n".join(json.dumps(row).encode() for row in records) + b"\n")
        result = self.summarize()
        self.assertEqual(result["severity"], {"info": 1, "warn": 2})
        self.assertEqual(result["warningCauses"], {"reset": 1, "rejected": 1})
        self.assertEqual(result["resetOperations"], {"read": 1})
        self.assertEqual(result["resetPublicDestinations"], 1)
        self.assertEqual(result["rejected"], [{"class": "loopback", "port": 8080, "count": 1}])
        encoded = json.dumps(result)
        for private in ("secret.example", "sensitive-uuid", "8.8.8.8", "127.0.0.1", "connection reset by peer"):
            self.assertNotIn(private, encoded)

    def test_mapped_loopback_and_ipv6_classification(self):
        for value, expected in [("[::ffff:127.0.0.1]:443", "loopback"), ("[::1]:443", "loopback"),
                                ("[fe80::1]:443", "link_local"), ("[2001:db8::1]:443", "reserved"),
                                ("168.63.129.16:80", "azure_platform"), ("domain.example:443", "hostname"),
                                ("192.168.1.2:80", "private")]:
            with self.subTest(value=value):
                self.assertEqual(guest.destination(value)[0], expected)
                self.assertIsNone(guest.destination(value)[2])

    def test_reset_operations_and_destination_deduplication(self):
        records = [dict(level="error", msg="TCP error", error=op + " connection reset by peer", reqAddr="8.8.8.8:443") for op in ("read", "write", "dial")]
        self.log(b"\n".join(json.dumps(row).encode() for row in records) + b"\n")
        result = self.summarize()
        self.assertEqual(result["resetOperations"], {"read": 1, "write": 1, "dial": 1})
        self.assertEqual(result["resetPublicDestinations"], 1)

    def test_hostname_reset_counts_public_remote_without_outputting_it(self):
        self.log((json.dumps(dict(level="warn", error="write tcp 192.0.2.4:555->8.8.8.8:443: connection reset by peer", reqAddr="private.example:443")) + "\n").encode())
        result = self.summarize()
        self.assertEqual(result["resetPublicDestinations"], 1)
        self.assertNotIn("private.example", json.dumps(result))
        self.assertNotIn("8.8.8.8", json.dumps(result))

    def test_full_thirty_minute_window_not_cut_at_63_files(self):
        self.log(b'{"level":"warn","error":"rejected"}\n', bucket=1000)
        for number in range(180):
            self.log(b'{"level":"info","msg":"ok"}\n', bucket=16200 + number * 10, counter=number + 1)
        result = self.summarize()
        self.assertEqual(guest.MAX_FILES, 2048)
        self.assertEqual(result["files"], 180)
        self.assertEqual(result["eligibleFiles"], 180)
        self.assertEqual(result["agedOutSkipped"], 1)
        self.assertTrue(result["windowStartCovered"])
        self.assertEqual(result["severity"], {"info": 180})
        self.assertEqual(result["warningCauses"], {})

    def test_concurrent_eviction_preserves_remaining_counts_as_incomplete(self):
        missing = self.log(b'{"level":"warn","error":"rejected"}\n', counter=1)
        self.log(b'{"level":"info","msg":"ok"}\n', counter=2)
        original = guest.os.lstat
        def lstat(path):
            if Path(path) == missing:
                raise FileNotFoundError("private-file-detail")
            return original(path)
        with patch.object(guest.os, "lstat", side_effect=lstat):
            result = self.summarize()
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["severity"], {"info": 1})
        self.assertFalse(result["scanComplete"])
        self.assertNotIn("private-file-detail", json.dumps(result))

    def test_vless_leading_fragment_marks_scan_incomplete(self):
        self.directory = Path(self.root) / "vless"
        self.directory.mkdir()
        self.log(b'connection reset by peer private.example\n[Warning] read tcp connection reset by peer\n')
        result = guest.summarize("vless", self.now, self.root)
        self.assertEqual(result["unparsed"], 1)
        self.assertEqual(result["severity"], {"warning": 1})
        self.assertEqual(result["warningCauses"], {"reset": 1})
        self.assertFalse(result["scanComplete"])
        self.assertNotIn("private.example", json.dumps(result))

    def test_vless_valid_split_record_keeps_warning_count(self):
        self.directory = Path(self.root) / "vless"
        self.directory.mkdir()
        self.log(b'[Warn', counter=1)
        self.log(b'ing] read tcp connection reset by peer\n', counter=2)
        result = guest.summarize("vless", self.now, self.root)
        self.assertEqual(result["unparsed"], 0)
        self.assertEqual(result["warningCauses"], {"reset": 1})

    def test_file_budget_overflow_is_explicit(self):
        for number in range(12):
            self.log(b'{"level":"info","msg":"ok"}\n', counter=number + 1)
        with patch.object(guest, "MAX_FILES", 10):
            result = self.summarize()
        self.assertEqual(result["files"], 10)
        self.assertEqual(result["eligibleFiles"], 12)
        self.assertFalse(result["scanComplete"])

    def test_byte_budget_and_oversized_line(self):
        self.log(b"x" * (guest.MAX_LINE * 3) + b'\n{"level":"info","msg":"ok"}\n')
        result = self.summarize()
        self.assertGreater(result["unparsed"], 0)
        self.assertEqual(result["severity"], {"info": 1})
        with patch.object(guest, "MAX_BYTES", 15):
            result = self.summarize()
        self.assertEqual(result["sampledBytes"], 15)
        self.assertFalse(result["scanComplete"])

    def test_fragment_crosses_segment_boundary(self):
        self.log(b'{"level":"warn","error":"connection ', counter=1)
        self.log(b'reset","reqAddr":"8.8.8.8:443"}\n', counter=2)
        result = self.summarize()
        self.assertEqual(result["warningCauses"], {"reset": 1})
        self.assertEqual(result["unparsed"], 0)

    def test_empty_or_malformed_logs_incomplete(self):
        self.assertFalse(self.summarize()["scanComplete"])
        self.log(b'{"level":[],"error":{}}\nnot-json\n')
        self.assertGreater(self.summarize()["unparsed"], 0)
        self.assertFalse(self.summarize()["scanComplete"])

    def test_safe_service_properties_and_child_ownership(self):
        commands = []
        def fake_run(args):
            commands.append(args)
            if args[0] == "systemctl":
                return "MainPID=111\nActiveState=active\n"
            return 'LISTEN 0 10 127.0.0.1:443 *:* users:(("core",pid=222,fd=3))\n'
        with patch.object(guest, "run", side_effect=fake_run), patch("builtins.open", side_effect=lambda *args: io.StringIO("222")):
            result = guest.services()
        self.assertTrue(all(row["owned"] for row in result))
        self.assertEqual([row["port"] for row in result], [18080, 18443, 443])
        self.assertTrue(all("status" not in command and "ExecStart" not in command for command in commands))

    def test_emit_bounded_and_truncation_explicit(self):
        result = {"schema": 1, "status": "observations_only", "logs": {"hy2": {"warningCauses": {"other": "x" * 4000}}}}
        with redirect_stdout(io.StringIO()) as output:
            guest.emit(result)
        summary = output.getvalue().strip().removeprefix(diag.MARKER)
        self.assertLessEqual(len(summary.encode()), 3000)
        self.assertEqual(json.loads(summary)["status"], "incomplete")
        self.assertTrue(json.loads(summary)["summaryTruncated"])

    def test_real_guest_summary_roundtrips_through_host_validation(self):
        self.log(b'{"level":"info","msg":"ok"}\n')
        fixture = guest_summary()
        summary = self.summarize()
        with patch.object(guest, "summarize", return_value=summary), patch.object(guest, "services", return_value=fixture["services"]), patch.object(guest, "resources", return_value=fixture["resources"]), patch.object(guest.os, "lstat", side_effect=OSError):
            data = guest.collect()
        with redirect_stdout(io.StringIO()) as output:
            guest.emit(data)
        self.assertEqual(parse_guest({"value": [{"message": output.getvalue()}]}), data)
        data["historicalLog"] = {"bytes": 64, "mtimeUtc": data["utc"], "privateRegularFile": True, "scanned": False}
        self.assertEqual(parse_guest(guest_response(data)), data)
        # Exercise the guest's actual pruning path without inventing another schema.
        for log in data["logs"].values():
            log["severity"] = {"info": 10 ** 800}
        with redirect_stdout(io.StringIO()) as output:
            guest.emit(data)
        result = parse_guest({"value": [{"message": output.getvalue()}]})
        self.assertTrue(result["summaryTruncated"])
        self.assertEqual(result["status"], "incomplete")

    def test_source_contains_no_service_mutations(self):
        for forbidden in ("systemctl restart", "systemctl stop", "systemctl start", "chmod(", "os.unlink(", "os.remove(", "journalctl", "/cmdline"):
            self.assertNotIn(forbidden, SOURCE)


if __name__ == "__main__":
    unittest.main()
