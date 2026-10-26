# Client operations

[Home](../README.md) · [Concepts](CONCEPTS.md) · [Device setup](DEVICES.md) · [Troubleshooting](TROUBLESHOOTING.md)

Use this guide for commands, private exports, application proxies and LAN sharing. These are client-side operations; do not provision or restart a server to connect. For ordinary desktop use, use the root launcher described in [Quick start](../README.md#quick-start).

Commands run from the **repository root**, using Python **3.11+** (`python` on Windows, `python3` on macOS/Linux). Set `VPN_PROFILES_FILE` to the absolute path of your own private [profile bundle](../profiles/README.md), or pass `--profiles-file PATH` to supported commands. Aliases identify formats, not supplied servers. Normal connections and text exports need no pip packages; optional QR export has a small separate dependency. The Python launcher and standalone cores do not inherit Clash routing rules; see [concepts](CONCEPTS.md#routing-modes-and-split-tunneling).

- [Import installer exports](../profiles/README.md#import-installer-exports) — convert private native JSON/URI files to a toolkit bundle
- [Advanced commands](#advanced-client-commands)
- [Speed testing](#speed-testing)
- [Private mobile exports](#export-an-existing-mobile-profile)
- [Private QR export](#convert-a-configuration-to-a-private-qr-code)
- [HTTP/SOCKS application setup](#httpsocks-for-another-application)
- [Terminal networking and TUN checks](#terminal-networking-through-clash)
- [Protected LAN sharing](#share-a-proxy-over-the-lan)

## Advanced client commands

```powershell
# Start your VLESS or Hysteria2 profile; run only one at a time. Ctrl+C stops it.
python clients/app.py vless --no-browser
python clients/app.py hysteria2 --no-browser

# One bounded HTTPS check through the proxy; no browser, then automatic stop.
python clients/app.py vless --check

# Local validation only: no core execution or VPN request.
python clients/vpn.py doctor vless
python clients/vpn.py doctor hysteria2
python clients/vpn.py doctor hysteria2

# Verify the previously acquired Hysteria2 core cache offline.
python clients/vpn.py fetch-core hysteria2

# Low-level Hysteria2 connection on alternative loopback ports.
python clients/vpn.py connect hysteria2 --socks-port 11808 --http-port 11809

# Explicitly opt into a reviewed pinned official download, if needed.
python clients/vpn.py fetch-core hysteria2 --online
```

`clients/app.py` with no arguments lists your configured connections, followed by **Desktop GUI installers** and **Exit**. Names identify your profiles, not required regions; one or multiple configured connections are supported. It uses a verified cached core; prepare the selected protocol first with `clients/vpn.py fetch-core vless --online` or `fetch-core hysteria2 --online` after download authorization. No virtual environment or pip step is required. Closing its separate browser or pressing Ctrl+C stops its owned client/browser. If Chrome/Edge is unavailable, the proxy remains available with manual local-port instructions. Advanced app options include `--socks-port`, `--http-port`, `--ready-timeout` and `--profiles-file`.

`doctor` checks the profile, pinned executable identity/hash and local port availability. A connection's ready message only means listeners opened. Normal ports are SOCKS5 `127.0.0.1:10808` and HTTP `127.0.0.1:10809`; only explicitly configured applications use them. Stop the first client before reusing its ports. Low-level `connect --ready-timeout` accepts up to 120 seconds.

`doctor`, `connect` and `export-mobile` support `--profiles-file PATH`; overrides last only for that invocation. Explicit paths override `VPN_PROFILES_FILE`; otherwise the fallback is `profiles/vpn-profiles.json` under the toolkit root, not the terminal directory. The schema is `schemaVersion: 1`; the `profiles` object maps safe connection IDs to profiles with explicit `vless` or `hysteria2` protocol selection; see [profile reference](../profiles/README.md). No decryption-key option is required; protect the plaintext input file using local access controls.

For mobile export commands and private output restrictions, use the [export procedure](#export-an-existing-mobile-profile). `--out` aliases `--output`. Hysteria2 profiles select the requested device's `mobileUris` entry when available, otherwise their default URI; VLESS profiles derive their VLESS/WebSocket/TLS URI from the supplied settings. Exporting creates no account and rotates nothing.

### Core verification and runtime files

- Pinned official client releases are **Xray v26.3.27** for VLESS and **Hysteria2 v2.12.3** for Hysteria2, for Windows x64 and macOS Intel/Apple Silicon. Source references, release hashes and licenses are under [vendor/](../vendor/README.md); preserve its notices.
- Acquired cores live under `~/.cache/vpn-skill/runtime/.tools/<core>/<tag-with-slashes-replaced-by-dashes>/<platform>/`, with `verified.json`. Each use verifies pinned project, version, profile/platform, asset identity and executable SHA-256. The source tree contains metadata only; legacy explicitly supplied `vendor/cores` remains supported without silent repair.
- A present but incomplete/modified/mismatched bundle fails closed; no automatic cache fallback or replacement download. If the platform bundle is absent, the user cache `~/.cache/vpn-skill/runtime/.tools` can be used only after the same identity/hash checks. Cache metadata must name the selected protocol explicitly and is never silently rewritten. Missing bundle/cache fails offline.
- `fetch-core --online` alone opts into downloading to that user cache: approved HTTPS release hosts, bounded sizes, exact release/asset metadata, SHA-256 and safe extraction of only the expected executable. The reviewed local manifest supplies the trusted pinned asset digest even if upstream API metadata lacks one; conflicting upstream or explicit digests fail closed. Existing caches are verified, not overwritten; downloads are not executed by this command, and any deliberately retained legacy bundle remains preferred later. The public source contains no executable bundle. The reviewed manifest pins both asset size/hash and extracted executable hash.
- A separately obtained official executable needs an **executable** digest, not the archive digest: `python clients/vpn.py connect vless --core PATH --core-sha256 DIGEST`.
- Acquisition checks used published HTTPS release-asset digests. Offline hashes are not publisher signatures and cannot defend against someone changing both the binary and manifest; obtain the repository from a trusted source.
- Runtime configs contain credentials. They are created after applying user-only Windows ACLs or macOS directory `0700` / file `0600`, and removed on normal exit/Ctrl+C. Abrupt termination can leave protected temporary files. Only owned child processes are stopped; core output is suppressed to avoid credential leakage.
- Browser data uses a separate temporary Chrome/Edge profile, not normal browser settings. Neither local connection nor cleanup changes the server, system routing, system proxy or LAN exposure. If policy blocks execution, use an approved method rather than bypassing it.

For a missing core/hash mismatch, obtain an authorized pinned core or restore trusted cache files rather than executing a changed binary. For missing profiles, verify the selected private file path; never paste credentials into diagnostics. Offline developer checks are listed in the [development guide](DEVELOPMENT.md#offline-checks).

## Speed testing

Use **`/vpn-speed`** for fixed-file downloads or **`/vpn-speed fast`** for the real Fast.com browser. Both share `admin/tools/speed_test.py`; no separate Fast.com skill is needed. Supply your own private bundle with `--profiles-file PATH` or `VPN_PROFILES_FILE` (fallback: ignored `profiles/vpn-profiles.json` under the toolkit root). Use your configured profile IDs, such as `primary` and `secondary`; protocol selection comes from their settings, not geographic names. No method starts or modifies a server.

```bash
python3 admin/tools/speed_test.py --profiles-file /absolute/private/vpn-profiles.json --profiles vless hysteria2 --rounds 3 --label "this-machine-network"
python3 admin/tools/speed_test.py fast --profiles-file /absolute/private/vpn-profiles.json --profiles hysteria2 --label "this-machine-network"
python3 admin/tools/speed_test.py --method fast --dry-run
```

On Windows use `python`. Default method is `file`; leading `file`/`fast` and `--method file|fast` are equivalent. Without `--profiles`, real tests select configured entries from your bundle; `--profiles primary secondary` limits the selection explicitly. File tests use three sequential rounds per selected profile. A dry run does not read credentials; supply profile IDs to obtain a concrete total budget, otherwise selection and total remain unresolved. Tests use verified cached cores, ephemeral loopback ports and private temporary configs, and stop only their own clients/browser. They do not change OS routing/proxies or normal browser profiles. Missing cores are not downloaded automatically.

### Fixed-file method

Requires Python3.11+ and curl8.4+; no extra Python packages or cloud login. Each sample requests `https://proof.ovh.net/files/10Mb.dat`, exactly10MiB. Defaults are3 rounds/profile and20seconds/request, totaling30MiB payload per selected profile (60MiB for two). Maximum5 rounds and30seconds/request, with a200MiB total payload ceiling. TLS/VPN/retransmission overhead is additional. No retries, redirects or fallback endpoints.

Only HTTP200, binary Content-Type, exact expected bytes and successful curl completion count as valid. HTTP errors, HTML/JSON/error pages and short files are invalid data, not low speeds, and stop the remaining suite. Partial timeout rates are diagnostic only; median/min/max use completed samples. Fresh client setup is outside curl timing; request timing includes connection and first-byte wait.

### Fast.com browser method

`speed_test.py fast` opens the actual `https://fast.com/` page, sequentially in isolated headless Chrome/Edge. `--headed` shows it. Requires an already-installed browser and optional Playwright pinned in `admin/tools/requirements-fast-com.txt`; install only in a local virtual environment with permission. No automatic package/browser download. File/help commands do not import Playwright. `fast_com_test.py` remains a backend/compatibility entrypoint, not a second skill.

Defaults: one browser run/profile,55seconds and256MiB **observed response-body bytes per profile**. Maximum120seconds and512MiB/profile, total selected observed budget at most1GiB. `--max-time` and `--max-observed-mib` adjust limits; ask before increasing defaults. Counts use the maximum of decoded and encoded response-body totals, not their sum. They exclude headers, uploads, TLS/VPN overhead, retransmissions and unseen traffic; event timing and in-flight requests can overshoot. **These are not strict wire or billing caps.**

Only a positive completed-page state with recognized Kbps/Mbps/Gbps units is a final score. Progressing, unknown, timed-out or budget-stopped readings stay **provisional**; report stop reason and observed bytes. Do not retry to chase a higher score or click extra upload tests. Fast.com's adaptive parallel transfers use different servers and are not interchangeable with single-file averages.

### Output and interpretation

`--dry-run` validates either plan without reading profiles, starting cores/browsers, creating files or accessing the network. JSON is printed to stdout. Optional file-method `--output .local/speed-tests/<unique-name>.json` saves sanitized results; Fast.com chooses a unique file there by default. Relative output paths resolve under `~/.cache/vpn-skill/runtime/`, so files stay outside installed plugins. Outputs must be new files under that root's `.local/speed-tests/`; symlinks and overwrites are rejected. Never commit measurement JSON or include credentials/raw browser/core logs in support messages.

Report the actual testing computer/network, profile, status, Mbps and duration; for file tests include valid-only median/range. Results measure **this machine → selected VPN → test endpoint**, not automatically another computer, phone, full-device traffic or a different country's route. Keep unrelated traffic quiet. Throughput alone does not establish GFW/ISP interference, congestion or server health. Tests consume egress data; do not schedule repeated tests or raise limits without agreement.

## Export an existing mobile profile

Profile owners can export from the toolkit root using installed Python 3.11+ and their private `VPN_PROFILES_FILE`. No separate local-install step is necessary.

**Windows:**

```powershell
python clients/vpn.py export-mobile --profile hysteria2 --device android --output "$HOME\vpn-mobile-export\hysteria2-android.txt"
python clients/vpn.py export-mobile --profile hysteria2 --device iphone --output "$HOME\vpn-mobile-export\hysteria2-iphone.txt"
```

**macOS:**

```bash
python3 clients/vpn.py export-mobile --profile hysteria2 --device android --output "$HOME/vpn-mobile-export/hysteria2-android.txt"
python3 clients/vpn.py export-mobile --profile hysteria2 --device iphone --output "$HOME/vpn-mobile-export/hysteria2-iphone.txt"
```

Use the exact ID from your bundle with `--profile`, and a corresponding private output filename. The example IDs `vless` and `hysteria2` work only if configured under those names. Hysteria2 profiles may supply separate Android and iPhone URIs; use the matching assigned device profile. An export does not establish endpoint availability. The tool creates a missing dedicated user-only directory, but requires existing parents to pass private-permission checks. Output must be a **new file outside every Git repository**; existing files are not overwritten and credentials are not printed. Read/import the file privately on the owner's device, not in assistant reads or captured terminal output. Ask the server owner for a separately managed credential when independent revocation is needed.

## Convert a configuration to a private QR code

`clients/qr.py` creates a PNG locally from a supported VLESS/Hysteria2 URI file, a repository-format profile bundle, or a supported Xray VLESS/WebSocket/TLS client JSON. It does not contact a QR website, start a client, or change the server. Connection credentials remain in the input and private output files, never terminal output.

Install the optional QR dependency into a local environment, not global Python:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r clients/requirements-qr.txt
.venv/Scripts/python clients/qr.py --input C:/private/client-uri.txt --output C:/private/phone-qr/connection.png --label Personal-VPN
```

For a bundle, explicitly choose its existing alias (`vless` for VLESS):

```powershell
.venv/Scripts/python clients/qr.py --input C:/private/vpn-profiles.json --profile vless --device android --output C:/private/phone-qr/vless.png --label Personal-VPN
```

On macOS/Linux use `.venv/bin/python`. A newly created output directory is protected automatically; an existing directory must already have acceptable private permissions. Output must be a new `.png` outside Git. Never commit QR images, send them to an online generator, or paste their payloads into chat. Anyone scanning one receives the connection credentials.

Open the PNG locally and use the phone VPN application's **Scan QR** import. **A connection QR does not transfer desktop routing, DNS, TUN or China-IP bypass rules.** Configure those separately in the phone app; do not assume scanning a connection code reproduces a desktop routing policy.

## HTTP/SOCKS for another application

A protocol client must run locally or on a trusted gateway. A VLESS/Hysteria2 server is not an ordinary HTTP/SOCKS proxy or built-in IKEv2/L2TP VPN endpoint.

For a repository client without the automatic browser, run from the repository root:

```powershell
python clients/app.py vless --no-browser
```

On macOS use `python3`; replace `vless` with the configured ID of any other connection, including Hysteria2. The browser launcher remains Windows/macOS-only. Keep the terminal running.

| Proxy type | Local endpoint |
| --- | --- |
| SOCKS5, preferably proxy/remote DNS | `127.0.0.1:10808` |
| HTTP / HTTPS CONNECT | `127.0.0.1:10809` |

Configure the desired application, not the remote server address. For example, Firefox supports SOCKS v5 at `127.0.0.1`, port `10808`, with **Proxy DNS when using SOCKS v5**; restore the prior setting afterwards. Other apps may support HTTP at port `10809`. A local ready message proves listeners exist, not remote authentication or leak protection. Stop one client before reusing its ports.

The automatic browser uses a separate temporary Chrome/Edge profile, preferring Chrome. It does not install a browser, change normal profiles or set the OS proxy. Treat its bookmarks/sessions as temporary. The repository clients do not enable TUN, system-wide routing or LAN sharing.

## Terminal networking through Clash

Start Clash and verify its actual **mixed/HTTP port** in settings. The examples below use `7897`, an illustrative port—not a guaranteed default. Generated repository Clash profiles specify `7890` before GUI overrides; the Python launcher uses HTTP `10809`. Do not confuse these endpoints.

### Verify TUN without an explicit proxy

After [enabling TUN](DEVICES.md#enable-tun-in-clash-verge-rev), run a bounded HTTPS request:

```bash
curl --noproxy '*' --connect-timeout 10 --max-time 20 -I https://github.com
```

`--noproxy '*'` disables curl's application-proxy use for this request, **not TUN routing**. Inspect the request in Clash's Connections view and confirm the intended outbound. A successful response alone could also be a direct connection; it does not prove TUN coverage. Avoid sharing raw connection lists or browsing logs. Test a GUI app and needed LAN services separately.

### Explicit proxy for one command

If TUN is unavailable or a tool needs explicit configuration, use a per-command proxy rather than permanent shell exports:

```bash
https_proxy=http://127.0.0.1:7897 curl --connect-timeout 10 --max-time 20 -I https://github.com
```

In Bash/zsh, an assignment before a command applies to that process and its children; it does not permanently change the shell or macOS settings. `https_proxy` tells tools that support it which proxy to use for HTTPS URLs. The `http://` describes the connection to the local HTTP proxy; HTTPS to the destination still uses TLS through CONNECT. Keep certificate verification enabled.

For a tool such as Git, an explicit per-invocation option is another choice:

```bash
git -c http.proxy=http://127.0.0.1:7897 ls-remote https://github.com/Homebrew/brew.git HEAD
```

Downloading an installer and networking performed by the installer are separate steps. If running a trusted, reviewed local installer that invokes compatible tools, pass the environment to the installer itself as needed:

```bash
https_proxy=http://127.0.0.1:7897 /bin/bash /path/to/reviewed-installer.sh
```

The path above is a placeholder, not a repository installation command. Tools can ignore environment variables, use separate configuration or drop them during privilege changes. `https_proxy` does not cover every protocol; HTTP requests may need `http_proxy`, and other tools may require their own settings. Do not assume this guarantees every child process uses Clash.

Keep Clash running while commands depend on its port. Avoid adding persistent proxy settings merely to fix one download: stale variables, shell startup entries or Git proxy settings can break networking after Clash stops. See [terminal troubleshooting](TROUBLESHOOTING.md#terminal-and-tun-problems).

## Share a proxy over the LAN

The repository clients bind to loopback only. Merely entering a computer's LAN IP on another device **does not enable sharing**. Use a sharing-capable client or separately configured controlled forwarder:

### Find the Mac LAN address and listening port

On the Mac that runs the proxy, find the interface used by the default route and then its IPv4 address:

```bash
interface=$(route -n get default | awk '/interface:/{print $2}')
printf 'Interface: %s\nLAN IPv4: ' "$interface"
ipconfig getifaddr "$interface"
```

A result such as `192.168.1.34` is a private LAN address. It can change after reconnecting or when the router renews DHCP; make a **DHCP reservation in the router** if other devices need a stable endpoint. A manual static address in macOS is less portable and can conflict on another network. The default gateway shown by `route -n get default` is the router, not the Mac's proxy address.

With the proxy running, inspect TCP listeners without exposing profile credentials:

```bash
lsof -nP -iTCP -sTCP:LISTEN
```

Interpret the address column carefully:

- `127.0.0.1:PORT` or `[::1]:PORT` is loopback-only and cannot be reached by another device.
- `*:PORT`, `0.0.0.0:PORT`, or `[::]:PORT` normally accepts connections on LAN interfaces, subject to the macOS firewall and application policy.
- A specific `LAN_IP:PORT` accepts connections on that interface.

UDP listeners can be inspected with `lsof -nP -iUDP`, but an HTTP/SOCKS mixed proxy normally needs its TCP listener. Listening does not prove that the firewall permits access or that proxy forwarding works.

### Enable Clash Verge LAN access

In Clash Verge Rev, enable **Allow LAN** in the application's proxy/settings area and note the configured **Mixed Port** (the exact menu label can vary by release). Keep Clash running and confirm that the port now listens on `*`, `0.0.0.0`, `[::]`, or the Mac's LAN address—not only `127.0.0.1`. Enable local proxy authentication if the installed Clash version and receiving device support it; otherwise use this only on a trusted, access-controlled LAN and turn **Allow LAN** off when no longer needed. Do not enable router port forwarding, DMZ, or public exposure.

On the other trusted device, set the HTTP proxy or SOCKS5 proxy to:

```text
Host: <Mac LAN IPv4>
Port: <Clash mixed port>
```

Use the proxy type supported by that device/application. If SOCKS5 offers remote/proxy DNS, enable it. From another computer on the same trusted LAN, verify basic reachability and then actual forwarding:

```bash
nc -vz <Mac-LAN-IPv4> <port>
curl --proxy http://<Mac-LAN-IPv4>:<port> https://example.com/
```

For a SOCKS5-only listener, use `curl --proxy socks5h://<Mac-LAN-IPv4>:<port> https://example.com/`. Test from the second device: testing on the Mac does not detect Wi-Fi client isolation or inbound firewall blocking. If the port is unreachable, follow [LAN troubleshooting](TROUBLESHOOTING.md#symptoms). Do not disable the firewall globally.

1. Bind to the intended trusted LAN interface; restrict the firewall to the receiving device/trusted LAN and required port.
2. Enable local proxy authentication supported by both client and TV. These are **local proxy** credentials, not VLESS/Hysteria2 node credentials. If suitable protection is unavailable, prefer a client on the box.
3. Enter the sharing device's LAN IP, actual port, matching HTTP/SOCKS protocol and local authentication in the receiving application. Do not use the remote server or VPN-interface address.
4. Verify both devices can reach each other; guest Wi-Fi/client isolation or VLANs may block them. Consider a DHCP reservation if the LAN address changes.
5. Keep the sharing device awake and client running for all playback. On phones, check actual background/battery settings, power and behavior after locking the screen.

HTTP/SOCKS may not encrypt the device-to-proxy hop; use a trusted network. **No public port forwarding, DMZ, UPnP or public `10808/10809` openings.** A hotspot does not automatically share a phone's VPN; verify explicit client/system support and the TV's route. iOS VPN does not automatically expose an Android-style LAN proxy either.

No new router is required. A maintained compatible router/gateway can help continuous multi-device use, but architecture, CPU, memory and QUIC/UDP performance need checking. A “VPN router” label is not a speed guarantee or authorization to purchase/flash hardware.
