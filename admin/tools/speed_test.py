#!/usr/bin/env python3
"""Bounded sequential HTTPS download comparison; never changes VPN servers or routing."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "clients"))
from core_install import resolve_core
from vpn import build_config, load_profile, profile_names, resolve_protocol, running_core
from vpn_common import default_profiles_file
from speed_common import free_ports, select_profiles, output_path as checked_output_path, runtime_root, utc_now

URL = "https://proof.ovh.net/files/10Mb.dat"
DOWNLOAD_BYTES = 10 * 1024 * 1024
MAX_BUDGET = 200 * 1024 * 1024
BINARY_TYPES = {"application/octet-stream", "application/x-binary", "binary/octet-stream", "application/x-download"}


def output_path(value: Path | None, root: Path | None = None) -> Path | None:
    return checked_output_path(value, root if root is not None else runtime_root())


def parse_args(argv=None, *, profiles_file=None, output_root=None, default_profiles=None, parser_setup=None, profile_policy=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", nargs="+", help="Configured profile IDs; execution defaults to all configured entries.")
    parser.add_argument("--profiles-file", type=Path, default=profiles_file if profiles_file is not None else default_profiles_file(),
                        help="Private bundle for another deployment; existing profiles are never replaced.")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--bytes", type=int, default=DOWNLOAD_BYTES, help="Fixed endpoint: only 10485760 bytes supported.")
    parser.add_argument("--max-time", type=int, default=20, help="Per download timeout, 1 to 30 seconds.")
    parser.add_argument("--label", default="unspecified", help="Observation point, printable ASCII, at most 80 characters; omit private identifiers.")
    parser.add_argument("--output", type=Path, help="New .local/speed-tests/<name>.json; stdout always contains JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print budget only; no profiles, cores, files or network.")
    if parser_setup is not None:
        parser_setup(parser)
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 5:
        parser.error("--rounds must be between 1 and 5.")
    if args.bytes != DOWNLOAD_BYTES:
        parser.error("--bytes must be 10485760 for the fixed OVH endpoint.")
    if not 1 <= args.max_time <= 30:
        parser.error("--max-time must be between 1 and 30 seconds.")
    select_profiles(args, parser, profile_names, default_profiles)
    if profile_policy is not None:
        profile_policy(args, parser)
    if not args.label or len(args.label) > 80 or any(not 32 <= ord(char) <= 126 for char in args.label):
        parser.error("--label must contain 1 to 80 printable ASCII characters.")
    if len(args.profiles) * args.rounds * args.bytes > MAX_BUDGET:
        parser.error("Requested download payload exceeds the 200 MiB budget.")
    try:
        args.output_root = output_root
        args.output = output_path(args.output, output_root)
    except (OSError, ValueError):
        parser.error("Output must be a new JSON file inside .local/speed-tests (no links or overwrite).")
    return args


def find_curl() -> str:
    executable = shutil.which("curl.exe" if os.name == "nt" else "curl")
    if not executable:
        raise RuntimeError("curl unavailable")
    result = subprocess.run([executable, "--disable", "--version"], capture_output=True, text=True, timeout=5)
    version = re.match(r"curl (\d+)\.(\d+)\.(\d+)\b", result.stdout)
    # Older curl only enforces max-filesize when Content-Length is known.
    if result.returncode or not version or tuple(map(int, version.groups())) < (8, 4, 0):
        raise RuntimeError("curl 8.4.0 or newer required")
    return executable


def transfer(curl: str, http_port: int, max_time: int) -> dict:
    result = {"startedUtc": utc_now(), "complete": False, "reason": "invalid_metrics",
              "httpStatus": None, "curlExit": None, "bytes": None, "curlSeconds": None,
              "ttfbSeconds": None, "curlBytesPerSecond": None, "mbps": None, "partialMbps": None}
    command = [curl, "--disable", "--silent", "--show-error", "--proxy", f"http://127.0.0.1:{http_port}",
               "--noproxy", "", "--proto", "=https", "--connect-timeout", "5", "--max-time", str(max_time),
               "--max-filesize", str(DOWNLOAD_BYTES), "--retry", "0", "--header", "Accept-Encoding: identity",
               "--output", os.devnull, "--write-out", "%{json}", "--url", URL]
    started = time.monotonic()
    try:
        response = subprocess.run(command, capture_output=True, text=True, timeout=max_time + 5)
        result["curlExit"] = response.returncode
        data = json.loads(response.stdout)
        code, size = int(data["http_code"]), float(data["size_download"])
        seconds, speed, ttfb = (float(data[key]) for key in ("time_total", "speed_download", "time_starttransfer"))
        if (not 0 <= code <= 599 or not all(math.isfinite(item) and item >= 0 for item in (size, seconds, speed, ttfb))
                or not size.is_integer() or size > DOWNLOAD_BYTES or ttfb > seconds or (size > 0 and seconds == 0)):
            raise ValueError
        binary = str(data.get("content_type", "")).split(";", 1)[0].strip().lower() in BINARY_TYPES
        result.update(httpStatus=code, bytes=int(size), curlSeconds=seconds, ttfbSeconds=ttfb,
                      curlBytesPerSecond=speed)
        good = response.returncode == 0 and code == 200 and size == DOWNLOAD_BYTES and binary
        result["complete"] = good
        result["reason"] = ("complete" if good else "http_error" if code not in (0, 200) else
                            "unexpected_content" if code == 200 and not binary else
                            "timeout" if response.returncode == 28 else "curl_failed" if response.returncode else
                            "http_error" if code != 200 else "incomplete_length")
        if good:
            result["mbps"] = round(size * 8 / seconds / 1_000_000, 3)
        elif code == 200 and binary and 0 < size < DOWNLOAD_BYTES:
            result["partialMbps"] = round(size * 8 / seconds / 1_000_000, 3)
    except subprocess.TimeoutExpired:
        result["reason"] = "process_timeout"
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    except OSError:
        result["reason"] = "curl_unavailable"
    finally:
        result["elapsedSeconds"] = round(time.monotonic() - started, 3)
    return result


def summarize(profiles: list[str], results: list[dict]) -> dict:
    summary = {}
    for name in profiles:
        samples = [item for item in results if item["profile"] == name]
        speeds = [item["mbps"] for item in samples if item["complete"]]
        summary[name] = {"validRounds": len(speeds), "attemptedRounds": len(samples),
                         "medianMbps": round(statistics.median(speeds), 3) if speeds else None,
                         "minMbps": min(speeds) if speeds else None, "maxMbps": max(speeds) if speeds else None}
    return summary


def run_suite(args, curl: str) -> tuple[list[dict], bool]:
    results = []
    for round_number in range(1, args.rounds + 1):
        for name in args.profiles:
            sample = {"profile": name, "round": round_number, "startedUtc": utc_now(),
                      "complete": False, "reason": "client_failed", "mbps": None, "partialMbps": None}
            try:
                # Core verification may print a message; keep stdout JSON-only.
                with redirect_stdout(io.StringIO()):
                    profile = load_profile(args.profiles_file, name)
                    protocol = resolve_protocol(name, profile)
                    core = resolve_core(protocol, None, None)
                socks_port, http_port = free_ports()
                config = build_config(name, profile, socks_port, http_port)
                with running_core(protocol, config, core, socks_port, http_port, 20):
                    sample.update(transfer(curl, http_port, args.max_time))
            except KeyboardInterrupt:
                sample.update(complete=False, reason="interrupted", mbps=None, partialMbps=None)
                results.append(sample)
                return results, True
            except Exception:
                # Stop the suite on core/setup/cleanup failures; never print raw errors or continue with uncertain cleanup.
                sample.update(complete=False, reason="client_failed", mbps=None, partialMbps=None)
                results.append(sample)
                return results, False
            results.append(sample)
            if sample["reason"] in {"http_error", "unexpected_content", "incomplete_length", "invalid_metrics"}:
                # A refused or changed endpoint is not a speed measurement; do not repeat it.
                return results, False
    return results, False


def main(argv=None, *, profiles_file=None, output_root=None, default_profiles=None, parser_setup=None, profile_policy=None) -> int:
    # Dispatch before parsing backend options; file/help never imports Playwright.
    argv = list(sys.argv[1:] if argv is None else argv)
    method_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    method_parser.add_argument("--method", choices=("file", "fast"))
    leading = argv.pop(0) if argv and argv[0] in {"file", "fast"} else None
    selected, remaining = method_parser.parse_known_args(argv)
    if leading and selected.method and leading != selected.method:
        method_parser.error("Leading method conflicts with --method.")
    method = selected.method or leading or "file"
    options = dict(profiles_file=profiles_file, output_root=output_root, default_profiles=default_profiles,
                   parser_setup=parser_setup, profile_policy=profile_policy)
    if method == "fast":
        # Resolve alongside this file, not a same-named private compatibility wrapper.
        import importlib.util
        spec = importlib.util.spec_from_file_location("_toolkit_fast_com", Path(__file__).with_name("fast_com_test.py"))
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        return backend.main(remaining, **options)
    if "--help" in remaining or "-h" in remaining:
        print("Methods: file (default) or fast; select with a leading method or --method file|fast.")
    return file_main(remaining, **options)


def file_main(argv=None, **options) -> int:
    args = parse_args(argv, **options)
    report = {"schemaVersion": 1, "startedUtc": utc_now(), "dryRun": args.dry_run,
              "observationPoint": {"label": args.label, "os": platform.system(), "architecture": platform.machine()},
              "profiles": args.profiles, "rounds": args.rounds, "endpoint": URL, "bytesPerRequest": args.bytes,
              "payloadBudgetBytes": args.bytes * args.rounds * len(args.profiles) if args.profiles else None,
              "maxTimeSeconds": args.max_time,
              "order": "sequential round-robin; fresh client per sample", "results": [],
              "limitations": ["Current machine to this endpoint through the selected proxy only; not full-device or phone/China-route speed.",
                              "Payload budget excludes TLS, VPN and retransmission overhead. No retries, redirects or fallback endpoints.",
                              "Partial throughput is not a completed test; summaries use complete downloads only.",
                              "Fresh client setup is outside curl timing; request timing includes its connection/handshake wait.",
                              "Rates alone do not identify throttling, GFW, congestion or server load."]}
    if not args.profiles:
        report["profileSelection"] = "Pass --profiles for a concrete dry-run budget; execution defaults to configured entries."
    code = 0
    if not args.dry_run:
        try:
            curl = find_curl()
        except (OSError, RuntimeError, subprocess.SubprocessError):
            report["error"] = "curl 8.4.0+ must be installed and usable; no profiles loaded or network attempted."
            code = 1
        else:
            report["results"], interrupted = run_suite(args, curl)
            report["summary"] = summarize(args.profiles, report["results"])
            complete = (len(report["results"]) == args.rounds * len(args.profiles)
                        and all(item["complete"] for item in report["results"]))
            code = 130 if interrupted else 0 if complete else 1
    report["finishedUtc"] = utc_now()
    report["exitCode"] = code
    if args.output is not None and not args.dry_run:
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
        print("Profile   Round  Result                Mbps (completed only)", file=sys.stderr)
        for item in report["results"]:
            speed = f"{item['mbps']:.3f}" if item["complete"] else "-"
            print(f"{item['profile']:<9} {item['round']:>5}  {item['reason']:<21} {speed}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
