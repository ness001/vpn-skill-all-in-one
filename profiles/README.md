# Private profile format

No working profiles are included. Supply your own plaintext JSON file privately; never commit it here. Set `VPN_PROFILES_FILE` to its absolute path, or use `--profiles-file PATH`. Explicit arguments override the environment; the standalone fallback is the ignored `profiles/vpn-profiles.json` under the toolkit root.

## Import installer exports

Convert a privately retrieved server-installer `client-uri.txt` or native `client.json` locally, without copying credentials into commands:

```bash
python3 clients/import_profile.py --input /absolute/private/client-uri.txt --name my-server --output "$HOME/vpn-private-bundle/vpn-profiles.json"
```

Use `python` on Windows. Either input format works for the installer's VLESS/WebSocket/verified-TLS and Hysteria2 exports; protocol is detected and stored explicitly. `--name` is your safe connection ID, not a protocol alias. The command validates through the same client configuration builders and writes one `schemaVersion: 1` bundle entry. No packages, downloads, server changes or connection tests are performed.

Output must be a **new `.json` file outside every Git repository**. A missing dedicated parent is created user-only; existing parents must already be private. Publication is atomic and never overwrites or merges an existing bundle. Credentials and paths are not printed. Select the resulting file with `--profiles-file` or `VPN_PROFILES_FILE`.

Only connection settings are imported: native local listeners, logs, routing/DNS and Xray mux are not copied; toolkit runtime listeners remain loopback-only. Native Hysteria2 accepts the installer's minimal `server`, `auth`, verified `tls` and optional local `socks5`/`http` sections, not arbitrary native features. Supported URI options follow the schema below; duplicate, insecure, malformed and unrepresentable connection options are refused, not silently dropped. For unsupported native settings, use a compatible native client rather than removing settings to force conversion.

## Schema

Top-level `schemaVersion` is integer `1`, and `profiles` maps your chosen identifiers to objects. Each object's `name` must match its map key. Identifiers use 1–64 ASCII letters, digits, underscores or hyphens and start with a letter or digit. A bundle may contain one server or multiple servers, including multiple entries using the same protocol. Identity and protocol are separate:

| Protocol | Required fields |
| --- | --- |
| `vless` | `name`, `protocol: "vless"`, `network: "ws"`, `tls: true`, `uuid`, `server`, integer `port`, `sni`, `wsHost`, `wsPath` |
| `hysteria2` | `name`, `protocol: "hysteria2"`, authenticated Hysteria2 `uri` |

A placeholder single-server bundle looks like this (not a working connection):

```json
{
  "schemaVersion": 1,
  "profiles": {
    "my-server": {
      "name": "my-server",
      "protocol": "hysteria2",
      "uri": "hysteria2://REPLACE_AUTH@vpn.example.invalid:443/?sni=vpn.example.invalid&insecure=0"
    }
  }
}
```

Select that entry with `python3 clients/vpn.py doctor my-server --profiles-file /absolute/private/vpn-profiles.json`. The launcher menu lists configured entries; GUI exports include those entries without requiring any specific server pair. GUI exports are named `VPN-v2rayN.txt` and `VPN-Clash.yaml`.

VLESS `uuid` must be a valid UUID; `wsPath` starts with `/`; `flow` is empty if supplied; `allowInsecure` is false if supplied. Hosts and ports must be valid. TLS verification is mandatory.

Hysteria2 accepts `hysteria2://` or `hy2://`, authentication in the URI authority, an optional port (default443), and supported query options `sni`, `insecure=0`/`false`, `alpn=h3`, `obfs=salamander` and `obfs-password`. Percent-encode reserved characters in authentication fields. Unsupported/duplicate options and insecure TLS are refused. Optional `mobileUris` maps `android` and `iphone` to device-specific URIs; otherwise mobile export uses `uri`. Desktop GUI exports use the desktop `uri`.

### Compatibility

Every bundle entry requires an explicit `protocol`: `vless` or `hysteria2`.
Profile IDs name individual connections. Core commands and verification manifests use
canonical protocol names.
