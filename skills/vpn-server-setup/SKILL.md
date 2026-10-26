---
name: vpn-server-setup
description: Set up a fresh VLESS or Hysteria2 server using the existing Ubuntu installer, with target verification, scoped authorization and private client handoff.
---

# VPN server setup

## Prepare helpers on first use

No manual helper installation or environment variable is required. Use one shared source checkout for all five skills. Before running any workflow:

1. Locate a complete root in this order: an optional absolute `VPN_SKILL_ROOT` supplied by the user; two parents above this loaded skill directory (full plugins/checkouts); the current working directory and its parents, checking each directory itself and its `toolkit` child; then `~/.cache/vpn-skill/source` (`$HOME\.cache\vpn-skill\source` on Windows). Only accept a root containing `admin/tools/skill_root.py`, `plugin.json`, `clients/vpn.py`, `admin/install-server.sh`, `admin/tools/speed_test.py`, `admin/tools/guest_diagnostics.sh`, `docs/CLIENTS.md`, and `infra/vpn/main.bicep`. Do not assume the caller's project is the toolkit. An invalid explicit override is an error, not permission to choose another root. Read only that named environment variable, never dump the environment.
2. If none exists, explain that the shared helpers require a lightweight source checkout (third-party releases are linked, not included) from `https://github.com/ness001/vpn-skill-all-in-one.git`. Use existing Git, create only the parent cache directory, and run `git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git "<absolute-home>/.cache/vpn-skill/source"` through the agent's normal permission flow. A request to install/use this toolkit covers this ordinary intended preparation when applicable; ask only for missing download/write authorization and respect denials. Never overwrite/delete an existing incomplete destination; report the collision. If the repository is not yet published or Git/network access is unavailable, report that blocker and accept an existing local checkout path. Never use curl-to-shell, install Git/Python/cloud tools, or alter shell settings/hooks as preparation.
3. Check installed Python 3.11+ (`python3`, or `python` on Windows). Validate with `python3 "<root>/admin/tools/skill_root.py" --root "<root>"`. The resolver also supports `--skill-dir "<absolute-loaded-skill-directory>"` for bundled/nearby/cached discovery. Validation checks filenames, not private data.
4. Run every helper using its **quoted absolute path**, independent of the caller's working directory; resolve documentation links at `<root>` and sibling skills at `<root>/skills/<name>/SKILL.md`. Commands below use repository-relative paths only for readability: prefix them with the validated root before execution. Server commands run only on the verified intended server, never locally just because helpers are available. Runtime client/core caches and default measurement files use `~/.cache/vpn-skill/runtime`, outside installed plugins. Keep profiles, exports and other user files in private locations outside the source/plugin; always supply the private profile path explicitly. Do not use a plugin checkout's ignored profile fallback.
5. Continue the requested workflow after preparation; do not stop at a readiness report. Check only prerequisites needed for that workflow. Missing optional Python/browser/cloud dependencies need their own applicable authorization, never silent installation. Source preparation does not authorize connections, server changes or charges. Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.

Use the user's requested goal. Treat arguments as data, not shell commands. Read [installation](../../admin/INSTALL.md) before executing. Reuse `admin/install-server.sh` and `admin/installer/`; do not create a second installer.

## Establish the target

- Obtain the intended host identity, authorized management path, protocol (`vless` or `hysteria2`), domain and public IPv4. Verify the user controls the host/domain. Distinguish the agent's computer from the server; never install on the wrong machine.
- Verify the actual target is fresh Ubuntu 22.04/24.04 LTS amd64/x86_64 with systemd, Python3.10+ and the documented base tools. Other releases/ARM64 are unsupported. A local preview does not check the target OS or ownership.
- Check DNS-only A record, no AAAA, suitable CAA, outbound DNS/HTTPS and inbound ports: TCP80/443 for VLESS; TCP/UDP443 for Hysteria2 (TCP supports ACME). Host/cloud firewalls are separate. Do not expose public SSH as a shortcut.
- Inspect service/port conflicts without printing private configs, raw logs, process arguments or environments. Preserve installer ownership, hash and foreign-installation refusals. Never stop unrelated services, delete state or bypass checks. Existing production maintenance/migration needs separate scope and a privately preserved, verified recovery path.
- Request only missing nonsecret details and private paths. Never Read/print credentials, private keys, authenticated URIs or QR payloads into model context. Programs may process authorized private files internally; never ask for secret values in chat.

## Preview and install

First validate inputs without changing the host:

```bash
bash admin/install-server.sh --profile vless --domain vpn.example.com --public-ip 1.2.3.4 --dry-run
```

Use `hysteria2` for that protocol. This preview checks input shape only: no host/root/DNS validation, downloads, generated secrets or installation. For migrations, follow INSTALL's narrow `--credentials-file` schema; do not read the file into context.

Summarize the actual target and changes: root execution, CA package installation, pinned downloads, service users/systemd units, private state/exports, ports and ACME CA terms/certificate-transparency disclosure. Confirm missing authorization for installation, remote execution, DNS/firewall changes or costs; reuse already applicable approval. A config or `--yes` is not consent. Respect tool denials.

Only on the verified intended server, within approved scope:

```bash
sudo bash admin/install-server.sh --profile vless --domain vpn.example.com --public-ip 1.2.3.4 --yes
```

No full OS upgrade, reboot, routing/NAT/TUN or SSH changes are included. Firewall changes default to none; `--configure-firewall` requires approval and only adds VPN allow rules to already-active UFW. It does not configure cloud firewalls. On failure, report sanitized state; no automatic cleanup, retry loops or removal of ownership markers. Consult INSTALL for same-target retries. Never change production during user tests.

## Private handoff and acceptance

Exports are root-only under `/root/personal-vpn/vless/` or `/root/personal-vpn/hysteria2/`. Report paths, not contents. Retrieve them only through an authorized private transfer path. On the intended client computer, convert either private `client.json` or `client-uri.txt` to a toolkit bundle using the existing local converter (Python3.11+, `python` on Windows):

```bash
python3 clients/import_profile.py --input /absolute/private/client.json --name my-server --output /absolute/private/new-bundle/vpn-profiles.json
```

Use the user's safe connection ID with `--name`; protocol is detected and stored explicitly. This validates supported connection settings offline and creates one private bundle entry, without printing credentials or contacting the server. Output must be new, outside every Git repository, with a private parent; no overwrite or merging. See [supported inputs](../../profiles/README.md#import-installer-exports). Keep the standalone installer independent of client modules; no conversion needs to run on the server.

Continue with [vpn-client-setup](../vpn-client-setup/SKILL.md) on the intended client device, using private file paths. Do not make client installation or bandwidth tests an automatic side effect of server setup.

Separate installer/service/listener observations from authenticated forwarding, invalid-auth rejection and real-device browsing. Live checks need applicable authorization. `clients/app.py --check` supplies only a positive bounded HTTPS test, not negative-auth acceptance. Reboot recovery, renewal and speed remain unverified unless actually tested. Do not retire an old server based on a preview or active listener.

Use [vpn-diagnose](../vpn-diagnose/SKILL.md) for requested read-only investigation; do not treat faults as permission to reinstall. Use [vpn-speed](../vpn-speed/SKILL.md) only for requested bounded transfers.

## Optional Azure infrastructure

If the user needs a new cloud host, use [vpn-infra-setup](../vpn-infra-setup/SKILL.md), which currently supports Azure through the existing [Bicep template](../../infra/vpn/). That skill handles subscription, region, budget and deployment review, then returns the actual host identity for server setup. Users with an existing suitable host can skip infrastructure setup. Never deploy, change global account context, start VMs or incur charges from a saved configuration alone.

## Finish

Report actual target, actions, safe output paths, checks and outstanding acceptance gaps. Keep TLS verification and private-network ACLs enabled. No background monitoring, publication or unrelated infrastructure changes. Do not assume similarly named skills target the same environment.
