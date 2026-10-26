# Client troubleshooting

[Home](../README.md) · [Concepts](CONCEPTS.md) · [Client operations](CLIENTS.md) · [Device setup](DEVICES.md)

Diagnose the client path before considering server work. Preserve TLS verification, access controls and the other working VPN. No server restart, credential rotation or deployment is implied by these checks.

## Check in order

1. Confirm the selected private profile, app/core version, endpoint availability and intended network. The toolkit supplies no hosted server. A result from another platform or past test is not a live health check.
2. Confirm the application actually reaches the client: system proxy, application proxy or TUN coverage. Then check the separate [routing mode](CONCEPTS.md#routing-modes-and-split-tunneling).
3. For the Python launcher, use [local doctor / bounded check commands](CLIENTS.md#advanced-client-commands). A valid config, open listener or latency icon alone is not proof of browsing.
4. Test one HTTPS destination and the intended app on the intended device/network. For China bypass, inspect the matched rule and outbound as described in the [routing check](#verify-china-bypass).
5. Restore manually changed proxy settings when stopping the client. Share only sanitized diagnostics, not credentials or raw connection logs.

## Read-only server diagnostics

Use **`/vpn-diagnose config=/absolute/private/target.json minutes=15`**, or invoke the reusable CLI with an explicit config. **Local mode runs on your Ubuntu server without Azure CLI, subscription IDs or cloud access.** Azure mode optionally runs the same collector remotely and retrieves Azure Monitor metrics. Neither mode starts VMs, installs software or changes services. Keep configuration outside this public repository.

```bash
python3 admin/tools/diagnose_vpn.py --mode local --config /absolute/private/target.json --minutes 15
```

Minimal local settings:

```json
{
  "services": [
    {"unit": "your-proxy.service", "port": 443, "transport": "tcp"}
  ]
}
```

Use Python3.11+ for the CLI and read permissions for the selected service/log observations; elevation is not automatic. The installer separately supports Python3.10+. One to three unique expected systemd services with port and `tcp`/`udp` transport are required. For Azure mode, pass `--mode azure` and add your `subscription` UUID, `resourceGroup` and `vm` to the JSON config; an existing Azure CLI login is required. Azure Monitor CPU/credit metrics are unavailable in local mode, not reported as zero.

Optional shared settings: `guestPython` (absolute interpreter path, default `/usr/bin/python3`); `logDirectories` (map `vless` and/or `hy2` to absolute directories); `historicalLog` (absolute file path, metadata only). Azure-only `cpuCredits` defaults to `false`; enable only for burstable VMs. Paths must use letters, numbers, `_`, `.`, `/` or `-`, without `.`/`..` components. Collector requirements: Linux `/proc`, systemd, `ss`, and the configured Python. Local Ubuntu support is 22.04/24.04 LTS amd64; offline tests do not establish live installation acceptance.

Supported log directories contain private `0700` directories and `0600` single-link files named `<unix-epoch-10-second-bucket>-<sequence>.log`. VLESS records use bracketed severity; Hy2 records use JSON `level`, `msg`, `error`, `reqAddr`. This is an existing rolling-collector format, **not arbitrary journal/file support**. Diagnostics do not install/configure a collector. Unconfigured streams return `log_support_not_configured`; inaccessible/unsafe or unsupported content returns incomplete coverage, never a clean-window claim. Arbitrary deployments can still obtain CPU/service/resource observations while logs remain explicitly unavailable.

`--dry-run` validates scope without Azure/network execution. Windows uses `python` in place of `python3`. `--logs-only` skips Azure Monitor but retains guest checks. Optional `--output .local/diagnostics/<new-name>.json` saves only a new local file under `~/.cache/vpn-skill/runtime/.local/diagnostics/`. Scanning is bounded to 1–30 minutes, 2048 files/32MiB per configured protocol, 64KiB partial lines and a 3000-byte guest summary; report all coverage/truncation flags. Fixed error categories/counts exclude raw logs and client/destination identities. Never share private configuration or credentials. Healthy CPU, active services and empty samples do not prove forwarding or browsing; missing metrics are unknown, and lifetime UDP counters are not window events.

See the [skill procedure](../skills/vpn-diagnose/SKILL.md).

## Loopback requests rejected by the VPN server

A request for localhost belongs on the **client device**, not the VPN server. The server correctly blocks remote access to its loopback/private network; do not disable that protection.

Generated Clash profiles now place these rules **before** the existing China bypass and default VPN rule:

```yaml
- DOMAIN-SUFFIX,localhost,DIRECT
- IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
- IP-CIDR6,::1/128,DIRECT,no-resolve
- GEOIP,CN,DIRECT
- MATCH,VPN
```

Re-export/re-import the local Clash profile to receive the fix, or add these first three rules to the active client's rule profile. Keep Rule mode. Existing imported files do not update merely because GitHub changed. Other clients need their own localhost/application-proxy bypass; exported node URIs do not carry application routing rules.

This fixes the generated profile's omission, not every possible source of localhost requests and not a proved cause of slow public downloads. If an application points its proxy at the wrong local port or recursively proxies itself, correct that application setting too.

## Connection resets

`connection reset by peer` is a symptom, not a setting to disable. Determine whether the log concerns the destination TCP connection, a QUIC transport/session or a local client close, and correlate it with the failing request. Servers and applications can legitimately close sessions. Do not assume GFW shaping or raise bandwidth/MTU blindly. Use a bounded transfer only when measuring speed is intended; keep successful and incomplete samples separate.

## Verify China bypass

Keep **Rule** selected, choose your available endpoint under **VPN**, and ensure the intended application actually uses Clash. Open one known mainland-China-IP destination and one international destination, then inspect Clash's connection details: the former should match **GeoIP CN → DIRECT**, the latter **MATCH → VPN**. A connection icon or latency check alone does not verify routing. Avoid sharing raw connection logs, which can reveal browsing destinations.

## Symptoms

| Symptom | First check |
| --- | --- |
| Missing/import-rejected profile | Correct private file path or assigned device file; app/version/protocol compatibility. Do not redeploy servers. |
| Certificate error | Device time and supplied TLS hostname; never disable verification. |
| Connected, no browsing | Application proxy/routing, DNS, TLS and protocol compatibility on that device. |
| Browser fails after disconnect | Restore manually changed proxy settings. |
| Sharing device cannot browse | Fix its upstream client before TV settings. |
| PC works, TV cannot reach it | [LAN setup](CLIENTS.md#share-a-proxy-over-the-lan): loopback binding, LAN IP, non-guest Wi-Fi, Allow LAN, firewall/isolation, protocol/port/authentication. Never disable the firewall globally. |
| Phone sharing stops when locked | Client background/battery behavior; consider a box/PC client. |

For support, share a nonsecret profile label, device/app/core version, time, network type and a sanitized error—not credentials, QR codes, private destinations or raw logs. Compare performance on the same device/network/destination at similar times; separate startup delay from sustained speed and agree on scope before high-volume tests.

## Terminal and TUN problems

| Symptom | First check |
| --- | --- |
| Browser works but curl/Git times out | The tool may ignore macOS system proxy. Verify TUN coverage or try a [per-command proxy](CLIENTS.md#explicit-proxy-for-one-command). A timeout alone does not establish the cause. |
| Connection refused to `127.0.0.1` | Confirm Clash is running and the configured port matches; inspect stale environment, shell startup or tool-specific proxy settings privately. Remove only settings you intentionally added. |
| TUN is on but the request is not in Clash | Check helper/service status, route exclusions, DNS and IPv4/IPv6 coverage. The toggle is not proof; use the [bounded test](CLIENTS.md#verify-tun-without-an-explicit-proxy). |
| GUI/LAN apps break after enabling TUN | Check another VPN, app-specific proxy, DNS and local-network routes. Temporarily disable TUN and compare with the previous working setup; do not disable the firewall globally. |
| Networking fails after Clash stops | Check for a still-enabled system proxy, persistent proxy variables/tool settings or stale TUN routes. Use the client's normal disable/cleanup controls before changing OS networking manually. |
| TUN feels slow | Compare the same small request/network/node, pause unrelated downloads, and inspect DIRECT versus VPN routing. Server load/distance, DNS and network quality may matter more than TUN overhead. Avoid unapproved high-volume speed tests. |

System Proxy and TUN being enabled together is not itself an error. Do not switch to Global mode merely to make terminal apps reach Clash—it changes routing policy, not coverage. No setup guarantees all commands work; authentication, upstream outages and TLS errors require their own diagnosis.
