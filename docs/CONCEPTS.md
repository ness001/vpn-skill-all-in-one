# VPN concepts

[Home](../README.md) · [Client operations](CLIENTS.md) · [Device setup](DEVICES.md) · [Troubleshooting](TROUBLESHOOTING.md)

Shared concepts belong here, regardless of operating system or client. App-specific controls belong in the device guide; commands and procedures belong in client operations.

## Client, server, core and profile

- A **server/node** is the remote VPN endpoint. Supply your own VLESS over WebSocket/TLS or Hysteria2 over QUIC/TLS endpoint. Choose any safe profile ID and specify its `vless` or `hysteria2` protocol; labels identify your configured connections, not supplied servers or required regions.
- A **client** authenticates to a node and forwards traffic. A **core** is its networking engine; a **GUI** is the graphical app controlling it. Software licenses are legal notices, not activation keys.
- A **connection profile** supplies protocol, endpoint, credentials and TLS/transport settings. A URI import usually carries connection details, not a complete routing/DNS policy.
- **HTTP/SOCKS** are interfaces an application can use to reach a running client. They are not interchangeable with the VLESS/Hysteria2 server protocol. A VLESS/Hysteria2 endpoint is not an ordinary HTTP/SOCKS or built-in IKEv2/L2TP endpoint.

## Routing modes and split tunneling

Routing decides **where a connection goes** after it reaches the client. Rule-based routing is a form of **split tunneling**: some destinations use the VPN, while others use the normal internet connection. Names and available controls vary by app; these modes describe Clash, not a feature guaranteed in every VPN.

| Clash mode | What happens to traffic handled by Clash | Everyday use |
| --- | --- | --- |
| **Rule** | Evaluates the configured rules in order; the first match chooses DIRECT, a proxy group or another action. | Recommended for this repository's China-bypass policy. |
| **Global** | Ignores the routing rules and uses the outbound selected in the Global selector. Select a VPN node there to proxy all handled traffic. | Temporary all-proxy troubleshooting; China bypass is not applied. |
| **Direct** | Sends handled traffic through the normal connection without the VPN. | No VPN protection for that traffic; does not turn off the client or restore OS proxy settings. |

### GeoIP bypass is a routing policy

**GeoIP** maps destination IP ranges to country/region codes. A bypass rule selects a direct connection for matching destinations rather than sending them through the VPN. This is a general client/router routing concept, not a phone or Clash-only feature. Rule mode by itself does not mean “bypass China”: the configured rules determine which destinations are direct, proxied or blocked. Different clients require their own compatible rule sets and databases.

### How this repository's China bypass works

Clash exports contain these ordered rules:

```yaml
mode: rule
rules:
  - GEOIP,CN,DIRECT
  - MATCH,VPN
```

1. For a hostname, Clash resolves the destination as needed to evaluate the GeoIP rule.
2. If the destination IP matches **CN** in the GeoIP database, Clash connects **DIRECT** through the local internet connection.
3. Otherwise, the final **MATCH** rule sends the connection through the **VPN** selector's chosen node. Select an available endpoint from your private profiles.

This classifies the **destination IP**, not the website's language, owner or domain suffix. A `.cn` site hosted outside mainland China can still use the VPN, and a `.com` site on a mainland China IP can go direct. Hong Kong and other non-CN entries are not included in this bypass. Database age, DNS answers and CDN locations can affect the result; keep the client's GeoIP data maintained.

**Privacy:** direct destinations see the normal public IP, not the VPN exit IP. Direct connections are not carried inside the VPN tunnel; HTTPS still protects HTTPS content. DNS privacy depends on the client's DNS configuration—Rule mode alone does not guarantee DNS goes through the VPN.

### Routing mode versus traffic coverage

- **System proxy / application proxy:** only applications honoring that proxy send traffic to Clash.
- **TUN / device VPN:** captures traffic according to OS routing, app exclusions and client settings; it does not automatically mean Global mode.
- **Rule / Global / Direct:** decides how the captured traffic leaves Clash. Rule mode can work with either system proxy or TUN.

The repository's **Python launcher** opens a separate proxy browser and does not inherit Clash's routing policy. **v2rayN/mobile URI imports** contain connection details, not this rule set; configure routing separately in those apps. Existing Clash imports need updating or re-importing to acquire new rules.

## System proxy and TUN

**TUN** is short for **tunnel** (often called a network tunnel). A TUN interface is a virtual network interface handling IP packets. In Clash, TUN mode routes traffic into the client at the network layer rather than requiring each application to speak HTTP/SOCKS. It is not a VPN server protocol or an automatic switch to Global mode.

### Why terminal tools may ignore system proxy

The macOS system proxy is a setting applications can consult, not forced packet routing. Safari and many GUI apps use networking APIs that honor it. Tools such as curl and Git generally use their own networking libraries and proxy configuration; they may instead require environment variables or tool-specific options. A working browser therefore does not prove terminal traffic reaches Clash.

TUN can cover both GUI apps and terminal tools without individual proxy settings, subject to routes, DNS, IPv4/IPv6 coverage and exclusions. **Global mode** only controls traffic already reaching Clash; it does not force otherwise-uncovered apps into the client.

### Can both be enabled?

**Yes: System Proxy and TUN can be enabled together in Clash Verge Rev.** Proxy-aware apps can use the explicit proxy, while TUN covers other traffic according to its routing settings. A correctly configured client avoids capturing its own outbound traffic recursively; enabling both does not normally create a second VPN tunnel or double encryption.

There is no requirement to disable System Proxy when TUN works. Keeping both is reasonable if applications work correctly; disabling System Proxy is an optional simplification after verifying TUN coverage. Neither toggle replaces **Rule** mode: with this repository's policy, handled CN destinations still go direct and other destinations use the selected proxy. GUI apps normally work, but other VPNs, app-specific proxies and local-network services can conflict.

### Performance and trade-offs

TUN itself usually adds modest processing overhead, not a fixed speed penalty. Actual performance depends on the device, traffic volume, implementation, VPN server distance/load and network quality; it must be measured on the intended setup.

- **More traffic:** background apps and downloads may now use the VPN, competing for bandwidth and increasing server egress costs.
- **CPU and battery:** handling more traffic and encrypting proxied connections uses resources.
- **Compatibility:** DNS, IPv6, local printers/shares and other VPNs can need routing or exclusion adjustments.
- **Permissions:** managing virtual interfaces and routes usually requires an administrator-approved helper/service.
- **Broader failure impact:** a client crash or unreachable node can disrupt more applications. Whether traffic fails closed, reconnects or goes direct depends on configuration; TUN is not inherently a kill switch.

China GeoIP bypass avoids an overseas detour for matching destinations, but does not guarantee speed or perfect classification. No mode can prevent every proxy, DNS, certificate or connectivity error. Test browser, terminal and needed LAN access before relying on it. See [Clash setup](DEVICES.md#enable-tun-in-clash-verge-rev) and [terminal verification](CLIENTS.md#terminal-networking-through-clash).

## DNS and destination addresses

DNS translates hostnames into IP addresses. **Local DNS** resolves through the device's resolver path; **proxy/remote DNS** asks the proxy side to resolve instead. The actual resolver and route depend on the client configuration. Resolving domains for GeoIP matching can affect DNS privacy and which CDN endpoint is chosen.

Clash may use synthetic (fake-IP) answers internally while retaining the original hostname for routing. Do not infer the final geographic destination from a synthetic address alone; inspect the matched rule and outbound. SOCKS5 remote DNS is an application option, not a guarantee that every app or client resolver uses the VPN.

## Localhost, LAN and public addresses

**Loopback** (`127.0.0.1` or `::1`) means the device using the address. On a TV it means the TV, not a nearby computer. **LAN IP** means the sharing device's reachable address on the local network; the default gateway is usually the router, not that device. **Public/exit IP** is the address a remote service sees.

A listener bound to loopback cannot be used by another device. Binding to a LAN address or all interfaces permits listening beyond loopback, but firewall rules and network isolation still control access. A listening port does not prove authenticated forwarding works. DHCP can change a LAN address; a router DHCP reservation can provide stability.

LAN sharing is a separate, deliberate capability—not a consequence of selecting Rule mode, entering a LAN IP, or enabling a phone hotspot. Local HTTP/SOCKS traffic may be unencrypted. Use trusted networks and access controls; never expose an unauthenticated proxy publicly. See [protected LAN sharing](CLIENTS.md#share-a-proxy-over-the-lan).

## Credentials and trust

Keep TLS verification enabled. Profiles, import links and QR codes can contain working credentials; exporting one copies access rather than creating an independently revocable account. Direct routing and DNS privacy are explained above; using a VPN does not automatically protect traffic that never reaches it.

This public toolkit contains no working credentials. Keep your [private profiles](../profiles/README.md) and exports out of Git. Removing a file or repository access does not revoke copied credentials; revocation requires a server-side change by the owner. Do not paste credentials, QR payloads or raw browsing logs into support messages.
