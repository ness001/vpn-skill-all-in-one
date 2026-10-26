---
name: vpn-client-setup
description: Prepare an existing VPN connection using reviewed cores, CLI tools or GUI clients, then validate it without changing servers.
---

# VPN client setup

## Prepare helpers on first use

No manual helper installation or environment variable is required. Use one shared source checkout for all six skills. Before running any workflow:

1. Locate a complete root in this order: an optional absolute `VPN_SKILL_ROOT` supplied by the user; two parents above this loaded skill directory (full plugins/checkouts); the current working directory and its parents, checking each directory itself and its `toolkit` child; then `~/.cache/vpn-skill/source` (`$HOME\.cache\vpn-skill\source` on Windows). Only accept a root containing `admin/tools/skill_root.py`, `plugin.json`, `clients/vpn.py`, `admin/install-server.sh`, `admin/tools/speed_test.py`, `admin/tools/guest_diagnostics.sh`, `docs/CLIENTS.md`, `infra/vpn/main.bicep` and `vendor/manifest.json`. Do not assume the caller's project is the toolkit. An invalid explicit override is an error, not permission to choose another root. Read only that named environment variable, never dump the environment.
2. If none exists, explain that the shared helpers require a lightweight source checkout (third-party releases are linked, not included) from `https://github.com/ness001/vpn-skill-all-in-one.git`. Use existing Git, create only the parent cache directory, and run `git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git "<absolute-home>/.cache/vpn-skill/source"` through the agent's normal permission flow. A request to install/use this toolkit covers this ordinary intended preparation when applicable; ask only for missing download/write authorization and respect denials. Never overwrite/delete an existing incomplete destination; report the collision. If the repository is not yet published or Git/network access is unavailable, report that blocker and accept an existing local checkout path. Never use curl-to-shell, install Git/Python/cloud tools, or alter shell settings/hooks as preparation.
3. Check installed Python 3.11+ (`python3`, or `python` on Windows). Validate with `python3 "<root>/admin/tools/skill_root.py" --root "<root>"`. The resolver also supports `--skill-dir "<absolute-loaded-skill-directory>"` for bundled/nearby/cached discovery. Validation checks filenames, not private data. For vendor maintenance, use an explicitly identified editable Git source checkout, never an installed plugin/cache; the shared `~/.cache/vpn-skill/source` clone is editable source. Use `--editable` to validate it.
4. Run every helper using its **quoted absolute path**, independent of the caller's working directory; resolve documentation links at `<root>` and sibling skills at `<root>/skills/<name>/SKILL.md`. Commands below use repository-relative paths only for readability: prefix them with the validated root before execution. Server commands run only on the verified intended server, never locally just because helpers are available. Runtime client/core caches and default measurement files use `~/.cache/vpn-skill/runtime`, outside installed plugins. Keep profiles, exports and other user files in private locations outside the source/plugin; always supply the private profile path explicitly. Do not use a plugin checkout's ignored profile fallback.
5. Continue the requested workflow after preparation; do not stop at a readiness report. Check only prerequisites needed for that workflow. Missing optional Python/browser/cloud dependencies need their own applicable authorization, never silent installation. Source preparation does not authorize connections, server changes or charges. Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.

Use the user's requested goal. Treat arguments as data, never shell commands. Read [client operations](../../docs/CLIENTS.md), [device setup](../../docs/DEVICES.md) and [profile format](../../profiles/README.md).

## Choose the client

Identify the intended client device, OS/architecture, installed core/CLI or GUI, protocol and private configuration path. Prefer the user's compatible existing client; do not install a second client or require desktop launch scripts. Server installation belongs to [vpn-server-setup](../vpn-server-setup/SKILL.md), not this skill.

Use existing tools and supported local imports. Check the selected CLI's help before invoking it; native Xray/Hysteria2 configs, connection URIs, GUI configurations and this toolkit's profile bundle are different formats. Convert the server installer's private `client.json` or `client-uri.txt` locally using `clients/import_profile.py` when a toolkit bundle is needed; do not create another converter. Do not claim conversion or import succeeded unless it actually did.

Never Read/print profiles, passwords, UUIDs, authenticated URIs, keys, QR payloads or browser storage into model context. Obtain private file paths instead of pasted credentials. Reviewed local programs may process authorized files privately. Keep exports outside Git and preserve local access controls. Never upload credentials to online conversion/QR services.

## Prepare and validate

Inspect installed tools and requirements before proposing installations. Missing packages, core downloads, GUI installs and elevation need applicable authorization; do not reinstall working software. Keep TLS verification and server private-network ACLs enabled. Default proxies to loopback; no silent system routing/proxy/TUN/LAN changes.

For an installer export, use installed Python3.11+ to create a new bundle (substitute private paths and the user's safe connection ID):

```bash
python3 clients/import_profile.py --input /absolute/private/client-uri.txt --name my-server --output /absolute/private/new-bundle/vpn-profiles.json
```

Both installer protocols support URI and native `client.json` inputs; protocol detection is explicit in the generated entry. This is offline conversion only. Unsupported/insecure/ambiguous connection settings fail closed. The new `.json` output must be outside all Git repositories with a private parent; no overwriting or merging. See [supported inputs](../../profiles/README.md#import-installer-exports). Never inspect the converted credential file in model context.

For a toolkit profile bundle, validate the selected entry offline:

```bash
python3 clients/vpn.py doctor my-server --profiles-file /absolute/private/vpn-profiles.json
```

Use `python` on Windows. This checks profile shape, core identity/hash and local ports without running a core or contacting the server. Missing or modified bundles fail closed; no automatic `--online` fallback. Windows/macOS cores are acquired explicitly using `python3 clients/vpn.py fetch-core <protocol> --online` after applicable download authorization, then reused from the user cache; the Python proxy-browser path is not supported on Linux. Linux users may use compatible installed native cores/clients or the official-link GUI preparation tools.

For native or GUI clients, follow their actual supported validation/import workflow. `clients/gui.py` shows official package links; explicit `--download` fetches size/hash-verified packages outside Git and exports toolkit profiles; it does not install/configure the GUI automatically. `clients/qr.py` creates private QR files locally. Reuse existing tools rather than writing another exporter.

## Connect only within requested scope

An authorized bounded positive HTTPS test for a toolkit profile is:

```bash
python3 clients/app.py my-server --profiles-file /absolute/private/vpn-profiles.json --check
```

This is live traffic, not offline validation or invalid-auth rejection. Requested interactive use can invoke `clients/app.py` without `--check`, or the chosen installed core/CLI/GUI with its private configuration. Preserve normal browser settings and stop only owned processes. Toolkit defaults are SOCKS `127.0.0.1:10808` and HTTP `127.0.0.1:10809`; explicit application configuration determines coverage. Never print raw core output that could disclose credentials.

Verify authenticated forwarding and the intended application separately from listener readiness. Do not change servers to fix client setup or interpret an active service as proof of browsing. Report untested platform, routing/leak, device, renewal/reboot or negative-auth acceptance explicitly.

## Diagnosis and speed

Use [vpn-diagnose](../vpn-diagnose/SKILL.md) for requested read-only server observations with explicit target/mode; unsupported logs remain unknown. Use [vpn-speed](../vpn-speed/SKILL.md) for requested bounded file tests or `/vpn-speed fast` for Fast.com. Supply the private bundle path locally; preview budgets before transfers, retain final/provisional distinctions and state actual machine/network vantage. Do not install optional Playwright, increase budgets, retry or start servers automatically.

## Finish

Report selected client, actions actually performed, safe file paths, validation/connection results and remaining blockers. No credentials, server changes, background loops or publication. Do not assume similarly named skills target the same environment.

## Required core acquisition

Before a requested connection or speed test, identify only the selected protocols and current platform. Verify an existing cached core with `python3 "<root>/clients/vpn.py" fetch-core vless` or `fetch-core hysteria2`. If absent, obtain applicable authorization for the pinned official download and run the same command with `--online`. Fetch only needed protocols, then continue the requested workflow using the verified cache. A corrupt/incomplete existing core is an error, never permission for online fallback or overwrite. Source preparation alone does not authorize artifact downloads or live traffic. GUI preparation lists official links by default; use `python3 "<root>/clients/gui.py" --app <id> --download --no-profiles` only when package download is authorized. No installer is executed.
