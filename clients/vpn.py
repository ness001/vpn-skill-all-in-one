#!/usr/bin/env python3
"""Foreground, loopback-only clients for configured VLESS and Hysteria2 profiles."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
from subprocess import Popen
import sys
import time
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
import uuid

from core_install import fetch_core, resolve_core
from vpn_common import (
    ClientError, MAX_CONFIG_BYTES, ROOT, ensure_private_export_parent, limited_read,
    default_profiles_file, private_directory, private_write,
)

BIND = "127.0.0.1"
PROTOCOL_NAMES = ("vless", "hysteria2")


def profile_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ClientError("Profile identifiers must use 1-64 letters, digits, underscores or hyphens, starting with a letter or digit.")
    return value


def resolve_protocol(name: str, profile: dict | None = None) -> str:
    """Resolve an explicit protocol independently of the profile identity."""
    profile_id(name)
    protocol = profile.get("protocol") if profile is not None else None
    if protocol is None:
        protocol = name if profile is None and name in PROTOCOL_NAMES else None
    if protocol not in PROTOCOL_NAMES:
        raise ClientError("Profile requires protocol vless or hysteria2.")
    return protocol


def profile_label(name: str, profile: dict) -> str:
    protocol = resolve_protocol(name, profile)
    return f"{profile_id(name)} ({'VLESS' if protocol == 'vless' else 'Hysteria2'})"


def text(value, field: str, maximum: int = 4096) -> str:
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ClientError(f"Invalid profile field: {field}.")
    return value


def host(value, field: str) -> str:
    value = text(value, field, 253)
    try:
        return str(ipaddress.ip_address(value.strip("[]")))
    except ValueError:
        if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for char in value):
            raise ClientError(f"Invalid profile field: {field}.")
        labels = value.rstrip(".").split(".")
        if any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-") for part in labels):
            raise ClientError(f"Invalid profile field: {field}.")
        return value


def port(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ClientError("Ports must be integers between 1 and 65535.")
    return value


def load_profiles(bundle: Path, *, normalize=None) -> dict[str, dict]:
    try:
        data = json.loads(limited_read(bundle.expanduser(), MAX_CONFIG_BYTES))
    except OSError:
        raise ClientError("Cannot read the shared profile bundle; check profiles/vpn-profiles.json or --profiles-file.") from None
    except (ValueError, UnicodeError):
        raise ClientError("Invalid profile bundle JSON; credential details are suppressed.") from None
    if (not isinstance(data, dict) or type(data.get("schemaVersion")) is not int
            or data["schemaVersion"] != 1):
        raise ClientError("Unsupported profile bundle schema.")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        raise ClientError("Invalid profile map in the shared bundle.")
    if normalize is not None:
        profiles = normalize(profiles)
    for name, profile in profiles.items():
        profile_id(name)
        if not isinstance(profile, dict):
            raise ClientError("Invalid profile entry in the shared bundle.")
        if profile.get("name") != name:
            raise ClientError("Profile name does not match its bundle entry.")
        resolve_protocol(name, profile)
    return profiles


def profile_names(bundle: Path) -> tuple[str, ...]:
    """Return configured IDs in bundle order."""
    return tuple(load_profiles(bundle))


def load_profile(bundle: Path, name: str, *, optional: bool = False) -> dict | None:
    profile_id(name)
    profiles = load_profiles(bundle)
    if name not in profiles:
        if optional:
            return None
        raise ClientError("The requested profile is not configured in the shared bundle.")
    return profiles[name]


def xray_config(profile: dict, socks_port: int, http_port: int) -> dict:
    if (profile.get("protocol") != "vless" or profile.get("network") != "ws"
            or profile.get("tls") is not True or profile.get("allowInsecure", False) is not False):
        raise ClientError("VLESS profile requires VLESS over WebSocket with verified TLS.")
    if profile.get("flow", "") != "":
        raise ClientError("VLESS WebSocket profiles must have an empty flow.")
    try:
        identity = str(uuid.UUID(profile["uuid"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ClientError("VLESS profile requires a valid authenticated VLESS UUID.") from None
    ws_path = text(profile.get("wsPath"), "wsPath")
    if not ws_path.startswith("/"):
        raise ClientError("WebSocket path must start with a slash.")
    return {
        "log": {"loglevel": "none"},
        "inbounds": [
            {"tag": "socks", "listen": BIND, "port": port(socks_port), "protocol": "socks",
             "settings": {"auth": "noauth", "udp": True, "ip": BIND}},
            {"tag": "http", "listen": BIND, "port": port(http_port), "protocol": "http",
             "settings": {}},
        ],
        "outbounds": [{
            "tag": "vpn", "protocol": "vless", "settings": {"vnext": [{
                "address": host(profile.get("server"), "server"), "port": port(profile.get("port")),
                "users": [{"id": identity, "encryption": "none"}],
            }]},
            "streamSettings": {
                "network": "ws", "security": "tls",
                "tlsSettings": {"serverName": host(profile.get("sni"), "sni"), "allowInsecure": False},
                "wsSettings": {"path": ws_path, "headers": {"Host": host(profile.get("wsHost"), "wsHost")}},
            },
        }],
    }


def hysteria_config(profile: dict, socks_port: int, http_port: int) -> dict:
    uri = text(profile.get("uri"), "uri", 16384)
    try:
        parsed = urlsplit(uri)
        if parsed.scheme not in ("hysteria2", "hy2") or parsed.path not in ("", "/"):
            raise ValueError
        server = host(parsed.hostname, "server")
        server_port = port(parsed.port if parsed.port is not None else 443)
        if parsed.username is None:
            raise ValueError
        auth = unquote(parsed.username)
        if parsed.password is not None:
            auth += ":" + unquote(parsed.password)
        auth = text(auth, "auth")
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
    except (ValueError, TypeError):
        raise ClientError("Hysteria profile requires a valid authenticated Hysteria 2 URI.") from None
    supported = {"sni", "insecure", "alpn", "obfs", "obfs-password"}
    if set(query) - supported or any(len(values) != 1 for values in query.values()):
        raise ClientError("Unsupported or duplicate Hysteria URI option; review the shared profile.")
    options = {key: values[0] for key, values in query.items()}
    if options.get("insecure", "0").lower() not in ("0", "false"):
        raise ClientError("Hysteria profile must verify TLS; insecure mode is not supported.")
    if options.get("alpn", "h3") != "h3":
        raise ClientError("Hysteria 2 requires the h3 ALPN.")
    if "obfs-password" in options and options.get("obfs") != "salamander":
        raise ClientError("Obfuscation password requires the salamander mode.")
    authority = f"[{server}]" if ":" in server else server
    config = {
        "server": f"{authority}:{server_port}", "auth": auth,
        "tls": {"sni": host(options.get("sni", server), "sni"), "insecure": False},
        "socks5": {"listen": f"{BIND}:{port(socks_port)}"},
        "http": {"listen": f"{BIND}:{port(http_port)}"},
    }
    if "obfs" in options:
        if options["obfs"] != "salamander":
            raise ClientError("Unsupported Hysteria obfuscation mode.")
        config["obfs"] = {"type": "salamander", "salamander": {
            "password": text(options.get("obfs-password"), "obfs-password"),
        }}
    return config


def build_config(name: str, profile: dict, socks_port: int, http_port: int) -> dict:
    protocol = resolve_protocol(name, profile)
    port(socks_port)
    port(http_port)
    if socks_port == http_port:
        raise ClientError("SOCKS and HTTP proxies require different ports.")
    return xray_config({**profile, "protocol": protocol}, socks_port, http_port) if protocol == "vless" else hysteria_config(profile, socks_port, http_port)


def mobile_uri(name: str, profile: dict, device: str) -> str:
    if resolve_protocol(name, profile) == "hysteria2":
        mobile = profile.get("mobileUris", {})
        if not isinstance(mobile, dict):
            raise ClientError("Invalid mobile profile map.")
        selected = mobile.get(device, profile.get("uri"))
        hysteria_config({"uri": selected}, 10808, 10809)
        return selected
    config = xray_config({**profile, "protocol": "vless"}, 10808, 10809)
    outbound = config["outbounds"][0]
    server = outbound["settings"]["vnext"][0]
    identity = server["users"][0]["id"]
    address = server["address"]
    authority = f"[{address}]" if ":" in address else address
    query = urlencode({
        "encryption": "none", "security": "tls", "sni": profile["sni"],
        "type": "ws", "host": profile["wsHost"], "path": profile["wsPath"],
    }, quote_via=quote)
    return f"vless://{identity}@{authority}:{server['port']}?{query}#{name}-{device}"


def export_mobile(name: str, profile: dict, device: str, output: Path) -> None:
    uri = mobile_uri(name, profile, device)
    expanded = output.expanduser()
    if expanded.is_symlink() or expanded.exists():
        raise ClientError("Export destination already exists; choose a new file.")
    destination = expanded.resolve()
    if destination.is_relative_to(ROOT.resolve()):
        raise ClientError("Mobile profiles must be exported outside this repository.")
    if any((parent / ".git").exists() for parent in destination.parents):
        raise ClientError("Mobile profiles cannot be exported inside another Git repository.")
    ensure_private_export_parent(destination.parent)
    try:
        private_write(destination, (uri + "\n").encode("utf-8"))
    except FileExistsError:
        raise ClientError("Export destination appeared during export; nothing was overwritten.") from None
    print("Mobile profile exported to the requested private file. Transfer securely; never commit or share publicly.")


def check_ports(socks_port: int, http_port: int) -> None:
    port(socks_port)
    port(http_port)
    if socks_port == http_port:
        raise ClientError("SOCKS and HTTP proxies require different ports.")
    for number, kind in ((socks_port, socket.SOCK_STREAM), (socks_port, socket.SOCK_DGRAM), (http_port, socket.SOCK_STREAM)):
        try:
            with socket.socket(socket.AF_INET, kind) as listener:
                if os.name == "nt":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind((BIND, number))
        except OSError:
            raise ClientError(f"Local proxy port {number} is unavailable; choose another port.") from None


def wait_ready(child, socks_port: int, http_port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = child.poll()
        if status is not None:
            raise ClientError(f"Client core exited before readiness (status {status}); raw core output is suppressed.")
        try:
            for number in (socks_port, http_port):
                with socket.create_connection((BIND, number), timeout=min(0.2, max(0.001, deadline - time.monotonic()))):
                    pass
            if child.poll() is not None:
                continue
            return
        except OSError:
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    raise ClientError("Client readiness timed out; check profile compatibility and remote availability.")


def stop_child(child) -> None:
    if child.poll() is None:
        try:
            child.terminate()
        except ProcessLookupError:
            return
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


@contextmanager
def running_core(name: str, config: dict, core: Path, socks_port: int, http_port: int, timeout: float):
    if not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise ClientError("Readiness timeout must be between 0 and 120 seconds.")
    check_ports(socks_port, http_port)
    with private_directory() as directory:
        config_path = directory / "client.json"
        private_write(config_path, json.dumps(config).encode("utf-8"))
        command = ([str(core), "run", "-c", str(config_path)] if resolve_protocol(name) == "vless"
                   else [str(core), "client", "--config", str(config_path)])
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        child = Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=directory, **options,
        )
        try:
            wait_ready(child, socks_port, http_port, timeout)
            yield child
        finally:
            stop_child(child)


def run_core(name: str, config: dict, core: Path, socks_port: int, http_port: int, timeout: float) -> None:
    with running_core(name, config, core, socks_port, http_port, timeout) as child:
        print(f"{name.upper()} client ready: SOCKS5 {BIND}:{socks_port}; HTTP {BIND}:{http_port}.", flush=True)
        print("Local listeners only; configure the application proxy manually. Remote connectivity is not verified.", flush=True)
        print("Keep this terminal open. Ctrl+C stops this child and removes its temporary config.", flush=True)
        status = child.wait()
        if status:
            raise ClientError(f"Client core exited (status {status}); raw core output is suppressed.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch-core", help="Verify the cached client offline; download only with --online.")
    fetch.add_argument("profile", type=profile_id, help="Protocol (vless/hysteria2) or configured profile ID.")
    fetch.add_argument("--profiles-file", type=Path, default=default_profiles_file())
    fetch.add_argument("--online", action="store_true", help="Explicitly allow a pinned official GitHub download instead of offline-only verification.")
    fetch.add_argument("--sha256", help="Trusted release-asset digest for explicit --online download when GitHub has no published digest.")
    export = commands.add_parser("export-mobile", help="Write one mobile URI to a new private file outside all Git repositories.")
    export.add_argument("--profile", required=True, type=profile_id)
    export.add_argument("--device", required=True, choices=("android", "iphone"))
    export.add_argument("--output", "--out", required=True, type=Path, help="New file in a dedicated user-only directory; a missing parent is created.")
    export.add_argument("--profiles-file", type=Path, default=default_profiles_file())
    for operation in ("connect", "doctor"):
        command = commands.add_parser(operation, help=("Run one client in the foreground." if operation == "connect" else "Validate locally without executing a core or contacting the VPN."))
        command.add_argument("profile", type=profile_id)
        command.add_argument("--profiles-file", type=Path, default=default_profiles_file())
        command.add_argument("--core", help="Path to a separately obtained official executable.")
        command.add_argument("--core-sha256", help="Trusted SHA-256 of the external executable (not its ZIP).")
        command.add_argument("--socks-port", type=int, default=10808)
        command.add_argument("--http-port", type=int, default=10809)
        if operation == "connect":
            command.add_argument("--ready-timeout", type=float, default=20)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "fetch-core":
            selected = args.profile
            if selected not in PROTOCOL_NAMES:
                selected = resolve_protocol(selected, load_profile(args.profiles_file, selected))
            fetch_core(selected, args.sha256, online=args.online)
            return 0
        profile = load_profile(args.profiles_file, args.profile)
        if args.command == "export-mobile":
            export_mobile(args.profile, profile, args.device, args.output)
            return 0
        config = build_config(args.profile, profile, args.socks_port, args.http_port)
        protocol = resolve_protocol(args.profile, profile)
        core = resolve_core(protocol, args.core, args.core_sha256)
        if args.command == "doctor":
            check_ports(args.socks_port, args.http_port)
            print(f"{args.profile}: shared bundle loaded, profile valid, core checksum verified, local ports available.")
            print("No core executed; remote connection and protocol compatibility are not tested.")
        else:
            run_core(protocol, config, core, args.socks_port, args.http_port, args.ready_timeout)
        return 0
    except KeyboardInterrupt:
        print("Stopped. Temporary client configuration removed.")
        return 130
    except ClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Paths, credentials, server addresses and raw core errors must not escape.
        print(f"Error: {type(exc).__name__}; operation failed (details suppressed to protect profiles).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
