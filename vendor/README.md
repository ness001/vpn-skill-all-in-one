# Pinned VPN core release links

This directory contains official release links, pinned versions, integrity metadata and license/source notices. Third-party executables and release archives are **not included** in Git.

[manifest.json](manifest.json) records Xray `v26.3.27` and Hysteria `app/v2.12.3` for Windows x64, macOS Intel and Apple Silicon, including official URLs, release-asset SHA-256/size and extracted executable SHA-256/size. These pins were recorded from verified official releases; changing metadata is not a repair for a checksum failure.

## Explicit acquisition

With Python 3.11+ installed, authorize only the protocol needed:

```bash
python3 clients/vpn.py fetch-core vless --online
python3 clients/vpn.py fetch-core hysteria2 --online
```

Run commands from the repository root. Downloads use reviewed official HTTPS hosts, bounded transfers and pinned size/hash checks; only the expected executable is extracted safely. This command never executes it. Runtime files use `~/.cache/vpn-skill/runtime/.tools`, outside Git. Subsequent `fetch-core` without `--online` verifies the cache offline. Existing invalid bundles/caches fail closed and are not overwritten. Normal connection and speed commands never download silently.

Xray geolocation databases, helper scripts and Wintun are not installed by the proxy-only client path. Python and browsers are separate prerequisites. Platform hashes do not establish actual device acceptance.

## Licenses and corresponding source

- Xray: [MPL-2.0](licenses/xray/LICENSE), [notice](licenses/xray/NOTICE.txt), [release](https://github.com/XTLS/Xray-core/releases/tag/v26.3.27), [tagged source](https://github.com/XTLS/Xray-core/tree/v26.3.27), [source archive](https://github.com/XTLS/Xray-core/archive/refs/tags/v26.3.27.tar.gz).
- Hysteria: [MIT](licenses/hysteria/LICENSE), [notice](licenses/hysteria/NOTICE.txt), [release](https://github.com/HyNetworks/hysteria/releases/tag/app/v2.12.3), [tagged source](https://github.com/HyNetworks/hysteria/tree/app/v2.12.3), [source archive](https://github.com/HyNetworks/hysteria/archive/refs/tags/app/v2.12.3.tar.gz).

Upstream license bytes and archived release notices remain preserved under `licenses/`; retaining Wintun's notice does not distribute its DLL. Source URLs provide corresponding Source Code Form under the upstream terms. No upstream endorsement is implied.

## Maintenance

[../admin/tools/vendor_refresh.py](../admin/tools/vendor_refresh.py) creates a new candidate containing official release **metadata only** with explicit `--online --output PATH`; it never reconstructs public release bytes. Review extracted-binary hashes, licenses and source references before integrating new pins. See [vendor maintenance](../skills/vpn-vendor-update/SKILL.md).
