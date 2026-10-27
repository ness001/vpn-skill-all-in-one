# Device and app setup

[Home](../README.md) · [Concepts](CONCEPTS.md) · [Client operations](CLIENTS.md) · [Troubleshooting](TROUBLESHOOTING.md)

Choose/install a compatible client, import an assigned profile and test the actual device. Shared routing, GeoIP, DNS, privacy and LAN concepts are in [VPN concepts](CONCEPTS.md), not specific to phones or TVs. Supply your own reachable server and private profile. Normal client connection does not provision a server or require cloud/SSH access.
## Choose a client

| Device | Official source | Guidance |
| --- | --- | --- |
| Windows GUI | Official **v2rayN** or **Clash Verge Rev**: choose Desktop GUI installers in VPN | Check upstream .NET/WebView2 requirements. Use the package for your CPU/OS. |
| macOS GUI | Official **v2rayN** or **Clash Verge Rev**: choose Desktop GUI installers in VPN | Choose the upstream Intel/Apple Silicon package; minimum OS versions differ. Verify behavior on the intended device. |
| Linux GUI | `python3 clients/gui.py` for official **v2rayN** or **Clash Verge Rev** | Choose an upstream package compatible with your distribution and CPU. |
| Android | [v2rayNG releases](https://github.com/2dust/v2rayNG/releases) | Choose a build supporting VLESS/WebSocket/TLS. |
| Android Hysteria2 | [Hiddify releases](https://github.com/hiddify/hiddify-app/releases/latest) | Choose a build supporting your Hysteria2 settings; test actual browsing. |
| iPhone / iPad | [Hiddify](https://hiddify.com/app/) or [Shadowrocket](https://apps.apple.com/app/shadowrocket/id932747118) | Compatible builds support these protocols; test actual iOS operation. |

Official compatibility references include the [Hysteria client directory](https://v2.hysteria.network/docs/getting-started/3rd-party-apps/) and app release notes. Features, prices, minimum OS and regional availability vary; mainland China App Store availability is not guaranteed. No purchase or account-region change is required by this guide. A compatibility listing is not a device acceptance test.

### How to choose a desktop client

- **Xray core / CLI:** direct VLESS/WebSocket/TLS configuration for scripts, terminal use and application proxies; no graphical interface.
- **Hysteria2 core / CLI:** direct Hysteria2 connections for terminal use or automation; requires a compatible UDP/QUIC path.
- **v2rayN:** a graphical way to import links and manage connection profiles through supported cores. Start here when you prefer a profile-oriented desktop interface and the current release supports your system/protocol.
- **Clash Verge Rev:** a graphical Mihomo client for routing rules, proxy groups and configurable TUN/system-proxy coverage. Choose it when those routing controls match your needs.

Reuse an installed compatible client first. Otherwise, check the release's OS/CPU and runtime requirements, then choose by workflow rather than assuming a different interface will improve speed. The client setup skill explains the relevant options and recommends one before asking for installation.

## Desktop GUI setup

Run `python3 clients/gui.py` (or choose **Desktop GUI installers** in a private launcher) to show official [v2rayN releases](https://github.com/2dust/v2rayN/releases) and [Clash Verge Rev releases](https://github.com/clash-verge-rev/clash-verge-rev/releases). The helper does not download packages or read credentials by default.

Install the upstream package for your operating system/CPU manually, following its current requirements and integrity guidance. Keep normal OS security checks enabled. Windows builds may require [.NET](https://dotnet.microsoft.com/download) or [Microsoft WebView2](https://developer.microsoft.com/microsoft-edge/webview2/); Linux builds require compatible distribution libraries. Check upstream release notes for minimum macOS versions and architecture support.

For an installed client, explicitly export imports from your private bundle:

```bash
python3 clients/gui.py --app v2rayn --profiles-file /absolute/private/profiles.json --export-profiles
python3 clients/gui.py --app clash-verge-rev --profiles-file /absolute/private/profiles.json --export-profiles
```

Exports go to a fresh directory under `~/Downloads/VPN-GUIs/`, outside Git; `--output-dir PATH` selects another private parent. `--open-folder` opens only that exported folder when requested. Python 3.11+ is required for export, not for the installed GUI. No installer/client is launched and no system proxy/routing setting is changed. Versions, package hashes and third-party licenses remain upstream rather than in this repository.

### Import the prepared connections

- **v2rayN:** extract/install the package, then import the private `VPN-v2rayN.txt` links using the app's file/clipboard import. Choose an available endpoint supplied by your server owner. If using system-proxy mode, disable it again when you stop the GUI.
- **Clash Verge Rev:** import the private `VPN-Clash.yaml` as a **local profile**, enable it, and select your available endpoint under the VPN group. The explicit YAML preserves each VLESS connection's WebSocket settings; it does not rely on URI auto-conversion.

Keep Clash in **Rule** mode for this repository’s [China GeoIP bypass policy](CONCEPTS.md#how-this-repositorys-china-bypass-works). Existing imports need updating or re-importing; URI-only v2rayN/mobile imports do not contain that rule set.

The generated files contain credentials. Keep them private and outside Git. Exporting them copies existing credentials; it does not provision another user.

A download or profile export is not proof of GUI operation on a particular device. Verify installation, authenticated forwarding and the intended applications on your own platform.

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
