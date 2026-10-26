"""Pure, stdlib-only configuration rendering for fresh personal VPN servers."""

import ipaddress
import json
import re
import secrets
import uuid
from urllib.parse import quote, urlencode

# Explicit ranges avoid a mutable geoip database dependency. Never reject the
# entire IPv4-mapped IPv6 range: Go also matches ordinary public IPv4 there.
DENIED_NETWORKS = (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4", "240.0.0.0/4", "168.63.129.16/32",
    "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    "2001:db8::/32",
)
STATE_ROOT = "/var/lib/personal-vpn-installer"
CONFIG_ROOT = "/etc/personal-vpn"
DATA_ROOT = "/var/lib/personal-vpn"
OPT_ROOT = "/opt/personal-vpn"
CLIENT_ROOT = "/root/personal-vpn"
VERSIONS = {"xray": "26.3.27", "caddy": "2.11.4", "hy2": "2.12.3"}


PROFILES = {"vless": "vless", "hysteria2": "hysteria2"}


def resolve_profile(profile):
    """Resolve a supported protocol to its neutral storage directory."""
    try:
        return PROFILES[profile]
    except (KeyError, TypeError):
        raise ValueError("Profile must be vless or hysteria2.") from None


def storage_profile(profile):
    return resolve_profile(profile)


def validate_target(profile, domain, public_ip, email=""):
    resolve_profile(profile)
    domain = domain.lower()
    if len(domain) > 253 or "." not in domain or not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", domain
    ):
        raise ValueError("Use a public ASCII DNS hostname (punycode if needed), not a URL or IP.")
    try:
        address = ipaddress.IPv4Address(public_ip)
    except ipaddress.AddressValueError:
        raise ValueError("--public-ip must be an IPv4 address.") from None
    if not address.is_global or address.is_multicast or str(address) == "168.63.129.16":
        raise ValueError("--public-ip must be a public unicast IPv4 address.")
    if email and (len(email) > 254 or not re.fullmatch(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", email
    )):
        raise ValueError("--email must be a valid ASCII email address.")
    return {"profile": profile, "domain": domain, "public_ip": str(address), "email": email}


def validate_credentials(profile, value):
    # Do not include supplied values in errors: these exceptions may be public.
    if not isinstance(value, dict):
        raise ValueError("Credentials must be a JSON object.")
    profile = resolve_profile(profile)
    allowed = {"uuid", "ws_path"} if profile == "vless" else {"password", "username"}
    if set(value) - allowed:
        raise ValueError("Credential file contains unsupported fields for this profile.")
    if profile == "vless":
        try:
            parsed = uuid.UUID(value["uuid"])
            if str(parsed) != value["uuid"].lower() or parsed.int == 0:
                raise ValueError
        except (KeyError, ValueError, AttributeError, TypeError):
            raise ValueError("VLESS credentials require a nonzero canonical UUID.") from None
        path = value.get("ws_path")
        if not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9/_-]{8,200}", path):
            raise ValueError("VLESS ws_path must start with / and contain 8-200 safe path characters.")
        return {"uuid": str(parsed), "ws_path": path}
    password = value.get("password")
    if not isinstance(password, str) or not 16 <= len(password) <= 256 or not re.fullmatch(r"[\x21-\x7e]+", password):
        raise ValueError("Hysteria2 password must have 16-256 printable ASCII characters without spaces.")
    username = value.get("username")
    if username is not None and (not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username)):
        raise ValueError("Hysteria2 optional username must contain 1-64 letters, digits, underscores or hyphens.")
    result = {"password": password}
    if username is not None:
        result["username"] = username
    return result


def new_credentials(profile):
    if resolve_profile(profile) == "vless":
        return {"uuid": str(uuid.uuid4()), "ws_path": "/" + secrets.token_urlsafe(24)}
    return {"password": secrets.token_urlsafe(32)}


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def xray_config(credentials):
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "vless-ws", "listen": "127.0.0.1", "port": 39761,
            "protocol": "vless",
            "settings": {"clients": [{"id": credentials["uuid"]}], "decryption": "none"},
            "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": credentials["ws_path"]}},
        }],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4"}},
            {"tag": "blocked", "protocol": "blackhole", "settings": {}},
        ],
        "routing": {"domainStrategy": "IPOnDemand", "rules": [{
            "type": "field", "ip": list(DENIED_NETWORKS), "outboundTag": "blocked",
        }]},
    }


def caddy_config(target, credentials):
    email = f"    email {json.dumps(target['email'])}\n" if target["email"] else ""
    return ("{\n    admin off\n" + email +
            "    servers {\n        protocols h1 h2\n    }\n}\n\n" +
            target["domain"] + " {\n" +
            "    bind 0.0.0.0\n" +
            f"    @vpn path {credentials['ws_path']}\n" +
            "    handle @vpn {\n        reverse_proxy 127.0.0.1:39761\n    }\n" +
            '    handle {\n        respond "Not found" 404\n    }\n}\n')


def hy2_config(target, credentials):
    acme = {
        "domains": [target["domain"]], "ca": "letsencrypt", "type": "tls",
        "tls": {"altPort": 443}, "dir": DATA_ROOT + "/hy2/acme",
    }
    if target["email"]:
        acme["email"] = target["email"]
    if "username" in credentials:
        auth = {"type": "userpass", "userpass": {credentials["username"]: credentials["password"]}}
    else:
        auth = {"type": "password", "password": credentials["password"]}
    return {
        "listen": "0.0.0.0:443", "acme": acme, "auth": auth,
        "congestion": {"type": "bbr", "bbrProfile": "standard"},
        "outbounds": [{"name": "direct", "type": "direct", "direct": {"mode": "4"}}],
        "acl": {"inline": [f"reject({network})" for network in DENIED_NETWORKS] + ["direct(all)"]},
    }


def client_config(target, credentials):
    host = target["domain"]
    label = {"vless": "VLESS", "hysteria2": "Hysteria2"}[target["profile"]]
    if resolve_profile(target["profile"]) == "vless":
        query = urlencode({"encryption": "none", "security": "tls", "sni": host,
                           "type": "ws", "host": host, "path": credentials["ws_path"]})
        uri = f"vless://{credentials['uuid']}@{host}:443?{query}#{label}"
        config = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"listen": "127.0.0.1", "port": 1080, "protocol": "socks", "settings": {"udp": True}}],
            "outbounds": [{"protocol": "vless", "settings": {"vnext": [{
                "address": host, "port": 443, "users": [{"id": credentials["uuid"], "encryption": "none"}],
            }]}, "streamSettings": {"network": "ws", "security": "tls",
                "tlsSettings": {"serverName": host, "allowInsecure": False},
                "wsSettings": {"path": credentials["ws_path"], "headers": {"Host": host}}}}],
        }
    else:
        auth = credentials["password"]
        if "username" in credentials:
            auth = credentials["username"] + ":" + auth
        uri = f"hysteria2://{quote(auth, safe='')}@{host}:443?{urlencode({'sni': host, 'insecure': '0'})}#{label}"
        config = {"server": f"{host}:443", "auth": auth, "tls": {"sni": host, "insecure": False},
                  "socks5": {"listen": "127.0.0.1:1080"}}
    return uri + "\n", json_text(config)


def unit(core, config_profile=None):
    config_profile = config_profile or ("vless" if core in ("xray", "caddy") else "hysteria2")
    account = core
    executable = f"{OPT_ROOT}/{core}/{VERSIONS[core]}/{core}"
    service = f"personal-vpn-{core}"
    low_port = core != "xray"
    if core == "xray":
        command = f"{executable} run -config {CONFIG_ROOT}/{config_profile}/xray/config.json"
        extra = ""
    elif core == "caddy":
        command = f"{executable} run --config {CONFIG_ROOT}/{config_profile}/caddy/Caddyfile --adapter caddyfile"
        extra = (f"Environment=HOME={DATA_ROOT}/caddy\n"
                 f"Environment=XDG_DATA_HOME={DATA_ROOT}/caddy/data\n"
                 f"Environment=XDG_CONFIG_HOME={DATA_ROOT}/caddy/config\n"
                 f"ReadWritePaths={DATA_ROOT}/caddy\n")
    else:
        command = f"{executable} server --config {CONFIG_ROOT}/{config_profile}/config.json"
        extra = f"Environment=HOME={DATA_ROOT}/hy2\nReadWritePaths={DATA_ROOT}/hy2\n"
    dependencies = "Wants=personal-vpn-xray.service\nAfter=personal-vpn-xray.service\n" if core == "caddy" else ""
    capabilities = "CAP_NET_BIND_SERVICE" if low_port else ""
    return (
        f"[Unit]\nDescription=Personal VPN {core}\nWants=network-online.target\nAfter=network-online.target\n{dependencies}\n"
        f"[Service]\nType=simple\nUser={account}\nGroup={account}\nExecStart={command}\n"
        "Restart=on-failure\nRestartSec=5\nUMask=0077\n"
        f"CapabilityBoundingSet={capabilities}\nAmbientCapabilities={capabilities}\n"
        "NoNewPrivileges=true\nPrivateTmp=true\nPrivateDevices=true\nProtectSystem=strict\n"
        "ProtectHome=true\nProtectKernelTunables=true\nProtectKernelModules=true\nProtectControlGroups=true\n"
        "RestrictSUIDSGID=true\nLockPersonality=true\nRestrictRealtime=true\n"
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\n" + extra +
        f"StandardOutput=append:{STATE_ROOT}/{service}.log\nStandardError=append:{STATE_ROOT}/{service}.log\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )
