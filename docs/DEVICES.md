# Device and app setup

[Home](../README.md) · [Concepts](CONCEPTS.md) · [Client operations](CLIENTS.md) · [Troubleshooting](TROUBLESHOOTING.md)

Choose/install a compatible client, import an assigned profile and test the actual device. Shared routing, GeoIP, DNS, privacy and LAN concepts are in [VPN concepts](CONCEPTS.md), not specific to phones or TVs. Supply your own reachable server and private profile. Normal client connection does not provision a server or require cloud/SSH access.
## Choose a client

| Device | Official source | Guidance |
| --- | --- | --- |
| Windows GUI | Official **v2rayN** or **Clash Verge Rev**: choose Desktop GUI installers in VPN | v2rayN includes .NET; Clash may need the separately linked Microsoft WebView2 installer. Use the package for your CPU/OS. |
| macOS GUI | Official **v2rayN** or **Clash Verge Rev**: choose Desktop GUI installers in VPN | Intel/Apple Silicon DMGs; minimum OS versions differ. Verify behavior on the intended device. |
| Linux GUI | `python3 clients/gui.py` for official **v2rayN** or **Clash Verge Rev** | x64 ZIP/DEB; compatible system libraries must already be installed for offline use. |
| Android | [v2rayNG releases](https://github.com/2dust/v2rayNG/releases) | Choose a build supporting VLESS/WebSocket/TLS. |
| Android Hysteria2 | [Hiddify releases](https://github.com/hiddify/hiddify-app/releases/latest) | Choose a build supporting your Hysteria2 settings; test actual browsing. |
| iPhone / iPad | [Hiddify](https://hiddify.com/app/) or [Shadowrocket](https://apps.apple.com/app/shadowrocket/id932747118) | Compatible builds support these protocols; test actual iOS operation. |

Official compatibility references include the [Hysteria client directory](https://v2.hysteria.network/docs/getting-started/3rd-party-apps/) and app release notes. Features, prices, minimum OS and regional availability vary; mainland China App Store availability is not guaranteed. No purchase or account-region change is required by this guide. A compatibility listing is not a device acceptance test.

## Desktop GUI setup

Run `python3 clients/gui.py` (or choose **Desktop GUI installers** in a private launcher) to list official pinned installer links. This default does not download or export credentials. After authorizing the selected download, use:

```bash
python3 clients/gui.py --app v2rayn --download --export-profiles
python3 clients/gui.py --app clash-verge-rev --download --export-profiles
```

Supply your private bundle using `--profiles-file PATH` or `VPN_PROFILES_FILE`. The explicit download verifies the full package size/SHA-256 and prepares imports; output defaults to `~/Downloads/VPN-GUIs/`, outside Git. Existing files are verified, never overwritten. Python 3.11+ is required for preparation, not for the installed GUI. Nothing runs installers, elevates privileges or changes system settings. Use only your OS/CPU package. The repository contains links and notices, not third-party release bytes.

### Pinned versions and platforms

| Client | Version | Windows | macOS | Linux |
| --- | --- | --- | --- | --- |
| v2rayN | 7.24.9 | x64 portable ZIP; .NET runtime included | Intel and Apple Silicon DMG; macOS13.6+ | x64 portable ZIP; compatible modern desktop libraries required |
| Clash Verge Rev | v2.5.2 | x64 installer plus Microsoft-direct offline WebView2 companion | Intel and Apple Silicon DMG; macOS12+ guidance | x64 Debian/Ubuntu `.deb`; system GTK/WebKit dependencies required |

**Linux is not universally dependency-free.** The packages include application/core binaries, not every distribution's native libraries. v2rayN was built on Ubuntu24.04; Clash requires compatible WebKitGTK4.1/GTK3/OpenSSL/Ayatana libraries already installed for a fully offline install. No Linux ARM package is currently listed.

For Clash on Windows, install **Microsoft WebView2 Evergreen Standalone x64 153.0.4234.48** first if missing, then Clash. Its companion URL points directly to Microsoft; download validation checks the reviewed size/hash, not a fresh Authenticode signature. Microsoft's separate license/notice references remain in `vendor/gui/licenses/`. Keep normal OS security checks enabled. No installer is executed automatically.

### Import the prepared connections

- **v2rayN:** extract/install the package, then import the private `VPN-v2rayN.txt` links using the app's file/clipboard import. Choose an available endpoint supplied by your server owner. If using system-proxy mode, disable it again when you stop the GUI.
- **Clash Verge Rev:** import the private `VPN-Clash.yaml` as a **local profile**, enable it, and select your available endpoint under the VPN group. The explicit YAML preserves each VLESS connection's WebSocket settings; it does not rely on URI auto-conversion.

Keep Clash in **Rule** mode for this repository’s [China GeoIP bypass policy](CONCEPTS.md#how-this-repositorys-china-bypass-works). Existing imports need updating or re-importing; URI-only v2rayN/mobile imports do not contain that rule set.

The generated files contain credentials. Keep them private and outside Git. Exporting them copies existing credentials; it does not provision another user.

A hash-verified download is not proof of GUI operation on a particular device. Verify installation, authenticated forwarding and the intended applications on your own platform.

### Enable TUN in Clash Verge Rev

1. Select an available configured endpoint and keep **Rule** mode for the configured China bypass.
2. Open **Settings → System Setting → Tun Mode** and enable it. Labels/locations can vary by release.
3. If prompted, install or enable the app's service/helper (sometimes called **Service Mode**) and approve the administrator prompt locally. Never share the password in chat or disable OS security controls.
4. **System Proxy may stay enabled at the same time.** See [how they coexist](CONCEPTS.md#can-both-be-enabled); disabling it is optional, not a requirement.
5. Avoid conflicting VPN/TUN clients. Verify [terminal networking](CLIENTS.md#terminal-networking-through-clash), GUI browsing and any needed LAN printers/shares. A toggle alone does not prove working routes or DNS.

**Allow LAN is separate:** leave it off unless intentionally sharing the proxy with another device. TUN does not require Allow LAN. If sharing is needed, follow [protected LAN setup](CLIENTS.md#share-a-proxy-over-the-lan).

If TUN causes problems, turn it off in Clash and retest with the prior working System Proxy or explicit app-proxy settings. Do not leave applications pointing at a stopped proxy or manually delete system routes as a first troubleshooting step.

## Import and connect

1. Install the official package matching the device. Extract desktop ZIPs before running; follow the release's runtime/core requirements.
2. Obtain **your assigned private profile**. Import its file, clipboard link or offline-generated QR by a method supported in that app version; menu names differ.
3. Select your assigned endpoint, retaining all authentication, hostname/SNI, port and transport settings. VLESS/WebSocket/TLS and Hysteria2/QUIC require compatible client settings. Do not substitute an IP for the TLS hostname or disable certificate verification.
4. On Android/iOS, allow the trusted app's VPN configuration when prompted; run one VPN app at a time. On desktop GUI clients, choose the intended supported system-proxy or VPN/TUN mode. See [traffic coverage versus routing mode](CONCEPTS.md#routing-mode-versus-traffic-coverage).
5. Test `https://example.com` and the intended app on the intended Wi-Fi/cellular network. A connected icon or latency result is insufficient.
6. Disconnect in the client and restore any manual OS/app proxy settings when finished.

Links and QR codes are credentials. Import privately, avoid cloud-synced exports/clipboard and public QR services, and remove unnecessary copies. Keep profiles and generated files outside public repositories. Ask the server owner to revoke or rotate credentials when needed; deleting an export does not revoke access. An export copies an existing credential; it does not create an independently revocable user.

For private mobile exports, use [client operations](CLIENTS.md#export-an-existing-mobile-profile). For connection-without-browsing symptoms, see [troubleshooting](TROUBLESHOOTING.md).

## TV boxes and SmartTube

**SmartTube's HTTP/SOCKS fields cannot speak VLESS or Hysteria2.** Do not enter the remote server address, port 443 and node password there.

| Where the compatible client runs | SmartTube endpoint |
| --- | --- |
| On the TV box | `127.0.0.1` and the client's actual local HTTP/SOCKS port |
| On a PC, phone or router | That device's reachable **LAN IP** and deliberately protected shared-proxy port |
| On a box/router using verified VPN routing | Usually leave SmartTube's duplicate proxy disabled; test the actual route |

See [loopback and LAN addresses](CONCEPTS.md#localhost-lan-and-public-addresses). Android apps do not necessarily use ports `10808/10809`.

### Client on the box

Check Android version, CPU architecture and protocol support. Import the assigned profile and test HTTPS before configuring SmartTube. If the app exposes a local proxy, match HTTP versus SOCKS and its actual port. If it supports only Android VPN mode, test SmartTube through that mode without a second proxy setting. Moving an unverified phone configuration onto a TV is not proof of compatibility.

For a client on another computer, phone or router, follow [protected LAN sharing](CLIENTS.md#share-a-proxy-over-the-lan), including Mac IP/listener checks and Clash Allow LAN setup.
