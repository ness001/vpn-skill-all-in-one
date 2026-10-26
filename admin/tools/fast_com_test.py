#!/usr/bin/env python3
"""Run the actual Fast.com page sequentially through isolated, strict-TLS VPN clients."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import math
from pathlib import Path
import platform
import re
import sys
import time
import unicodedata
from uuid import uuid4

from speed_common import ROOT, free_ports, select_profiles, output_path, runtime_root, utc_now
sys.path.insert(0, str(ROOT / "clients"))
from core_install import resolve_core
from vpn import build_config, load_profile, profile_names, resolve_protocol, running_core
from vpn_common import default_profiles_file

URL = "https://fast.com/"
MIB = 1024 * 1024
CLASSES = {"succeeded", "failed", "error", "in-progress", "complete", "completed"}
UNITS = {"Kbps": 0.001, "Mbps": 1, "Gbps": 1000}
STATE_JS = """() => {
    const value = document.querySelector('#speed-value');
    const units = document.querySelector('#speed-units');
    const progress = document.querySelector('#speed-progress-indicator');
    const result = document.querySelector('#speed-results');
    const allowed = new Set(['succeeded', 'failed', 'error', 'in-progress', 'complete', 'completed']);
    const classes = element => element ? [...element.classList].filter(c => allowed.has(c)) : [];
    return {value: value ? value.textContent.trim() : null,
        units: units ? units.textContent.trim() : null,
        valueClasses: classes(value), resultClasses: classes(result),
        ancestorClasses: classes(value && value.parentElement && value.parentElement.closest('.succeeded')),
        progressClasses: classes(progress), progressPresent: !!progress};
}"""


def parse_args(argv=None, *, profiles_file=None, output_root=None, default_profiles=None, parser_setup=None, profile_policy=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", nargs="+", help="Configured profile IDs; execution defaults to all configured entries.")
    parser.add_argument("--profiles-file", type=Path,
                        default=profiles_file if profiles_file is not None else default_profiles_file(),
                        help="Private profile bundle; overrides VPN_PROFILES_FILE.")
    parser.add_argument("--max-time", type=int, default=55, help="Per-browser time budget, including navigation, 1 to 120 seconds.")
    parser.add_argument("--max-observed-mib", type=int, default=256, help="Per-profile observed response budget, 16 to 512 MiB; not a wire cap.")
    parser.add_argument("--label", default="current local machine", help="Actual testing machine/network only, not the VPN server; omit private identifiers.")
    parser.add_argument("--output", type=Path, help="New .local/speed-tests/<name>.json; defaults to a unique timestamped file.")
    parser.add_argument("--headed", action="store_true", help="Show the isolated browser instead of the default headless mode.")
    parser.add_argument("--dry-run", action="store_true", help="Validate/print plan only; no Playwright import, profiles, browser, files or network.")
    if parser_setup is not None:
        parser_setup(parser)
    args = parser.parse_args(argv)
    if not 1 <= args.max_time <= 120:
        parser.error("--max-time must be between 1 and 120 seconds.")
    select_profiles(args, parser, profile_names, default_profiles)
    if profile_policy is not None:
        profile_policy(args, parser)
    if not 16 <= args.max_observed_mib <= 512 or len(args.profiles) * args.max_observed_mib > 1024:
        parser.error("Observed budget must be 16 to 512 MiB per profile and at most 1024 MiB total.")
    if not args.label or len(args.label) > 80 or any(not 32 <= ord(c) <= 126 for c in args.label):
        parser.error("--label must contain 1 to 80 printable ASCII characters describing the actual vantage point.")
    try:
        filename = f"fastcom-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid4().hex[:8]}.json"
        args.output_root = output_root if output_root is not None else runtime_root()
        args.output = output_path(args.output or Path(".local/speed-tests") / filename, args.output_root)
    except (OSError, ValueError):
        parser.error("Output must be a new JSON file inside .local/speed-tests (no links or overwrite).")
    return args


def load_playwright():
    # Optional dependency: neither install packages nor download a bundled browser.
    from playwright.sync_api import sync_playwright
    return sync_playwright


def browser_path():
    from browser import browser_path as installed_browser
    return installed_browser()


def displayed_mbps(value, units):
    if units not in UNITS or not isinstance(value, str) or len(value) > 48:
        return None
    normalized = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in value.strip())
    normalized = normalized.replace("٫", ".")
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:[   ][0-9]{3})+)(?:[.,][0-9]+)?", normalized):
        return None
    number = float(re.sub(r"[   ]", "", normalized).replace(",", ".")) * UNITS[units]
    return number if math.isfinite(number) and number > 0 else None


def page_state(raw):
    # Never retain arbitrary DOM text, class names, page HTML, URLs, IPs or tokens.
    speed = displayed_mbps(raw.get("value"), raw.get("units"))
    state = {key: sorted(set(raw.get(key, [])) & CLASSES) for key in
             ("valueClasses", "resultClasses", "ancestorClasses", "progressClasses")}
    state.update(value=raw["value"] if speed is not None else None,
                 units=raw["units"] if raw.get("units") in UNITS else None,
                 progressPresent=raw.get("progressPresent") is True)
    all_classes = set().union(*(state[key] for key in
                              ("valueClasses", "resultClasses", "ancestorClasses", "progressClasses")))
    succeeded = "succeeded" in set(state["valueClasses"] + state["ancestorClasses"])
    completed = (speed is not None and succeeded and state["progressPresent"]
                 and not all_classes.intersection({"in-progress", "failed", "error"}))
    return state, speed, completed


def measure(playwright, executable, http_port, args):
    started = time.monotonic()
    deadline, limit = started + args.max_time, args.max_observed_mib * MIB
    result = {"startedUtc": utc_now(), "completed": False, "reason": "timeout",
              "finalMbps": None, "provisionalMbps": None, "page": None}
    decoded = encoded = 0
    stopped = budget_hit = False
    cdp = None

    def stop_network():
        nonlocal stopped
        if stopped:
            return
        stopped = True
        if cdp is not None:
            try:
                cdp.send("Network.emulateNetworkConditions", {"offline": True, "latency": 0,
                         "downloadThroughput": 0, "uploadThroughput": 0})
            except Exception:
                pass  # Context/browser closure is the fallback; never a strict wire-byte cap.

    def received(event):
        nonlocal decoded, encoded, budget_hit
        decoded += max(0, int(event.get("dataLength", 0)))
        encoded += max(0, int(event.get("encodedDataLength", 0)))
        if max(decoded, encoded) >= limit:
            budget_hit = True
            stop_network()  # Cancel in-flight traffic promptly, not browser.close() inside a callback.

    try:
        with ExitStack() as cleanup:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=not args.headed,
                      timeout=args.max_time * 1000, proxy={"server": f"http://127.0.0.1:{http_port}"},
                      args=["--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
            cleanup.callback(browser.close)
            context = browser.new_context(ignore_https_errors=False, service_workers="block")
            cleanup.callback(context.close)
            context.route("**/*", lambda route: route.abort() if stopped else route.continue_())
            page = context.new_page()
            cdp = context.new_cdp_session(page)
            cdp.on("Network.dataReceived", received)
            cdp.send("Network.enable")
            try:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    page.goto(URL, wait_until="domcontentloaded", timeout=max(1, int(remaining * 1000)))
                while time.monotonic() < deadline and not budget_hit:
                    state, speed, completed = page_state(page.evaluate(STATE_JS))
                    result.update(page=state, provisionalMbps=speed)
                    if budget_hit or time.monotonic() >= deadline:
                        break
                    if completed:
                        result.update(completed=True, reason="completed", finalMbps=speed, provisionalMbps=None)
                        break
                    page.wait_for_timeout(min(100, max(1, (deadline - time.monotonic()) * 1000)))
            except Exception as exc:
                if not budget_hit and type(exc).__name__ != "TimeoutError":
                    result.update(reason="browser_failed", errorClass=type(exc).__name__, completed=False, finalMbps=None)
            finally:
                stop_network()
    except KeyboardInterrupt:
        result.update(reason="interrupted", completed=False, finalMbps=None)
    except Exception as exc:
        result.update(reason="browser_failed", errorClass=type(exc).__name__, completed=False, finalMbps=None)
    finally:
        observed = max(decoded, encoded)
        if budget_hit and result["reason"] not in {"browser_failed", "interrupted"}:
            result.update(completed=False, reason="observed_budget", finalMbps=None)
        result.update(observedDecodedBytes=decoded, observedEncodedBytes=encoded, observedResponseBytes=observed,
                      observedOvershootBytes=max(0, observed - limit), elapsedSeconds=round(time.monotonic() - started, 3),
                      finishedUtc=utc_now())
    return result


def run_suite(args, playwright, executable):
    results = []
    for name in args.profiles:
        sample = {"profile": name, "startedUtc": utc_now(), "completed": False,
                  "reason": "client_failed", "finalMbps": None, "provisionalMbps": None}
        try:
            # Keep core-verification output and private exception messages off both output streams.
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                profile = load_profile(args.profiles_file, name)
                protocol = resolve_protocol(name, profile)
                core = resolve_core(protocol, None, None)
                socks_port, http_port = free_ports()
                config = build_config(name, profile, socks_port, http_port)
                with running_core(protocol, config, core, socks_port, http_port, 20):
                    sample.update(measure(playwright, executable, http_port, args))
        except KeyboardInterrupt:
            sample.update(completed=False, reason="interrupted", finalMbps=None)
        except Exception as exc:
            sample.update(completed=False, reason="client_failed", finalMbps=None, errorClass=type(exc).__name__)
        results.append(sample)
        if sample["reason"] in {"interrupted", "client_failed", "browser_failed"}:
            break  # No retry and no next client after uncertain setup/cleanup.
    return results


def main(argv=None, **options):
    args = parse_args(argv, **options)
    report = {"schemaVersion": 1, "startedUtc": utc_now(), "dryRun": args.dry_run,
              "method": "actual Fast.com browser page", "endpoint": URL, "profiles": args.profiles,
              "observationPoint": {"label": args.label, "os": platform.system(), "architecture": platform.machine()},
              "headless": not args.headed, "maxTimeSeconds": args.max_time,
              "maxObservedBytesPerProfile": args.max_observed_mib * MIB,
              "totalSelectedObservedBudgetBytes": len(args.profiles) * args.max_observed_mib * MIB if args.profiles else None,
              "order": "sequential; fresh client and isolated browser per profile", "results": [],
              "limitations": ["Only this actual machine/network through the selected proxy; not phone, Mac or China-route evidence unless run there.",
                              "CDP dataReceived counts decoded and encoded response bodies separately; budget uses their maximum, not their sum.",
                              "Observed bytes are not billing or wire bytes: exclude headers, uploads, TLS/VPN overhead, retransmissions and unseen browser traffic.",
                              "Best-effort offline cancellation and browser closure can overshoot; event delivery and in-flight traffic prevent a strict transfer cap.",
                              "No retries by this runner; Fast.com controls its own requests. Timeout includes launch/navigation, excludes client setup/cleanup.",
                              "Only a positive page completion state with recognized units is final; capped, timed-out and progressing readings are provisional."]}
    if not args.profiles:
        report["profileSelection"] = "Pass --profiles for a concrete dry-run budget; execution defaults to configured entries."
    code = 0
    if not args.dry_run:
        try:
            factory = load_playwright()
        except ImportError:
            report["error"] = "Optional Playwright is missing; install requirements-fast-com.txt in the ignored .venv. No automatic install or browser download."
            code = 1
        else:
            try:
                executable = browser_path()
                with factory() as playwright:
                    report["results"] = run_suite(args, playwright, executable)
            except KeyboardInterrupt:
                report["error"] = "interrupted"
            except Exception as exc:
                report.update(error="Browser/runtime unavailable or cleanup failed; install Chrome or Edge locally if absent.", errorClass=type(exc).__name__)
            code = 0 if (not report.get("error") and len(report["results"]) == len(args.profiles)
                         and all(item["completed"] for item in report["results"])) else 1
    report.update(finishedUtc=utc_now(), exitCode=code)
    if not args.dry_run:
        try:
            destination = output_path(args.output, args.output_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.write("\n")
        except (OSError, ValueError):
            report["outputError"] = "Could not save result; destination must be new and inside .local/speed-tests."
            code = report["exitCode"] = 1
    print(json.dumps(report, indent=2, allow_nan=False))
    if not args.dry_run:
        print("Profile   Result             Final Mbps  Provisional Mbps", file=sys.stderr)
        for item in report["results"]:
            final = f"{item['finalMbps']:.3f}" if item["completed"] else "-"
            provisional = f"{item['provisionalMbps']:.3f}" if item["provisionalMbps"] is not None else "-"
            print(f"{item['profile']:<9} {item['reason']:<18} {final:>10}  {provisional:>16}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
