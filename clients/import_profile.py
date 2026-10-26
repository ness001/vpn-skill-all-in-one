#!/usr/bin/env python3
"""Convert one private installer client JSON or URI file to a new toolkit bundle."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import quote, urlencode, urlsplit

from qr import _fields, uri_profile, xray_profile
from vpn import build_config, host, profile_id, text
from vpn_common import (
    ClientError, MAX_CONFIG_BYTES, check_private_path, ensure_private_export_parent,
    limited_read, private_directory, private_export_path, private_write,
)


def hysteria_profile(config: dict) -> dict:
    """Adapt the installer's minimal native Hysteria2 connection, not local listeners."""
    _fields(config, {"server", "auth", "tls", "socks5", "http"})
    tls = _fields(config.get("tls", {}), {"sni", "insecure"})
    if tls.get("insecure", False) is not False:
        raise ClientError("Hysteria2 input must verify TLS.")
    server = text(config.get("server"), "server")
    endpoint = urlsplit("//" + server)
    if (endpoint.username is not None or endpoint.password is not None or endpoint.path
            or endpoint.query or endpoint.fragment or endpoint.hostname is None):
        raise ClientError("Native Hysteria2 input requires one server host and port.")
    # Parsing and validation below also reject malformed ports/hosts and empty auth.
    server_port = endpoint.port
    if server_port is None:
        raise ClientError("Native Hysteria2 input requires an explicit server port.")
    authority = f"[{endpoint.hostname}]" if ":" in endpoint.hostname else endpoint.hostname
    auth = text(config.get("auth"), "auth")
    query = urlencode({"sni": host(tls.get("sni", endpoint.hostname), "sni"), "insecure": "0"})
    return uri_profile(f"hysteria2://{quote(auth, safe='')}@{authority}:{server_port}?{query}")


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ClientError("Duplicate JSON fields are not supported.")
        result[key] = value
    return result


def input_profile(source: Path, name: str) -> dict:
    profile_id(name)
    source = source.expanduser().absolute()
    check_private_path(source)
    if not stat.S_ISREG(source.stat().st_mode):
        raise ClientError("Input must be a regular file.")
    content = limited_read(source, MAX_CONFIG_BYTES).decode("utf-8-sig").strip()
    if content.startswith(("vless://", "hysteria2://", "hy2://")):
        profile = uri_profile(content)
    else:
        config = json.loads(content, object_pairs_hook=unique_fields)
        if not isinstance(config, dict) or "profiles" in config or "schemaVersion" in config:
            raise ClientError("Input must be one installer client JSON or supported URI, not a bundle.")
        profile = xray_profile(config) if "outbounds" in config else hysteria_profile(config)
    profile = {**profile, "name": name}
    build_config(name, profile, 10808, 10809)
    return profile


def import_profile(source: Path, output: Path, name: str) -> Path:
    destination = private_export_path(output, ".json")
    profile = input_profile(source, name)
    data = (json.dumps({"schemaVersion": 1, "profiles": {name: profile}}, indent=2) + "\n").encode("utf-8")
    ensure_private_export_parent(destination.parent)
    with private_directory(destination.parent) as temporary:
        pending = temporary / "bundle.json"
        private_write(pending, data)
        private_export_path(destination, ".json")
        # Atomic no-clobber publication: never expose a partially written bundle.
        os.link(pending, destination)
    return destination


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ClientError("Invalid arguments; use --help. Argument values are suppressed.")


def parser() -> argparse.ArgumentParser:
    result = PrivateArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--input", required=True, type=Path, help="Private client.json or one-line client-uri.txt; no secrets in arguments.")
    result.add_argument("--name", required=True, type=profile_id, help="Safe connection ID, independent of its protocol.")
    result.add_argument("--output", required=True, type=Path, help="New JSON bundle outside all Git repositories, in a private directory.")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        import_profile(args.input, args.output, args.name)
        print("Private profile bundle created at the requested output. No connection was tested; keep this file private.")
        return 0
    except KeyboardInterrupt:
        print("Profile import cancelled.", file=sys.stderr)
        return 130
    except Exception:
        # JSON, filesystem and argument exceptions can contain credentials or paths.
        print("Error: Profile import failed. Check the supported input, safe name and new private JSON output outside Git; details suppressed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
