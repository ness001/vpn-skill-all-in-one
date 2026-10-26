#!/usr/bin/env python3
"""Read-only local-on-server or Azure VPN diagnostics with explicit configuration."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("guest_diagnostics.sh")
MARKER = "VPN_DIAGNOSTICS="


class DiagnosticError(Exception):
    pass


def load_config(path, mode="azure"):
    """Validate configuration before CLI lookup or guest execution."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        required = {"services"}
        if mode == "azure":
            required.update(("subscription", "resourceGroup", "vm"))
        optional = {"guestPython", "logDirectories", "historicalLog", "cpuCredits"}
        if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - optional:
            raise ValueError
        if mode == "azure":
            if not isinstance(data["subscription"], str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", data["subscription"]):
                raise ValueError
            for key in ("resourceGroup", "vm"):
                if not isinstance(data[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,89}", data[key]):
                    raise ValueError
        services = data["services"]
        if not isinstance(services, list) or not 1 <= len(services) <= 3:
            raise ValueError
        for row in services:
            if not isinstance(row, dict) or set(row) != {"unit", "port", "transport"}:
                raise ValueError
            if not isinstance(row["unit"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,95}\.service", row["unit"]):
                raise ValueError
            if type(row["port"]) is not int or not 1 <= row["port"] <= 65535 or row["transport"] not in ("tcp", "udp"):
                raise ValueError
        if len({row["unit"] for row in services}) != len(services):
            raise ValueError
        data.setdefault("guestPython", "/usr/bin/python3")
        data.setdefault("logDirectories", {})
        data.setdefault("historicalLog", None)
        data.setdefault("cpuCredits", False)
        if type(data["cpuCredits"]) is not bool:
            raise ValueError
        logs = data["logDirectories"]
        if not isinstance(logs, dict) or set(logs) - {"vless", "hy2"}:
            raise ValueError
        for value in [data["guestPython"]] + list(logs.values()) + ([data["historicalLog"]] if data["historicalLog"] is not None else []):
            if not isinstance(value, str) or len(value) > 240 or not value.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or any(part in (".", "..", "") for part in value.split("/")[1:]):
                raise ValueError
        return data
    except (OSError, ValueError, TypeError, KeyError):
        raise DiagnosticError("invalid_or_missing_target_config") from None


def runtime_root():
    return Path.home() / ".cache" / "vpn-skill" / "runtime"


def output_path(value, root=None):
    root = runtime_root() if root is None else root
    if value is None:
        return None
    allowed = root / ".local" / "diagnostics"
    path = value if value.is_absolute() else root / value
    if (path.exists() or path.is_symlink() or path.resolve().parent != allowed
            or any(p.is_symlink() for p in (root / ".local", allowed))
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.json", path.name)):
        raise ValueError("Output must be a new .local/diagnostics/<name>.json (no links or overwrite).")
    return path.resolve()


def parse_args(argv=None, root=None, default_config=None, default_mode=None):
    root = runtime_root() if root is None else root
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--mode", choices=("local", "azure"), default=default_mode, required=default_mode is None,
                        help="local: run on this server; azure: explicit subscription/VM via existing Azure CLI.")
    parser.add_argument("--config", type=Path, default=default_config, required=default_config is None, help="Private JSON service/log settings; Azure mode also requires explicit target IDs.")
    parser.add_argument("--minutes", type=int, default=30, help="Requested rolling-log and metric window: 1..30 minutes.")
    parser.add_argument("--logs-only", action="store_true", help="Skip Azure Monitor CPU/credit metrics; retain guest service/resource checks.")
    parser.add_argument("--dry-run", action="store_true", help="Validate explicit service/log configuration and print scope; no network or guest execution.")
    parser.add_argument("--output", type=Path, help="New .local/diagnostics/<name>.json; stdout always contains sanitized JSON.")
    args = parser.parse_args(argv)
    if not 1 <= args.minutes <= 30:
        parser.error("--minutes must be between 1 and 30.")
    try:
        args.output = output_path(args.output, root)
    except (ValueError, OSError):
        parser.error("Output must be a new .local/diagnostics/<name>.json (no links or overwrite).")
    try:
        args.config = load_config(args.config, args.mode)
    except DiagnosticError:
        parser.error("invalid_or_missing_target_config")
    return args


def azure(az, arguments, config, timeout=120):
    try:
        result = subprocess.run([az] + arguments + ["--subscription", config["subscription"],
                                "--only-show-errors", "--output", "json"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise DiagnosticError("azure_cli_unavailable_or_timeout") from None
    if result.returncode:
        # Azure/PowerShell stderr can contain account information or echoed guest text.
        raise DiagnosticError("azure_cli_failed_check_existing_login_and_access")
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise DiagnosticError("azure_cli_invalid_json") from None
    if not isinstance(data, dict):
        raise DiagnosticError("azure_cli_invalid_response")
    return data


def _require(condition):
    if not condition:
        raise DiagnosticError("guest_summary_invalid_schema")


def _fields(value, required, optional=()):
    _require(isinstance(value, dict) and set(required) <= set(value)
             and set(value) <= set(required) | set(optional))


def _count(value, maximum=None):
    _require(type(value) is int and value >= 0 and (maximum is None or value <= maximum))


def _timestamp(value, nullable=False):
    if value is None and nullable:
        return
    _require(isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value))
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise DiagnosticError("guest_summary_invalid_schema") from None


def _counts(value, allowed):
    _fields(value, (), allowed)
    for count in value.values():
        _count(count)


def validate_guest(data, config):
    # Treat Run Command output as data: no free-text field reaches stdout or disk.
    _fields(data, ("schema", "status", "utc", "requestedSinceUtc", "bucketSeconds",
                   "logs", "services", "resources", "historicalLog"), ("summaryTruncated",))
    _require(type(data["schema"]) is int and data["schema"] == 1)
    _require(data["status"] in ("observations_only", "incomplete"))
    _require(type(data["bucketSeconds"]) is int and data["bucketSeconds"] == 10)
    _timestamp(data["utc"])
    _timestamp(data["requestedSinceUtc"])
    complete = data["status"] == "observations_only"
    truncated = "summaryTruncated" in data
    if truncated:
        _require(data["summaryTruncated"] is True and not complete)
    _fields(data["logs"], ("vless", "hy2"))
    details = ("severity", "warningCauses", "rejected")
    for log in data["logs"].values():
        if isinstance(log, dict) and "error" in log:
            _fields(log, ("error",))
            _require(not complete and log["error"] in ("logs_unavailable_or_unsafe", "log_support_not_configured"))
            continue
        counts = ("files", "eligibleFiles", "agedOutSkipped", "bytesOnDisk", "sampledBytes",
                  "unparsed", "resetPublicDestinations", "rejectedOmitted")
        flags = ("privateModes", "scanComplete", "windowStartCovered", "resetPublicCountCapped")
        _fields(log, counts + flags + ("oldestBucketUtc", "newestWriteUtc", "resetOperations")
                + (() if truncated else details), details if truncated else ())
        for key in counts:
            _count(log[key])
        for key in flags:
            _require(type(log[key]) is bool)
        for key in ("oldestBucketUtc", "newestWriteUtc"):
            _timestamp(log[key], nullable=True)
        _require(not complete or (log["scanComplete"] and log["privateModes"] and log["unparsed"] == 0))
        if "severity" in log:
            _counts(log["severity"], ("debug", "info", "warning", "warn", "error", "fatal", "unknown", "other"))
        if "warningCauses" in log:
            _counts(log["warningCauses"], ("reset", "rejected", "idle", "timeout", "deadline", "refused",
                                          "unreachable", "no_route", "broken_pipe", "auth", "cancelled", "eof", "other"))
        _counts(log["resetOperations"], ("write", "read", "dial", "unknown"))
        if "rejected" in log:
            _require(isinstance(log["rejected"], list) and len(log["rejected"]) <= 6)
            for row in log["rejected"]:
                _fields(row, ("class", "port", "count"))
                _require(row["class"] in ("unknown", "hostname", "loopback", "unspecified", "private",
                                          "link_local", "multicast", "public_ipv6", "reserved", "shared",
                                          "fake_ip", "azure_platform", "public_ipv4"))
                _count(row["port"], 65535)
                _count(row["count"])
    services = data["services"]
    if isinstance(services, dict):
        _fields(services, ("error",))
        _require(not complete and services["error"] == "read_failed")
    else:
        _require(isinstance(services, list) and len(services) == len(config["services"]))
        for row, expected in zip(services, config["services"]):
            unit, port, transport = expected["unit"], expected["port"], expected["transport"]
            _fields(row, ("unit", "active", "mainPid", "children", "port", "transport", "listener", "owned"))
            _require(row["unit"] == unit and row["transport"] == transport)
            _count(row["port"], 65535)
            _require(row["port"] == port)
            _count(row["mainPid"])
            _require(isinstance(row["children"], list) and len(row["children"]) <= 8)
            for pid in row["children"]:
                _count(pid)
            for key in ("active", "listener", "owned"):
                _require(type(row[key]) is bool and (not complete or row[key]))
    resources = data["resources"]
    if isinstance(resources, dict) and "error" in resources:
        _fields(resources, ("error",))
        _require(not complete and resources["error"] == "read_failed")
    else:
        _fields(resources, ("memory", "logDiskFreeMiB", "udpCountersSinceBootNotWindow"))
        _fields(resources["memory"], ("MemTotalKiB", "MemFreeKiB"), ("MemAvailableKiB",))
        for value in resources["memory"].values():
            _count(value)
        _count(resources["logDiskFreeMiB"])
        _counts(resources["udpCountersSinceBootNotWindow"], ("InErrors", "RcvbufErrors", "SndbufErrors", "NoPorts"))
    historical = data["historicalLog"]
    _require(isinstance(historical, dict))
    if "present" in historical:
        _fields(historical, ("present", "scanned"))
        _require(historical["present"] is False)
    else:
        _fields(historical, ("bytes", "mtimeUtc", "privateRegularFile", "scanned"))
        _count(historical["bytes"])
        _timestamp(historical["mtimeUtc"])
        _require(type(historical["privateRegularFile"]) is bool)
    _require(historical["scanned"] is False)


def parse_guest(response, config):
    markers = []
    if not isinstance(response, dict) or not isinstance(response.get("value"), list):
        raise DiagnosticError("guest_invalid_envelope")
    for entry in response["value"]:
        if not isinstance(entry, dict):
            raise DiagnosticError("guest_invalid_envelope")
        code = entry.get("code", "")
        if "failed" in str(code).lower() or str(entry.get("level", "")).lower() == "error":
            raise DiagnosticError("guest_command_failed")
        message = entry.get("message", "")
        if not isinstance(message, str):
            raise DiagnosticError("guest_invalid_envelope")
        markers.extend(line[len(MARKER):] for line in message.splitlines() if line.startswith(MARKER))
    if len(markers) != 1 or len(markers[0].encode("utf-8")) > 3000:
        raise DiagnosticError("guest_summary_missing_duplicate_or_truncated")
    try:
        data = json.loads(markers[0])
    except ValueError:
        raise DiagnosticError("guest_summary_invalid_json") from None
    validate_guest(data, config)
    return data


def render_guest(config, minutes):
    if type(minutes) is not int or not 1 <= minutes <= 30:
        raise DiagnosticError("invalid_minutes")
    source = SCRIPT.read_text(encoding="utf-8")
    substitutions = {"__WINDOW_MINUTES__": str(minutes), "__GUEST_PYTHON__": config["guestPython"],
                     "__GUEST_CONFIG_BASE64__": base64.b64encode(json.dumps({key: config[key] for key in
                         ("services", "logDirectories", "historicalLog")}).encode("utf-8")).decode("ascii")}
    for marker, value in substitutions.items():
        if source.count(marker) != 1:
            raise DiagnosticError("invalid_guest_template")
        source = source.replace(marker, value)
    return source


def guest(az, minutes, config):
    # Only validated paths and base64 JSON enter the shell/Python template.
    source = render_guest(config, minutes)
    with tempfile.TemporaryDirectory(prefix="vpn-diagnostics-") as directory:
        script = Path(directory) / "guest-diagnostics.sh"
        script.write_text(source, encoding="utf-8", newline="\n")
        response = azure(az, ["vm", "run-command", "invoke", "--resource-group", config["resourceGroup"], "--name", config["vm"],
                             "--command-id", "RunShellScript", "--scripts", "@" + str(script)], config, timeout=600)
    return parse_guest(response, config)


def local_guest(minutes, config):
    # No sudo, Azure CLI, SSH or service changes. Missing permissions become
    # incomplete collector sections, using exactly the Azure guest schema.
    try:
        response = subprocess.run(["/bin/sh"], input=render_guest(config, minutes),
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise DiagnosticError("local_collector_unavailable_or_timeout") from None
    if response.returncode:
        raise DiagnosticError("local_collector_failed_check_python_and_read_permissions")
    return parse_guest({"value": [{"message": response.stdout}]}, config)


def metrics(az, minutes, config):
    end = datetime.now(timezone.utc)
    stamp = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
    resource = f"/subscriptions/{config['subscription']}/resourceGroups/{config['resourceGroup']}/providers/Microsoft.Compute/virtualMachines/{config['vm']}"
    metric_names = ["Percentage CPU"] + (["CPU Credits Remaining"] if config["cpuCredits"] else [])
    response = azure(az, ["monitor", "metrics", "list", "--resource", resource,
                         "--metrics"] + metric_names + ["--interval", "PT5M",
                         "--aggregation", "Average", "--start-time", stamp(end - timedelta(minutes=minutes)),
                         "--end-time", stamp(end)], config)
    result = {"intervalSeconds": 300, "cpu": None, "creditsRemaining": None, "creditsRequested": config["cpuCredits"]}
    names = {"Percentage CPU": "cpu"}
    if config["cpuCredits"]:
        names["CPU Credits Remaining"] = "creditsRemaining"
    for metric in response.get("value", []):
        key = names.get(metric.get("name", {}).get("value"))
        if not key:
            continue
        bins = []
        for series in metric.get("timeseries", []):
            for row in series.get("data", []):
                value, timestamp = row.get("average"), row.get("timeStamp", "")
                if (type(value) in (int, float) and math.isfinite(value) and value >= 0
                        and re.fullmatch(r"[0-9T:.+Z-]{19,35}", timestamp)):
                    bins.append((timestamp, value))
        if bins:
            bins.sort()
            values = [row[1] for row in bins]
            result[key] = {"bins": len(bins), "latestUtc": bins[-1][0], "latestBinAverage": bins[-1][1],
                           "meanBinAverage": round(sum(values) / len(values), 3), "peakBinAverage": max(values)}
    result["status"] = "available" if all(result[key] is not None for key in names.values()) else "incomplete"
    return result


def main(argv=None, *, root=None, default_config=None, default_mode=None):
    root = runtime_root() if root is None else root
    args = parse_args(argv, root, default_config, default_mode)
    config = args.config
    local = args.mode == "local"
    result = {"mode": args.mode,
              "target": {"scope": "this_server"} if local else
                        {key: config[key] for key in ("subscription", "resourceGroup", "vm")},
              "minutes": args.minutes, "readOnly": True, "authenticatedForwardingTested": False}
    if args.dry_run:
        result.update(status="dry_run", guestRunCommands=0 if local else 1,
                      localCollectors=1 if local else 0, monitorQueries=0 if local or args.logs_only else 1,
                      logLimits={"filesPerProtocol": 2048, "bytesPerProtocol": 32 * 1024 * 1024,
                                 "partialLineBytes": 65536, "guestSummaryBytes": 3000})
    else:
        result["status"] = "incomplete"
        try:
            if local:
                result["metrics"] = {"status": "unavailable", "reason": "azure_monitor_not_used_in_local_mode",
                                     "cpu": None, "creditsRemaining": None}
                result["guest"] = local_guest(args.minutes, config)
            else:
                az = shutil.which("az")
                if not az:
                    raise DiagnosticError("azure_cli_not_installed")
                for key, reader in (("guest", guest), ("metrics", metrics)):
                    if key == "metrics" and args.logs_only:
                        result[key] = {"status": "skipped"}
                        continue
                    try:
                        result[key] = reader(az, args.minutes, config)
                    except DiagnosticError as exc:
                        result["error"] = str(exc)
                    except Exception:
                        result["error"] = "diagnostic_collection_failed"
            if ("error" not in result and result["guest"]["status"] == "observations_only"
                    and result["metrics"]["status"] != "incomplete"):
                result["status"] = "observations_only"
        except DiagnosticError as exc:
            result["error"] = str(exc)
        except Exception:
            result["error"] = "diagnostic_collection_failed"
        if args.output:
            try:
                path = output_path(args.output, root)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as handle:
                    json.dump(result, handle, indent=2, sort_keys=True)
                    handle.write("\n")
            except (OSError, ValueError):
                result.update(status="incomplete", error="output_write_failed")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["status"] == "incomplete" else 0


if __name__ == "__main__":
    raise SystemExit(main())
