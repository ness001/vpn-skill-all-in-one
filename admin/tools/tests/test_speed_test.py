"""Offline speed-test regression tests; no real profiles, clients or network."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import speed_test as speed


class SpeedTests(unittest.TestCase):
    def setUp(self):
        self.names = self.enterContext(patch.object(speed, "profile_names", return_value=("vless", "secondary-hy2")))
        self.network = self.enterContext(patch.object(speed.subprocess, "run", side_effect=AssertionError("No unmocked subprocesses")))
        self.profiles = self.enterContext(patch.object(speed, "load_profile", side_effect=AssertionError("No real profile reads")))
        self.cores = self.enterContext(patch.object(speed, "resolve_core", side_effect=AssertionError("No real core reads")))
        self.ports = self.enterContext(patch.object(speed, "free_ports", return_value=(31001, 31002)))
        self.client = self.enterContext(patch.object(speed, "running_core", side_effect=AssertionError("No real clients")))

    def response(self, code=200, size=speed.DOWNLOAD_BYTES, seconds=4, content="application/octet-stream", exit_code=0):
        return subprocess.CompletedProcess([], exit_code, json.dumps({
            "http_code": code, "size_download": size, "time_total": seconds,
            "speed_download": size / seconds if seconds else 0, "time_starttransfer": 0.25,
            "content_type": content, "remote_ip": "203.0.113.1", "url_effective": "secret-do-not-copy",
        }), "secret stderr must not escape")

    def measure(self, response):
        with patch.object(speed.subprocess, "run", return_value=response):
            return speed.transfer("curl", 31002, 20)

    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = speed.main(argv)
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    @contextmanager
    def dummy_clients(self):
        active, history = [], []

        @contextmanager
        def client(name, config, core, socks, http, timeout):
            self.assertEqual(active, [])
            active.append(name)
            history.append(("start", name))
            try:
                yield object()
            finally:
                history.append(("stop", name))
                active.remove(name)

        with (patch.object(speed, "find_curl", return_value="curl"),
              patch.object(speed, "load_profile", side_effect=lambda _, name: {"protocol": "vless" if name == "vless" else "hysteria2", "secret": "do-not-print"}),
              patch.object(speed, "resolve_core", return_value=Path("dummy-core")),
              patch.object(speed, "build_config", return_value={"secret": "do-not-print"}),
              patch.object(speed, "running_core", side_effect=client)):
            yield history
        self.assertEqual(active, [])

    def test_generic_profiles_resolve_protocol_before_starting_core(self):
        bundle = Path("/private/example.json")
        with self.dummy_clients(), patch.object(speed, "profile_names", return_value=("primary", "secondary")) as names, patch.object(speed, "load_profile", side_effect=[{"protocol": "vless"}, {"protocol": "hysteria2"}]), patch.object(speed, "resolve_core", return_value=Path("dummy")) as core, patch.object(speed.subprocess, "run", return_value=self.response()):
            code, report, _ = self.invoke(["--profiles-file", str(bundle), "--rounds", "1"])
        self.assertEqual(code, 0)
        names.assert_called_once_with(bundle)
        self.assertEqual(report["profiles"], ["primary", "secondary"])
        self.assertEqual([call.args[0] for call in core.call_args_list], ["vless", "hysteria2"])

    def test_explicit_generic_dry_run_skips_name_and_credential_reads(self):
        code, report, _ = self.invoke(["--profiles", "primary", "secondary", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(report["payloadBudgetBytes"], 60 * 1024 * 1024)
        self.names.assert_not_called()
        self.profiles.assert_not_called()

    def test_method_dispatch_accepts_leading_and_flag_forms(self):
        for argv in (["file", "--dry-run"], ["--method", "file", "--dry-run"],
                     ["fast", "--dry-run"], ["--method=fast", "--dry-run"]):
            with self.subTest(argv=argv):
                code, report, _ = self.invoke(argv)
                self.assertEqual(code, 0)
                self.assertEqual(report["results"], [])
                self.assertEqual("maxObservedBytesPerProfile" in report, "fast" in " ".join(argv))

    def test_conflicting_and_unknown_methods_rejected(self):
        for argv in (["fast", "--method", "file"], ["--method", "other"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                speed.main(argv)

    def test_file_help_and_plans_do_not_import_playwright(self):
        import builtins
        original = builtins.__import__

        def no_playwright(name, *args, **kwargs):
            if name.startswith("playwright"):
                raise AssertionError("Playwright must remain optional")
            return original(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=no_playwright):
            for argv in (["--dry-run"], ["fast", "--dry-run"]):
                self.assertEqual(self.invoke(argv)[0], 0)
            for argv in (["--help"], ["fast", "--help"]):
                with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                    speed.main(argv)
                self.assertEqual(stopped.exception.code, 0)

    def test_profile_environment_and_explicit_override(self):
        with patch.dict(os.environ, {"VPN_PROFILES_FILE": "/private/environment.json"}):
            self.assertEqual(speed.parse_args([]).profiles_file, Path("/private/environment.json"))
            self.assertEqual(speed.parse_args(["--profiles-file", "/private/explicit.json"]).profiles_file,
                             Path("/private/explicit.json"))

    def test_generic_hysteria2_alias_needs_no_private_operational_opt_in(self):
        self.assertEqual(speed.parse_args(["--profiles", "hysteria2"]).profiles, ["hysteria2"])

    def test_default_dry_run_no_private_read_core_or_network(self):
        code, report, _ = self.invoke(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(report["profiles"], [])
        self.assertIn("profileSelection", report)
        self.assertEqual(report["rounds"], 3)
        self.assertIsNone(report["payloadBudgetBytes"])
        self.names.assert_not_called()
        self.assertEqual(report["results"], [])
        self.network.assert_not_called()
        self.profiles.assert_not_called()
        self.cores.assert_not_called()
        self.client.assert_not_called()
        self.ports.assert_not_called()

    def test_invalid_limits_and_custom_urls_rejected_without_execution(self):
        invalid = [["--rounds", str(value)] for value in (0, -1, 6)]
        invalid += [["--bytes", str(value)] for value in (0, 1, 20 * 1024 * 1024, 21 * 1024 * 1024)]
        invalid += [["--max-time", str(value)] for value in (0, 31)]
        invalid += [["--url", "http://127.0.0.1/private"], ["--profiles", "vless", "vless"]]
        invalid += [["--label", label] for label in ("", "a" * 81, "line\nline", "\x1b[31m", "‮")]
        for argv in invalid:
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                speed.parse_args(argv)
            self.assertEqual(caught.exception.code, 2)
        self.network.assert_not_called()
        self.profiles.assert_not_called()

    def test_external_bundle_is_used_without_disclosing_path(self):
        bundle = Path("external-private-bundle.json")
        with self.dummy_clients(), patch.object(speed, "load_profile", return_value={"protocol": "vless"}) as load, patch.object(
            speed.subprocess, "run", return_value=self.response()
        ):
            code, report, stderr = self.invoke(["--profiles", "vless", "--profiles-file", str(bundle), "--rounds", "1"])
        self.assertEqual(code, 0)
        load.assert_called_once_with(bundle, "vless")
        self.assertNotIn(str(bundle), json.dumps(report) + stderr)

    def test_external_bundle_dry_run_does_not_read_it(self):
        code, report, _ = self.invoke(["--profiles", "vless", "--profiles-file", "absent-private.json", "--dry-run"])
        self.assertEqual(code, 0)
        self.profiles.assert_not_called()
        self.assertEqual(report["payloadBudgetBytes"], 30 * 1024 * 1024)

    def test_public_parser_rejects_private_opt_in_flags(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            speed.parse_args(["--profiles", "hysteria2", "--allow-hysteria2", "--dry-run"])
        code, report, _ = self.invoke(["--profiles", "hysteria2", "--rounds", "5", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(report["payloadBudgetBytes"], 50 * 1024 * 1024)
        self.network.assert_not_called()

    def test_budget_guard(self):
        with patch.object(speed, "MAX_BUDGET", 10), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            speed.parse_args(["--profiles", "primary", "--dry-run"])

    def test_maximum_supported_budget_under_ceiling(self):
        args = speed.parse_args(["--profiles", "primary", "secondary", "backup", "--rounds", "5"])
        self.assertLessEqual(len(args.profiles) * args.rounds * args.bytes, speed.MAX_BUDGET)

    def test_safe_curl_flags_override_environment_and_curlrc(self):
        environment = {"HTTPS_PROXY": "http://other.invalid:8888", "NO_PROXY": "*", "CURL_HOME": "bad-curlrc"}
        with patch.dict(os.environ, environment), patch.object(speed.subprocess, "run", return_value=self.response()) as run:
            result = speed.transfer("curl", 31002, 20)
        command = run.call_args.args[0]
        self.assertTrue(result["complete"])
        self.assertEqual(command[1], "--disable")
        for flag, value in (("--proxy", "http://127.0.0.1:31002"), ("--noproxy", ""),
                            ("--proto", "=https"), ("--max-filesize", str(speed.DOWNLOAD_BYTES)),
                            ("--max-time", "20"), ("--connect-timeout", "5"), ("--retry", "0"),
                            ("--url", speed.URL), ("--output", os.devnull)):
            self.assertEqual(command[command.index(flag) + 1], value)
        for flag in ("--insecure", "-k", "--location", "-L", "--compressed", "--parallel"):
            self.assertNotIn(flag, command)
        self.assertEqual(run.call_args.kwargs["timeout"], 25)

    def test_success_metrics_units_and_no_sensitive_curl_fields(self):
        result = self.measure(self.response())
        self.assertTrue(result["complete"])
        self.assertEqual(result["mbps"], 20.972)
        self.assertEqual(result["ttfbSeconds"], 0.25)
        self.assertEqual(result["curlBytesPerSecond"], speed.DOWNLOAD_BYTES / 4)
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("203.0.113.1", json.dumps(result))
        self.assertIsNone(result["partialMbps"])

    def test_http_error_and_redirect_never_count_as_speed(self):
        for code in (301, 302, 403, 404, 500):
            with self.subTest(code=code):
                result = self.measure(self.response(code=code))
                self.assertFalse(result["complete"])
                self.assertIsNone(result["mbps"])
                self.assertIsNone(result["partialMbps"])

    def test_wrong_length_empty_and_oversized_responses_fail(self):
        for size in (0, 12, speed.DOWNLOAD_BYTES - 1, speed.DOWNLOAD_BYTES + 1):
            with self.subTest(size=size):
                result = self.measure(self.response(size=size))
                self.assertFalse(result["complete"])
                self.assertIsNone(result["mbps"])

    def test_html_json_and_missing_content_type_fail_even_at_correct_length(self):
        for content in ("text/html", "application/json", "text/plain", ""):
            with self.subTest(content=content):
                result = self.measure(self.response(content=content))
                self.assertFalse(result["complete"])
                self.assertEqual(result["reason"], "unexpected_content")
                self.assertIsNone(result["partialMbps"])

    def test_binary_content_type_parameters_are_accepted(self):
        self.assertTrue(self.measure(self.response(content="application/octet-stream; charset=binary"))["complete"])

    def test_timeout_partial_throughput_is_not_complete(self):
        result = self.measure(self.response(size=2 * 1024 * 1024, seconds=8, exit_code=28))
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["partialMbps"], 2.097)
        self.assertIsNone(result["mbps"])

    def test_nonzero_exit_with_full_length_does_not_pass(self):
        self.assertFalse(self.measure(self.response(exit_code=23))["complete"])

    def test_process_timeout_suppresses_raw_output(self):
        with patch.object(speed.subprocess, "run", side_effect=subprocess.TimeoutExpired("secret command", 25, output="secret")):
            result = speed.transfer("curl", 31002, 20)
        self.assertEqual(result["reason"], "process_timeout")
        self.assertNotIn("secret", json.dumps(result))

    def test_invalid_or_nonfinite_metrics_fail_closed(self):
        responses = [subprocess.CompletedProcess([], 0, "secret non-JSON", "secret"),
                     self.response(seconds=0), self.response(seconds=float("nan")), self.response(size=-1),
                     self.response(size=float("inf")), subprocess.CompletedProcess([], 0, "[]", "secret")]
        for response in responses:
            with self.subTest(stdout=response.stdout):
                result = self.measure(response)
                self.assertFalse(result["complete"])
                self.assertEqual(result["reason"], "invalid_metrics")
                self.assertNotIn("secret", json.dumps(result))

    def test_curl_preflight_requires_modern_size_enforcement(self):
        for version, accepted in (("8.3.0", False), ("8.4.0", True), ("8.10.1", True)):
            response = subprocess.CompletedProcess([], 0, f"curl {version} test\n", "")
            with self.subTest(version=version), patch.object(speed.shutil, "which", return_value="curl"), patch.object(speed.subprocess, "run", return_value=response) as run:
                if accepted:
                    self.assertEqual(speed.find_curl(), "curl")
                else:
                    with self.assertRaises(RuntimeError):
                        speed.find_curl()
                self.assertEqual(run.call_args.args[0], ["curl", "--disable", "--version"])

    def test_missing_curl_reports_failure_before_profile_reads(self):
        with patch.object(speed.shutil, "which", return_value=None):
            code, report, _ = self.invoke([])
        self.assertEqual(code, 1)
        self.assertEqual(report["results"], [])
        self.profiles.assert_not_called()
        self.network.assert_not_called()

    def test_round_robin_owned_client_cleanup(self):
        with self.dummy_clients() as history, patch.object(speed.subprocess, "run", return_value=self.response()):
            code, report, stderr = self.invoke(["--rounds", "2"])
        expected = [(event, name) for _ in range(2) for name in ("vless", "hysteria2") for event in ("start", "stop")]
        self.assertEqual(history, expected)
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["vless"]["validRounds"], 2)
        self.assertNotIn("do-not-print", json.dumps(report) + stderr)

    def test_cleanup_after_transfer_timeout_and_failure_json(self):
        with self.dummy_clients() as history, patch.object(speed.subprocess, "run", side_effect=subprocess.TimeoutExpired("secret", 25)):
            code, report, _ = self.invoke(["--profiles", "secondary-hy2", "--rounds", "1"])
        self.assertEqual(code, 1)
        self.assertEqual(history, [("start", "hysteria2"), ("stop", "hysteria2")])
        self.assertEqual(report["results"][0]["reason"], "process_timeout")
        self.assertIsNone(report["summary"]["secondary-hy2"]["medianMbps"])

    def test_interrupt_cleans_up_and_returns_partial_report(self):
        with self.dummy_clients() as history, patch.object(speed, "transfer", side_effect=KeyboardInterrupt):
            code, report, _ = self.invoke(["--rounds", "2"])
        self.assertEqual(code, 130)
        self.assertEqual(history, [("start", "vless"), ("stop", "vless")])
        self.assertEqual(report["results"][0]["reason"], "interrupted")

    def test_setup_or_cleanup_exception_stops_suite_without_raw_error(self):
        with self.dummy_clients(), patch.object(speed, "running_core", side_effect=RuntimeError("secret credential")):
            code, report, stderr = self.invoke([])
        self.assertEqual(code, 1)
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["reason"], "client_failed")
        self.assertNotIn("secret", json.dumps(report) + stderr)

    def test_cleanup_failure_invalidates_sample_and_stops_next_client(self):
        @contextmanager
        def failed_cleanup(*_):
            try:
                yield object()
            finally:
                raise RuntimeError("secret cleanup detail")

        with self.dummy_clients(), patch.object(speed, "running_core", side_effect=failed_cleanup) as client, patch.object(speed.subprocess, "run", return_value=self.response()):
            code, report, stderr = self.invoke([])
        self.assertEqual(code, 1)
        self.assertEqual(client.call_count, 1)
        self.assertFalse(report["results"][0]["complete"])
        self.assertIsNone(report["results"][0]["mbps"])
        self.assertNotIn("secret", json.dumps(report) + stderr)

    def test_private_profile_failure_is_sanitized_and_starts_no_client(self):
        with patch.object(speed, "find_curl", return_value="curl"), patch.object(speed, "load_profile", side_effect=RuntimeError("secret profile contents")):
            code, report, stderr = self.invoke([])
        self.assertEqual(code, 1)
        self.client.assert_not_called()
        self.assertNotIn("secret", json.dumps(report) + stderr)

    def test_invalid_endpoint_stops_suite_after_cleanup(self):
        for response in (self.response(code=403), self.response(content="text/html"), self.response(size=12),
                         self.response(code=403, exit_code=28), self.response(content="text/html", exit_code=28)):
            with self.subTest(response=response.stdout), self.dummy_clients() as history, patch.object(speed.subprocess, "run", return_value=response) as curl:
                code, report, _ = self.invoke(["--rounds", "3"])
            self.assertEqual(code, 1)
            self.assertEqual(curl.call_count, 1)
            self.assertEqual(history, [("start", "vless"), ("stop", "vless")])
            self.assertEqual(len(report["results"]), 1)
            self.assertEqual(report["summary"]["vless"]["validRounds"], 0)
            self.assertEqual(report["summary"]["secondary-hy2"]["attemptedRounds"], 0)

    def test_binary_timeout_may_continue_bounded_rounds(self):
        with self.dummy_clients() as history, patch.object(speed.subprocess, "run", side_effect=[self.response(size=1024, exit_code=28), self.response()]):
            code, report, _ = self.invoke(["--profiles", "secondary-hy2", "--rounds", "2"])
        self.assertEqual(code, 1)
        self.assertEqual(len(history), 4)
        self.assertEqual(report["summary"]["secondary-hy2"]["validRounds"], 1)

    def test_ttfb_larger_than_total_time_fails_closed(self):
        result = self.measure(self.response(seconds=0.1))
        self.assertFalse(result["complete"])
        self.assertEqual(result["reason"], "invalid_metrics")

    def test_valid_only_summary_and_all_fail_null_not_zero(self):
        values = [{"profile": "vless", "complete": True, "mbps": value} for value in (20, 30, 10)]
        values += [{"profile": "vless", "complete": False, "mbps": None, "partialMbps": 80}]
        values += [{"profile": "hysteria2", "complete": False, "mbps": None}]
        summary = speed.summarize(["vless", "hysteria2"], values)
        self.assertEqual(summary["vless"], {"validRounds": 3, "attemptedRounds": 4, "medianMbps": 20, "minMbps": 10, "maxMbps": 30})
        self.assertIsNone(summary["hysteria2"]["medianMbps"])
        self.assertIsNone(summary["hysteria2"]["minMbps"])
        self.assertIsNone(summary["hysteria2"]["maxMbps"])

    def test_new_output_saved_and_overwrite_forbidden(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(speed, "runtime_root", return_value=Path(directory)):
            destination = Path(directory) / ".local" / "speed-tests" / "sample.json"
            with self.dummy_clients(), patch.object(speed.subprocess, "run", return_value=self.response()):
                code, report, _ = self.invoke(["--profiles", "vless", "--rounds", "1", "--output", str(destination)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), report)
            with self.assertRaises(ValueError):
                speed.output_path(destination)

    def test_dry_run_never_creates_output(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(speed, "runtime_root", return_value=Path(directory)):
            destination = Path(directory) / ".local" / "speed-tests" / "sample.json"
            code, _, _ = self.invoke(["--dry-run", "--output", str(destination)])
            self.assertEqual(code, 0)
            self.assertFalse(destination.parent.exists())

    def test_output_paths_cannot_touch_profiles_vendor_git_or_escape(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(speed, "runtime_root", return_value=Path(directory)):
            for relative in ("profiles/vpn-profiles.json", "vendor/new.json", ".git/new.json", "../outside.json",
                             ".local/speed-tests/../escape.json", ".local/speed-tests/new.txt"):
                with self.subTest(path=relative), self.assertRaises(ValueError):
                    speed.output_path(Path(relative))
            with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
                speed.output_path(Path(".local/speed-tests/new.json"))

    def test_save_race_cannot_overwrite_and_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(speed, "runtime_root", return_value=Path(directory)):
            destination = Path(directory) / ".local" / "speed-tests" / "sample.json"

            def raced_transfer(*_):
                destination.parent.mkdir(parents=True)
                destination.write_text("existing result", encoding="utf-8")
                return {"complete": True, "reason": "complete", "mbps": 10, "partialMbps": None}

            with self.dummy_clients(), patch.object(speed, "transfer", side_effect=raced_transfer):
                code, report, _ = self.invoke(["--profiles", "vless", "--rounds", "1", "--output", str(destination)])
            self.assertEqual(code, 1)
            self.assertIn("outputError", report)
            self.assertEqual(destination.read_text(encoding="utf-8"), "existing result")


if __name__ == "__main__":
    unittest.main()
