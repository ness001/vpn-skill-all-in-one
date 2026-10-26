"""Export configured profiles privately for supported desktop GUIs."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from vpn import build_config, hysteria_config, load_profile, mobile_uri, profile_label, profile_names, resolve_protocol
from vpn_common import ROOT, ClientError, default_profiles_file, ensure_private_export_parent, private_write


def clash_config(profiles: dict[str, dict]) -> dict:
    proxies = []
    for name, profile in profiles.items():
        build_config(name, profile, 10808, 10809)
        label = profile_label(name, profile)
        if resolve_protocol(name, profile) == "vless":
            proxy = {"name": label, "type": "vless", "server": profile["server"], "port": profile["port"],
                     "uuid": profile["uuid"], "tls": True, "servername": profile["sni"], "skip-cert-verify": False,
                     "network": "ws", "udp": True, "ws-opts": {"path": profile["wsPath"], "headers": {"Host": profile["wsHost"]}}}
        else:
            hy = hysteria_config(profile, 10808, 10809)
            endpoint = urlsplit("//" + hy["server"])
            proxy = {"name": label, "type": "hysteria2", "server": endpoint.hostname, "port": endpoint.port,
                     "password": hy["auth"], "sni": hy["tls"]["sni"], "skip-cert-verify": False}
            if "obfs" in hy:
                proxy["obfs"] = "salamander"
                proxy["obfs-password"] = hy["obfs"]["salamander"]["password"]
        proxies.append(proxy)
    if not proxies:
        raise ClientError("No connection profiles are configured.")
    return {
        "mixed-port": 7890, "allow-lan": False, "bind-address": "127.0.0.1", "mode": "rule",
        "log-level": "warning", "ipv6": False, "proxies": proxies,
        "proxy-groups": [{"name": "VPN", "type": "select", "proxies": [proxy["name"] for proxy in proxies]}],
        "rules": [
            "DOMAIN-SUFFIX,localhost,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR6,::1/128,DIRECT,no-resolve",
            "GEOIP,CN,DIRECT",
            "MATCH,VPN",
        ],
    }


def export_gui_profiles(app_id: str, directory: Path, profiles_file: Path | None = None) -> Path:
    if app_id not in ("v2rayn", "clash-verge-rev"):
        raise ClientError("Unsupported GUI profile format.")
    path = profiles_file if profiles_file is not None else default_profiles_file()
    profiles = {name: load_profile(path, name) for name in profile_names(path)}
    if not profiles:
        raise ClientError("No connection profiles are configured.")
    destination = directory.expanduser().resolve()
    if destination.is_relative_to(ROOT.resolve()) or any((parent / ".git").exists() for parent in (destination, *destination.parents)):
        raise ClientError("GUI profile exports must stay outside Git repositories.")
    if app_id == "v2rayn":
        uris = []
        for name, profile in profiles.items():
            build_config(name, profile, 10808, 10809)
            # GUI imports use desktop auth, not optional device-specific credentials.
            desktop = {key: value for key, value in profile.items() if key != "mobileUris"}
            uri = mobile_uri(name, desktop, "android").split("#", 1)[0]
            uris.append(uri + "#" + quote(profile_label(name, profile), safe=""))
        data = ("\n".join(uris) + "\n").encode()
        filename = "VPN-v2rayN.txt"
    else:
        # JSON is valid YAML; the .yaml extension is convenient for GUI local import.
        data = (json.dumps(clash_config(profiles), indent=2) + "\n").encode()
        filename = "VPN-Clash.yaml"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_private_export_parent(destination)
    output = destination / filename
    if output.exists() or output.is_symlink():
        raise ClientError("Profile export already exists; use a fresh private directory.")
    private_write(output, data)
    return output
