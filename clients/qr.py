#!/usr/bin/env python3
"""Convert a private VPN bundle, URI file or supported Xray config to a private PNG."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import parse_qs, quote, unquote, urlsplit

from vpn import load_profile, mobile_uri, profile_id, text, xray_config
from vpn_common import (
    ClientError, MAX_CONFIG_BYTES, ROOT, check_private_path, ensure_private_export_parent, limited_read,
    private_directory, private_export_path, private_write,
)


class QRExportError(ClientError):
    """Only fixed, credential-free messages belong in this exception."""


def _fields(value, allowed: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) - allowed:
        raise QRExportError("Unsupported connection settings; use a minimal verified-TLS profile.")
    return value


def _one(value) -> dict:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise QRExportError("Exactly one VLESS server and authenticated user are required.")
    return value[0]


def xray_profile(config: dict) -> dict:
    """Adapt connection fields only; routing, DNS, inbounds and mux are not exported."""
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list) or not all(isinstance(item, dict) for item in outbounds):
        raise QRExportError("Invalid Xray outbound list.")
    outbound = _one([item for item in outbounds if item.get("protocol") == "vless"])
    _fields(outbound, {"tag", "protocol", "settings", "streamSettings", "mux"})
    settings = _fields(outbound.get("settings"), {"vnext"})
    server = _fields(_one(settings.get("vnext")), {"address", "port", "users"})
    user = _fields(_one(server.get("users")), {"id", "encryption", "flow", "level", "email"})
    stream = _fields(outbound.get("streamSettings"), {"network", "security", "tlsSettings", "wsSettings"})
    tls = _fields(stream.get("tlsSettings", {}), {"serverName", "allowInsecure"})
    ws = _fields(stream.get("wsSettings", {}), {"path", "headers", "host"})
    headers = _fields(ws.get("headers", {}), {"Host"})
    if (stream.get("security") != "tls" or user.get("encryption") != "none"
            or ("host" in ws and "Host" in headers and ws["host"] != headers["Host"])):
        raise QRExportError("Only authenticated VLESS WebSocket with verified TLS is supported.")
    return {
        "protocol": "vless", "network": stream.get("network"), "tls": True,
        "server": server.get("address"), "port": server.get("port"), "uuid": user.get("id"),
        "flow": user.get("flow", ""), "allowInsecure": tls.get("allowInsecure", False),
        "sni": tls.get("serverName", server.get("address")), "wsPath": ws.get("path", "/"),
        "wsHost": ws.get("host", headers.get("Host", server.get("address"))),
    }


def uri_profile(uri: str) -> dict:
    """Adapt supported URI connection fields without losing transport options."""
    text(uri, "uri", 16384)
    if any(char.isspace() for char in uri):
        raise QRExportError("URI whitespace must be percent-encoded.")
    # urllib otherwise accepts broken escapes or replaces invalid UTF-8 silently.
    if re.search(r"%(?![0-9a-fA-F]{2})", uri):
        raise QRExportError("Invalid URI percent encoding.")
    unquote(uri, errors="strict")
    parsed = urlsplit(uri)
    if parsed.scheme in ("hysteria2", "hy2"):
        profile = {"protocol": "hysteria2", "uri": uri}
        mobile_uri("hysteria2", profile, "android")
        return profile
    if (parsed.scheme != "vless" or parsed.path not in ("", "/")
            or parsed.username is None or parsed.password is not None):
        raise QRExportError("Input must contain one supported authenticated VPN URI.")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
    if any(len(values) != 1 for values in query.values()):
        raise QRExportError("Duplicate VLESS URI options are not supported.")
    options = _fields({key: values[0] for key, values in query.items()},
                      {"encryption", "security", "sni", "type", "host", "path", "flow"})
    if options.get("encryption") != "none" or options.get("security") != "tls":
        raise QRExportError("Only authenticated VLESS WebSocket with verified TLS is supported.")
    profile = {
        "protocol": "vless", "network": options.get("type"), "tls": True,
        "server": parsed.hostname, "port": parsed.port if parsed.port is not None else 443, "uuid": unquote(parsed.username),
        "flow": options.get("flow", ""), "sni": options.get("sni", parsed.hostname),
        "wsHost": options.get("host", parsed.hostname), "wsPath": options.get("path", "/"),
    }
    xray_config(profile, 10808, 10809)
    return profile


def validated_uri(uri: str) -> str:
    """Validate a URI while keeping its exact supported options intact."""
    uri_profile(uri)
    return uri


def _check_path(path: Path) -> None:
    try:
        check_private_path(path)
    except ClientError as error:
        raise QRExportError(str(error)) from None


def input_uri(path: Path, profile: str | None = None, device: str = "android", label: str | None = None) -> str:
    path = path.expanduser().absolute()
    _check_path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise QRExportError("Input must be a regular file.")
    content = limited_read(path, MAX_CONFIG_BYTES).decode("utf-8-sig").strip()
    if content.startswith(("vless://", "hysteria2://", "hy2://")):
        if profile is not None:
            raise QRExportError("--profile is only used with a profile bundle.")
        uri = validated_uri(content)
    else:
        config = json.loads(content)
        if not isinstance(config, dict):
            raise QRExportError("Input JSON must be a profile bundle or supported Xray config.")
        if "schemaVersion" in config or "profiles" in config:
            if profile is None:
                raise QRExportError("A profile bundle requires --profile with a configured profile ID.")
            uri = mobile_uri(profile, load_profile(path, profile), device)
        else:
            if profile is not None:
                raise QRExportError("--profile is only used with a profile bundle.")
            uri = mobile_uri("vless", xray_profile(config), device)
    if label is not None:
        uri = uri.split("#", 1)[0] + "#" + quote(text(label, "label", 256), safe="")
    return uri


def png_bytes(uri: str) -> bytes:
    try:
        import qrcode
        from PIL import Image
    except ImportError:
        raise QRExportError("QR support is unavailable. Install clients/requirements-qr.txt separately; nothing was downloaded.") from None
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    code.add_data(uri)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    data = buffer.getvalue()
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    # Optional local verification only; zxing-cpp is NOT a production dependency.
    try:
        import zxingcpp
    except ModuleNotFoundError as error:
        if error.name != "zxingcpp":
            raise
    else:
        with Image.open(io.BytesIO(data)) as image:
            results = zxingcpp.read_barcodes(image)
        if len(results) != 1 or results[0].text != uri:
            raise QRExportError("QR decoding verification failed; no output was written.")
    return data


def _output_path(output: Path) -> Path:
    try:
        return private_export_path(output, ".png", root=ROOT)
    except ClientError as error:
        raise QRExportError(str(error)) from None


def export_qr(source: Path, output: Path, *, profile: str | None = None,
              device: str = "android", label: str | None = None) -> Path:
    destination = _output_path(output)
    data = png_bytes(input_uri(source, profile, device, label))
    # An existing user+SYSTEM directory can contain a NEW user-only qr/ child.
    # Existing parent permissions are inspected, never modified.
    ensure_private_export_parent(destination.parent)
    with private_directory(destination.parent) as temporary:
        pending = temporary / "qr.png"
        private_write(pending, data)
        _output_path(destination)
        # Atomic, no-clobber publication on Windows and POSIX. Fail closed if the
        # filesystem cannot hard-link rather than leave a partially written PNG.
        os.link(pending, destination)
    return destination


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise QRExportError("Invalid arguments; use --help. Argument values are suppressed.")


def parser() -> argparse.ArgumentParser:
    result = PrivateArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--input", required=True, type=Path, help="Private bundle, one-line URI or supported Xray JSON.")
    result.add_argument("--output", required=True, type=Path, help="New PNG outside Git, in a private directory.")
    result.add_argument("--profile", type=profile_id, help="Configured profile ID; required only for a profile bundle.")
    result.add_argument("--device", choices=("desktop", "android", "iphone"), default="android")
    result.add_argument("--label", help="Optional phone entry label; replaces the URI fragment.")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        destination = export_qr(args.input, args.output, profile=args.profile, device=args.device, label=args.label)
        print(f"Private QR PNG: {destination}")
        print("Connection only; configure China bypass in phone app. Keep this credential QR private.")
        return 0
    except QRExportError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("QR export cancelled.", file=sys.stderr)
        return 130
    except Exception:
        # Decoder, JSON, dependency and filesystem exceptions can contain secrets.
        print("Error: QR export failed. Check the supported input, optional dependencies and private output directory; details suppressed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
