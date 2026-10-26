# Fresh server installation

**One entry point, two protocols.** Run on a **new Ubuntu 22.04 or 24.04 LTS amd64/x86_64 server with systemd and Python 3.10+**, on any hosting provider or a suitable standalone host. Select `vless` or `hysteria2`; neither requires Azure or a geographic region. This is server-only support, not Ubuntu desktop browser-launcher support. Other distributions/releases and ARM are refused. This installs server software; it does not create a VM or connect your desktop.

**Do not run on existing production machines.** Existing VPN/web-server services, occupied ports, foreign configuration and ownership conflicts cause a refusal. This is not an upgrade/uninstall tool.

| Profile | Software | Public inbound ports | Private core |
| --- | --- | --- | --- |
| `vless` | Xray 26.3.27 VLESS/WebSocket + Caddy TLS | TCP 80, TCP 443 | Xray `127.0.0.1:39761` |
| `hysteria2` | Hysteria2 2.12.3, adaptive BBR | UDP 443; TCP 443 for ACME issuance/renewal | Authenticated QUIC proxy |

Only explicit protocol names are accepted. Deployment-specific compatibility and migrations belong in private administration adapters. This installer never migrates deployed directory or service identities.

## Prepare once

1. Obtain approval for the server, public IPv4, DNS, firewall changes and ongoing compute/egress charges. This installer creates **no cloud resources** and uses no Azure/DNS-provider credentials.
2. Provision a fresh standard Ubuntu image. Keep your existing secure management path. Use a static public IPv4 routed/NATed to the server; private VM interfaces behind cloud NAT are normal.
3. Create a **DNS-only public A record** pointing directly to that IPv4. Remove AAAA records: this installer does not configure IPv6. Public DNS, not just `/etc/hosts`, must agree. CAA records, if present, must allow Let's Encrypt and Caddy's configured ACME issuers. Do not orange-cloud/CDN-proxy the record.
4. Open the profile's public ports in the **cloud firewall/NSG** and any host firewall. Leave SSH/management rules unchanged. No need to expose TCP 39761. Hysteria2 does not need TCP 80.
5. Copy only `admin/install-server.sh` and `admin/installer/` together to the server, or use a clone of this toolkit. No client credential repository file is read. Outbound DNS/HTTPS access to Ubuntu mirrors, GitHub and ACME is needed. Python 3.10+ is included in standard Ubuntu 22.04/24.04 images. The installer requires `apt-get`, `systemctl`, `systemd-analyze`, `ss`, `useradd` and `runuser`, plus a systemd-booted host; minimized images missing these prerequisites are refused rather than silently bootstrapped.

## One command

From the repository directory, replace the domain and IPv4 below with your own values:

```bash
sudo bash admin/install-server.sh --profile vless --domain vpn.example.com --public-ip 1.2.3.4 --email admin@example.com --yes
```

Or choose Hysteria2 on a **different fresh server**:

```bash
sudo bash admin/install-server.sh --profile hysteria2 --domain vpn.example.com --public-ip 1.2.3.4 --email admin@example.com --yes
```

Email is optional. `--yes` authorizes the described local installation and public ACME account/certificate issuance, including the CA's terms. Public certificates are normally recorded in certificate-transparency logs; the hostname is not secret. Without `--yes`, a terminal wizard requests missing fields and confirmation. In noninteractive mode, profile/domain/public IPv4 are required.

**Safe preview** (also works with Git Bash and Python on Windows; no sudo needed):

```bash
bash admin/install-server.sh --profile vless --domain vpn.example.com --public-ip 1.2.3.4 --yes --dry-run
```

Dry-run validates input shape and an explicitly supplied credential file, but **does not resolve DNS, check remote reachability, install anything, generate secrets, write state or require root**. Real installation enforces Ubuntu/architecture/systemd, public DNS resolution, ownership and port checks before installing packages.

### Host firewall

Default: **no firewall changes**. If UFW is already active, you can append `--configure-firewall` to explicitly allow only the profile's VPN ports. This never enables/resets UFW, changes its default policy, deletes a rule, edits SSH or closes management access. It does not manage other firewalls or cloud NSGs. An already-completed install is read-only on retry, including its firewall; manage any later firewall change separately.

## What is installed

- Only `apt-get update` and `apt-get install --no-install-recommends ca-certificates`; **no full OS upgrade, reboot, kernel tuning, NAT, IP forwarding, Docker, TUN or panel**.
- Version-pinned official upstream releases with pinned SHA256; mismatches stop before executing binaries. Source URLs/hashes are in `installer/install.py`; versions are in `installer/render.py`. Binaries reside under `/opt/personal-vpn/<core>/<version>/`.
- Dedicated non-login `xray`/`caddy` or `hy2` system users. Xray has no capabilities; Caddy/Hy2 have only `CAP_NET_BIND_SERVICE`. Systemd hardening and private root-owned configuration files (`0640`, readable only by the relevant service group).
- VLESS units: `personal-vpn-xray.service`, `personal-vpn-caddy.service`; Hysteria2: `personal-vpn-hy2.service`. Unrelated services are not replaced. Configuration paths remain `/etc/personal-vpn/vless/` (VLESS) and `/etc/personal-vpn/hysteria2/` (Hysteria2), using the selected protocol.
- Private destination, loopback, link-local, multicast, IMDS and Azure WireServer proxy access blocked in core routing/ACL; this does not change the host Azure Agent's networking. The known-bad `reject(::ffff:0:0/96)` rule is deliberately absent.
- Generated client UUID/path/password and strict-TLS client exports under `/root/personal-vpn/vless/` (VLESS) or `/root/personal-vpn/hysteria2/` (Hysteria2): `client-uri.txt`, `client.json`, `credentials.json`, `inventory.json`. Parent directory `0700`, files `0600`. Secrets are never printed or passed as CLI arguments. Retrieve only through your existing authorized private management/file-transfer path; never paste into tickets or commit generated files.

The client JSON is a native Xray or Hysteria2 configuration with a **loopback-only SOCKS listener on 1080**, not a GUI configuration or automatic update to this repository's launcher. Import the private URI into a compatible client, or convert either `client-uri.txt` or `client.json` locally on the intended client computer:

```bash
python3 clients/import_profile.py --input /absolute/private/client.json --name my-server --output "$HOME/vpn-private-bundle/vpn-profiles.json"
```

Use `python` on Windows. This detects either installer's protocol and creates one validated toolkit profile without printing credentials, connecting or changing the server. It requires a new private `.json` output outside every Git repository and does not overwrite/merge existing bundles. See [supported inputs and profile format](../profiles/README.md#import-installer-exports), then [client setup](../skills/vpn-client-setup/SKILL.md). New installs do not silently reuse production credentials.

## Retry and failure handling

Run the **same command with the same domain/IP/email** to retry. The saved target identity, export labels, configuration and paths stay unchanged. Saved credentials are reused; completed owned installs verify recorded file hashes/ownership and print status without rotating secrets, restarting services or changing files. Different target settings, externally edited configuration or unowned files are refused. There is no destructive `--force` option.

Root-only state/logs are under `/var/lib/personal-vpn-installer/` (`0700`). Installation commands and native validators log privately to `install.log`; service output goes to `personal-vpn-*.log` in the same directory. These logs may contain private information: inspect locally as root, share only sanitized summaries. They are not automatically rotated by this minimal installer; configure retention as a follow-up maintenance step and monitor disk usage. Systemd's lifecycle messages remain available in its normal journal.

Failure leaves owned state/configuration and private logs for diagnosis; it does **not** attempt a broad cleanup, rollback or removal of unrelated files. A rare interruption between creating an object and recording its ownership fails closed on retry and needs private manual review. Do not delete state or rerun onto a different service. A currently running partial installation may continue running after a failed retry.

Validation includes Xray's native test, Caddy's native validate, systemd unit verification and active/listener checks. **Hysteria2 has no standalone config-check flag**: configuration is parsed during actual startup. Caddy certificate issuance may be asynchronous. Startup/listeners alone do not establish strict-TLS authenticated forwarding, invalid-auth rejection, mobile browsing, performance, future renewal or reboot recovery. Verify those separately with explicit scope before retiring any previous server. No live server or remote end-to-end acceptance is claimed by this source's local tests.

## Explicit credential-preserving migration

Migration requires separate approval for the new infrastructure and later DNS/cutover changes. Keep the old server working until the replacement passes strict-TLS authenticated/invalid-auth checks. Preserving credentials means anyone with an old copy retains access; rotate separately if that is not intended.

Prepare a **local root/invoking-user-owned mode-0600 JSON file** using a private editor/transfer, not command-line arguments, shell history or terminal output. The installer accepts only these schemas (placeholders below are not usable credentials):

VLESS, to preserve an existing client UUID and WebSocket path:

```json
{"uuid":"REPLACE_WITH_EXISTING_UUID","ws_path":"/REPLACE_WITH_EXISTING_PATH"}
```

Hysteria2 password auth:

```json
{"password":"REPLACE_WITH_EXISTING_PASSWORD"}
```

Hysteria2 user/password auth, if the existing client's auth is `username:password`:

```json
{"username":"existing-device","password":"REPLACE_WITH_EXISTING_PASSWORD"}
```

Append `--credentials-file /root/private-migration.json` to the installation command. Supported VLESS paths use `/` followed by 8–200 letters/digits/slashes/underscores/hyphens; Hysteria2 passwords are 16–256 printable ASCII characters without spaces. Unsupported existing settings are refused, not silently changed. One Hysteria2 credential (optionally one username) is supported, not a multi-device account migration. Do not pass the repository's entire profile JSON; the schemas are intentionally narrow.

For a cutover preserving the original hostname, the new server must already receive that hostname's public DNS/ACME traffic when this installer runs. DNS changes and downtime planning are **not automated**; copying credentials alone cannot preserve hostname/TLS reachability. A temporary new hostname instead requires a client update. Never run this installer over the old production installation.

## Local developer checks

```bash
python -B -m unittest discover -s admin/installer -p 'test_*.py' -v
bash -n admin/install-server.sh
```

Tests use fake credentials and mocked platform checks for Ubuntu 22.04/24.04, unsupported OS/releases/architectures, root/Python/systemd/base tools, explicit protocols, neutral service paths, DNS/port refusal, private retry semantics and safe dry-run behavior. Linux file-permission checks are skipped on Windows. No test provisions a VM or runs the real installer. These checks are not live Ubuntu installation, forwarding, renewal or reboot acceptance.

The optional Azure template in `infra/vpn/` remains a separate provisioning path with its pinned Ubuntu 24.04 image; the server installer itself does not require it. Its location follows the resource group unless explicitly supplied, and example parameters require an approved region instead of assuming one. Template contract tests require the official Azure CLI/Bicep compiler; do not substitute a mock compiler for deployment validation.
