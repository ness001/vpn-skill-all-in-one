"""Offline Fast.com regression tests; profiles, browsers, clients and network are all fake."""
import builtins
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fast_com_test as fast
import speed_test
import speed_common

LOAD_PLAYWRIGHT = fast.load_playwright


def state(value="120", units="Mbps", succeeded=True, progressing=False, **changes):
    result = {"value": value, "units": units, "valueClasses": ["succeeded"] if succeeded else [],
              "ancestorClasses": [], "resultClasses": [], "progressClasses": ["in-progress"] if progressing else [],
              "progressPresent": True}
    result.update(changes)
    return result


class FakeBrowser:
    def __init__(self, states=None, events=None, goto_error=None, evaluate_error=None,
                 context_error=None, browser_error=None, goto_seconds=0):
        self.clock = 0
        self.states = list(states or [state()])
        self.events = events or []
        self.goto_error, self.evaluate_error = goto_error, evaluate_error
        self.context_error, self.browser_error = context_error, browser_error
        self.goto_seconds = goto_seconds
        self.history, self.commands, self.waits = [], [], []
        self.chromium = SimpleNamespace(launch=Mock(side_effect=self.launch))

    def launch(self, **kwargs):
        self.history.append("browser-start")
        self.launch_args = kwargs
        return self

    def new_context(self, **kwargs):
        self.context_args = kwargs
        return SimpleNamespace(close=self.close_context, route=self.route, new_page=lambda: self,
                               new_cdp_session=lambda _: self)

    def route(self, pattern, handler):
        self.route_handler = handler

    def on(self, name, callback):
        self.callback = callback

    def send(self, command, params=None):
        self.commands.append((command, params))

    def goto(self, url, **kwargs):
        self.url, self.goto_args = url, kwargs
        self.clock += self.goto_seconds
        for event in self.events:
            self.callback(event)
        if self.goto_error:
            raise self.goto_error

    def evaluate(self, script):
        self.script = script
        if self.evaluate_error:
            raise self.evaluate_error
        result = self.states[0]
        if len(self.states) > 1:
            self.states.pop(0)
        return result

    def wait_for_timeout(self, millis):
        self.waits.append(millis)
        self.clock += millis / 1000

    def close_context(self):
        self.history.append("context-stop")
        if self.context_error:
            raise self.context_error

    def close(self):
        self.history.append("browser-stop")
        if self.browser_error:
            raise self.browser_error


class FastTests(unittest.TestCase):
    def setUp(self):
        self.names = self.enterContext(patch.object(fast, "profile_names", return_value=("vless", "secondary-hy2")))
        self.profiles = self.enterContext(patch.object(fast, "load_profile", side_effect=AssertionError("No real profiles")))
        self.cores = self.enterContext(patch.object(fast, "resolve_core", side_effect=AssertionError("No real cores")))
        self.ports = self.enterContext(patch.object(fast, "free_ports", return_value=(31001, 31002)))
        self.clients = self.enterContext(patch.object(fast, "running_core", side_effect=AssertionError("No real clients")))
        self.browser = self.enterContext(patch.object(fast, "browser_path", side_effect=AssertionError("No real browser lookup")))
        self.playwright = self.enterContext(patch.object(fast, "load_playwright", side_effect=AssertionError("No real Playwright import")))
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory).resolve()
        self.enterContext(patch.object(fast, "runtime_root", return_value=self.root))
        self.enterContext(patch.object(speed_test, "runtime_root", return_value=self.root))

    def invoke(self, argv=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = fast.main(argv or [])
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def measure(self, browser, argv=None):
        args = fast.parse_args(argv or ["--max-time", "1", "--max-observed-mib", "16"])
        with patch.object(fast.time, "monotonic", side_effect=lambda: browser.clock):
            result = fast.measure(browser, Path("installed-browser"), 31002, args)
        return result

    @contextmanager
    def fake_clients(self):
        active, history = [], []

        @contextmanager
        def client(name, *_):
            self.assertEqual(active, [])
            active.append(name)
            history.append(("start", name))
            try:
                yield object()
            finally:
                history.append(("stop", name))
                active.remove(name)

        @contextmanager
        def runtime():
            yield object()

        with (patch.object(fast, "load_profile", side_effect=lambda _, name: {"protocol": "vless" if name == "vless" else "hysteria2", "secret": "private-token"}),
              patch.object(fast, "resolve_core", return_value=Path("dummy-core")),
              patch.object(fast, "build_config", return_value={"secret": "private-token"}),
              patch.object(fast, "running_core", side_effect=client),
              patch.object(fast, "browser_path", return_value=Path("installed-browser")),
              patch.object(fast, "load_playwright", return_value=runtime)):
            yield history
        self.assertEqual(active, [])

    def success(self, *_, **__):
        return {"completed": True, "reason": "completed", "finalMbps": 120, "provisionalMbps": None}

    def test_profile_environment_explicit_override_and_external_bundle_use(self):
        import os
        bundle = Path("external-private.json")
        with patch.dict(os.environ, {"VPN_PROFILES_FILE": "/private/environment.json"}):
            self.assertEqual(fast.parse_args([]).profiles_file, Path("/private/environment.json"))
            self.assertEqual(fast.parse_args(["--profiles-file", str(bundle)]).profiles_file, bundle)
        with self.fake_clients(), patch.object(fast, "load_profile", return_value={"protocol": "vless"}) as load, patch.object(
            fast, "measure", side_effect=self.success
        ):
            code, report, stderr = self.invoke(["--profiles", "vless", "--profiles-file", str(bundle)])
        self.assertEqual(code, 0)
        load.assert_called_once_with(bundle, "vless")
        self.assertNotIn(str(bundle), json.dumps(report) + stderr)

    def test_configured_generic_profiles_use_protocol_for_cores(self):
        with self.fake_clients(), patch.object(fast, "profile_names", return_value=("primary", "secondary")), patch.object(fast, "load_profile", side_effect=[{"protocol": "vless"}, {"protocol": "hysteria2"}]), patch.object(fast, "resolve_core", return_value=Path("dummy")) as cores, patch.object(fast, "measure", side_effect=self.success):
            code, report, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report["profiles"], ["primary", "secondary"])
        self.assertEqual([call.args[0] for call in cores.call_args_list], ["vless", "hysteria2"])

    def test_explicit_generic_dry_run_never_reads_bundle(self):
        code, report, _ = self.invoke(["--profiles", "primary", "secondary", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(report["totalSelectedObservedBudgetBytes"], 512 * fast.MIB)
        self.names.assert_not_called()
        self.profiles.assert_not_called()

    def test_generic_hysteria2_alias_needs_no_private_operational_opt_in(self):
        self.assertEqual(fast.parse_args(["--profiles", "hysteria2"]).profiles, ["hysteria2"])

    def test_dry_run_defaults_without_any_runtime_access_or_file(self):
        code, report, _ = self.invoke(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(report["profiles"], [])
        self.assertIn("profileSelection", report)
        self.assertEqual(report["maxTimeSeconds"], 55)
        self.assertEqual(report["maxObservedBytesPerProfile"], 256 * fast.MIB)
        self.assertIsNone(report["totalSelectedObservedBudgetBytes"])
        self.names.assert_not_called()
        self.assertEqual(report["results"], [])
        self.assertTrue(report["headless"])
        for mocked in (self.playwright, self.browser, self.profiles, self.cores, self.ports, self.clients):
            mocked.assert_not_called()
        self.assertFalse((self.root / ".local").exists())

    def test_limits_reject_out_of_bounds_and_custom_url(self):
        invalid = [["--max-time", str(n)] for n in (0, -1, 121)]
        invalid += [["--max-observed-mib", str(n)] for n in (0, 15, 513)]
        invalid += [["--url", "https://other.invalid"], ["--profiles", "vless", "vless"]]
        invalid += [["--label", label] for label in ("", "a" * 81, "line\nline", "\x1b[31m", "‮")]
        for argv in invalid:
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                fast.parse_args(argv)

    def test_boundary_limits_accepted(self):
        for time_limit, byte_limit in ((1, 16), (120, 512)):
            args = fast.parse_args(["--max-time", str(time_limit), "--max-observed-mib", str(byte_limit)])
            self.assertEqual(args.max_time, time_limit)
            self.assertEqual(args.max_observed_mib, byte_limit)

    def test_total_budget_rejects_three_times_512(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fast.parse_args(["--profiles", "vless", "secondary-hy2", "hysteria2", "--max-observed-mib", "512"])

    def test_public_parser_rejects_private_opt_in_flags_without_clients(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fast.parse_args(["--profiles", "hysteria2", "--allow-hysteria2"])
        code, report, _ = self.invoke(["--profiles", "hysteria2", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(report["profiles"], ["hysteria2"])
        self.clients.assert_not_called()

    def test_optional_dependency_missing_is_friendly_and_no_profiles(self):
        with patch.object(fast, "load_playwright", side_effect=ImportError("private-token")):
            code, report, stderr = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("Optional Playwright is missing", report["error"])
        self.assertNotIn("private-token", json.dumps(report) + stderr)
        self.profiles.assert_not_called()
        self.clients.assert_not_called()

    def test_lazy_loader_imports_only_when_called(self):
        original = builtins.__import__
        imports = []

        def fake_import(name, *args, **kwargs):
            imports.append(name)
            if name == "playwright.sync_api":
                raise ImportError("not installed")
            return original(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            self.invoke(["--dry-run"])
            self.assertNotIn("playwright.sync_api", imports)
            with self.assertRaises(ImportError):
                LOAD_PLAYWRIGHT()
        self.assertIn("playwright.sync_api", imports)

    def test_missing_installed_browser_does_not_read_profiles(self):
        with self.fake_clients(), patch.object(fast, "browser_path", side_effect=RuntimeError("private-token")), patch.object(fast, "load_profile") as profiles:
            code, report, stderr = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report["errorClass"], "RuntimeError")
        profiles.assert_not_called()
        self.assertNotIn("private-token", json.dumps(report) + stderr)

    def test_units_converted_to_decimal_mbps(self):
        for text, units, expected in (("120", "Mbps", 120), ("800", "Kbps", .8), ("1.5", "Gbps", 1500),
                                      ("1,5", "Mbps", 1.5), ("1 234,5", "Mbps", 1234.5),
                                      ("١٢٫٥", "Mbps", 12.5), ("１２.５", "Mbps", 12.5)):
            with self.subTest(text=text, units=units):
                self.assertEqual(fast.displayed_mbps(text, units), expected)

    def test_unknown_byte_units_or_non_numeric_values_never_become_rates(self):
        for text, units in (("120", "MBps"), ("120", "Bps"), ("120", "mbps"), ("1,234.5", "Mbps"),
                            ("NaN", "Mbps"), ("inf", "Mbps"), ("0", "Mbps"), ("-1", "Mbps"),
                            ("1e9", "Mbps"), ("1/2", "Mbps"), (None, "Mbps"), ("x" * 100, "Mbps")):
            with self.subTest(text=text, units=units):
                self.assertIsNone(fast.displayed_mbps(text, units))

    def test_value_only_never_proves_completed(self):
        _, speed, completed = fast.page_state(state(succeeded=False))
        self.assertEqual(speed, 120)
        self.assertFalse(completed)

    def test_value_succeeded_but_progress_running_is_incomplete(self):
        self.assertFalse(fast.page_state(state(progressing=True))[2])

    def test_result_succeeded_without_value_or_ancestor_signal_is_incomplete(self):
        self.assertFalse(fast.page_state(state(succeeded=False, resultClasses=["succeeded"]))[2])

    def test_ancestor_success_requires_present_nonrunning_progress(self):
        self.assertTrue(fast.page_state(state(succeeded=False, ancestorClasses=["succeeded"]))[2])
        self.assertFalse(fast.page_state(state(progressPresent=False))[2])
        self.assertFalse(fast.page_state(state(resultClasses=["in-progress"]))[2])
        self.assertFalse(fast.page_state(state(progressClasses=["failed"]))[2])

    def test_unknown_units_or_empty_value_never_complete(self):
        self.assertFalse(fast.page_state(state(units="unknown"))[2])
        self.assertFalse(fast.page_state(state(value=""))[2])

    def test_dom_output_has_strict_allowlist(self):
        raw = state(value="private-token", units="private-token", valueClasses=["private-token", "succeeded"],
                    url="https://secret.invalid", body="private-token", ip="203.0.113.1")
        sanitized, _, _ = fast.page_state(raw)
        text = json.dumps(sanitized)
        for secret in ("private-token", "secret.invalid", "203.0.113.1"):
            self.assertNotIn(secret, text)
        self.assertEqual(sanitized["valueClasses"], ["succeeded"])

    def test_browser_success_is_actual_page_headless_proxy_and_strict_tls(self):
        browser = FakeBrowser()
        result = self.measure(browser)
        self.assertTrue(result["completed"])
        self.assertEqual(result["finalMbps"], 120)
        self.assertIsNone(result["provisionalMbps"])
        self.assertEqual(browser.url, "https://fast.com/")
        self.assertTrue(browser.launch_args["headless"])
        self.assertEqual(browser.launch_args["proxy"], {"server": "http://127.0.0.1:31002"})
        self.assertFalse(browser.context_args["ignore_https_errors"])
        self.assertEqual(browser.context_args["service_workers"], "block")
        self.assertEqual(browser.launch_args["executable_path"], "installed-browser")
        self.assertIn("--disable-quic", browser.launch_args["args"])
        self.assertIn("#speed-value", browser.script)
        self.assertEqual(browser.history, ["browser-start", "context-stop", "browser-stop"])
        self.assertEqual(browser.commands[-1][0], "Network.emulateNetworkConditions")

    def test_headed_is_explicit_only(self):
        browser = FakeBrowser()
        self.measure(browser, ["--headed"])
        self.assertFalse(browser.launch_args["headless"])

    def test_in_progress_timeout_retains_only_provisional_rate(self):
        browser = FakeBrowser(states=[state(progressing=True)])
        result = self.measure(browser)
        self.assertFalse(result["completed"])
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["provisionalMbps"], 120)
        self.assertIsNone(result["finalMbps"])
        self.assertTrue(all(millis <= 100 for millis in browser.waits))
        self.assertEqual(browser.history[-2:], ["context-stop", "browser-stop"])

    def test_navigation_time_is_included_and_no_second_full_budget(self):
        browser = FakeBrowser(goto_seconds=0.95, states=[state(progressing=True)])
        result = self.measure(browser)
        self.assertEqual(browser.goto_args["timeout"], 1000)
        self.assertLessEqual(sum(browser.waits), 51)
        self.assertLessEqual(result["elapsedSeconds"], 1.002)
        self.assertEqual(result["reason"], "timeout")

    def test_navigation_timeout_is_not_fake_zero_or_raw_error(self):
        browser = FakeBrowser(goto_error=TimeoutError("private-token"))
        result = self.measure(browser)
        self.assertEqual(result["reason"], "timeout")
        self.assertIsNone(result["finalMbps"])
        self.assertIsNone(result["provisionalMbps"])
        self.assertNotIn("errorClass", result)
        self.assertNotIn("private-token", json.dumps(result))
        self.assertEqual(browser.history[-2:], ["context-stop", "browser-stop"])

    def test_budget_counts_decoded_encoded_independently_and_reports_overshoot(self):
        limit = 16 * fast.MIB
        browser = FakeBrowser(events=[{"dataLength": limit + 123, "encodedDataLength": limit // 2,
                                       "requestId": "private-token"}])
        result = self.measure(browser)
        self.assertFalse(result["completed"])
        self.assertEqual(result["reason"], "observed_budget")
        self.assertIsNone(result["finalMbps"])
        self.assertEqual(result["observedDecodedBytes"], limit + 123)
        self.assertEqual(result["observedEncodedBytes"], limit // 2)
        self.assertEqual(result["observedResponseBytes"], limit + 123)
        self.assertEqual(result["observedOvershootBytes"], 123)
        self.assertNotIn("private-token", json.dumps(result))
        route = Mock()
        browser.route_handler(route)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()
        self.assertEqual(browser.commands[-1][1]["offline"], True)

    def test_encoded_budget_can_stop_compressed_or_streamed_responses(self):
        limit = 16 * fast.MIB
        browser = FakeBrowser(events=[{"dataLength": 1, "encodedDataLength": limit}])
        self.assertEqual(self.measure(browser)["reason"], "observed_budget")

    def test_counts_are_not_double_counted(self):
        chunk = 9 * fast.MIB
        browser = FakeBrowser(events=[{"dataLength": chunk, "encodedDataLength": chunk}])
        result = self.measure(browser)
        self.assertTrue(result["completed"])
        self.assertEqual(result["observedResponseBytes"], chunk)

    def test_budget_hit_while_navigation_fails_is_capped_not_browser_error(self):
        browser = FakeBrowser(events=[{"dataLength": 16 * fast.MIB}], goto_error=RuntimeError("private-token"))
        result = self.measure(browser)
        self.assertEqual(result["reason"], "observed_budget")
        self.assertNotIn("errorClass", result)

    def test_evaluation_failure_is_class_only_and_cleans_up(self):
        browser = FakeBrowser(evaluate_error=RuntimeError("https://private.invalid/token"))
        result = self.measure(browser)
        self.assertEqual(result["reason"], "browser_failed")
        self.assertEqual(result["errorClass"], "RuntimeError")
        self.assertNotIn("private.invalid", json.dumps(result))
        self.assertEqual(browser.history[-2:], ["context-stop", "browser-stop"])

    def test_keyboard_interrupt_stops_network_and_browser(self):
        browser = FakeBrowser(evaluate_error=KeyboardInterrupt())
        result = self.measure(browser)
        self.assertEqual(result["reason"], "interrupted")
        self.assertFalse(result["completed"])
        self.assertEqual(browser.commands[-1][0], "Network.emulateNetworkConditions")
        self.assertEqual(browser.history[-2:], ["context-stop", "browser-stop"])

    def test_context_cleanup_failure_still_closes_browser_and_invalidates(self):
        for error in (RuntimeError("private-token"), TimeoutError("private-token")):
            browser = FakeBrowser(context_error=error)
            result = self.measure(browser)
            self.assertEqual(result["reason"], "browser_failed")
            self.assertFalse(result["completed"])
            self.assertIsNone(result["finalMbps"])
            self.assertEqual(browser.history[-2:], ["context-stop", "browser-stop"])

    def test_browser_cleanup_failure_cannot_be_hidden_by_budget(self):
        browser = FakeBrowser(events=[{"dataLength": 16 * fast.MIB}], browser_error=RuntimeError("private-token"))
        self.assertEqual(self.measure(browser)["reason"], "browser_failed")

    def test_offline_cancellation_failure_falls_back_to_closure(self):
        browser = FakeBrowser()
        original_send = browser.send

        def send(command, params=None):
            original_send(command, params)
            if command == "Network.emulateNetworkConditions":
                raise RuntimeError("private-token")

        browser.send = send
        result = self.measure(browser)
        self.assertTrue(result["completed"])
        self.assertEqual(browser.history[-2:], ["context-stop", "browser-stop"])

    def test_profiles_run_serially_once_with_owned_cleanup(self):
        with self.fake_clients() as history, patch.object(fast, "measure", side_effect=self.success) as measure:
            code, report, stderr = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(history, [("start", "vless"), ("stop", "vless"), ("start", "hysteria2"), ("stop", "hysteria2")])
        self.assertEqual(measure.call_count, 2)
        self.assertEqual([item["profile"] for item in report["results"]], ["vless", "secondary-hy2"])
        self.assertNotIn("private-token", json.dumps(report) + stderr)

    def test_cap_and_timeout_continue_to_next_profile_but_exit_one(self):
        for reason in ("observed_budget", "timeout"):
            partial = {"completed": False, "reason": reason, "finalMbps": None, "provisionalMbps": 85}
            with self.fake_clients() as history, patch.object(fast, "measure", side_effect=[partial, self.success()]):
                code, report, stderr = self.invoke()
            self.assertEqual(code, 1)
            self.assertEqual(len(history), 4)
            self.assertEqual(len(report["results"]), 2)
            self.assertIsNone(report["results"][0]["finalMbps"])
            self.assertIn("85.000", stderr)

    def test_setup_failure_class_only_and_stops_suite(self):
        with self.fake_clients(), patch.object(fast, "load_profile", side_effect=ValueError("private-token")), patch.object(fast, "running_core") as clients:
            code, report, stderr = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["errorClass"], "ValueError")
        clients.assert_not_called()
        self.assertNotIn("private-token", json.dumps(report) + stderr)

    def test_client_cleanup_failure_invalidates_and_prevents_next_client(self):
        @contextmanager
        def client(*_):
            try:
                yield object()
            finally:
                raise RuntimeError("private-token")

        with self.fake_clients(), patch.object(fast, "running_core", side_effect=client) as clients, patch.object(fast, "measure", side_effect=self.success):
            code, report, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(clients.call_count, 1)
        self.assertEqual(report["results"][0]["reason"], "client_failed")
        self.assertFalse(report["results"][0]["completed"])
        self.assertIsNone(report["results"][0]["finalMbps"])

    def test_browser_failure_stops_next_client_after_cleanup(self):
        failure = {"completed": False, "reason": "browser_failed", "finalMbps": None, "provisionalMbps": None}
        with self.fake_clients() as history, patch.object(fast, "measure", return_value=failure):
            code, report, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(history, [("start", "vless"), ("stop", "vless")])
        self.assertEqual(len(report["results"]), 1)

    def test_interrupt_returns_json_and_cleans_client(self):
        with self.fake_clients() as history, patch.object(fast, "measure", side_effect=KeyboardInterrupt):
            code, report, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["reason"], "interrupted")
        self.assertEqual(history, [("start", "vless"), ("stop", "vless")])

    def test_default_output_new_filename_does_not_use_label(self):
        first, second = fast.parse_args(["--label", "no-filename-label"]), fast.parse_args([])
        self.assertNotEqual(first.output, second.output)
        self.assertEqual(first.output.parent, self.root / ".local" / "speed-tests")
        self.assertNotIn("no-filename-label", first.output.name)

    def test_new_result_file_matches_stdout_and_existing_is_refused(self):
        destination = self.root / ".local" / "speed-tests" / "test.json"
        with self.fake_clients(), patch.object(fast, "measure", side_effect=self.success):
            code, report, _ = self.invoke(["--output", str(destination)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), report)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fast.parse_args(["--output", str(destination)])

    def test_dry_run_never_writes_requested_file(self):
        destination = self.root / ".local" / "speed-tests" / "test.json"
        code, _, _ = self.invoke(["--output", str(destination), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertFalse(destination.parent.exists())

    def test_output_cannot_escape_or_use_symlinks(self):
        for path in ("profiles/new.json", "../outside.json", ".local/speed-tests/nested/test.json", ".local/speed-tests/new.txt"):
            with self.subTest(path=path), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                fast.parse_args(["--output", path])
        with patch.object(Path, "is_symlink", return_value=True), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fast.parse_args([])

    def test_output_race_never_overwrites_existing_file(self):
        destination = self.root / ".local" / "speed-tests" / "race.json"

        def measure(*_):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("existing", encoding="utf-8")
            return self.success()

        with self.fake_clients(), patch.object(fast, "measure", side_effect=measure):
            code, report, _ = self.invoke(["--profiles", "vless", "--output", str(destination)])
        self.assertEqual(code, 1)
        self.assertIn("outputError", report)
        self.assertEqual(destination.read_text(encoding="utf-8"), "existing")


if __name__ == "__main__":
    unittest.main()
