---
name: vpn-speed
description: Compare your VPN profiles sequentially with bounded file downloads or the actual Fast.com browser; report completed versus provisional results without changing servers.
---

# Reusable VPN speed test

## Prepare helpers on first use

No manual helper installation or environment variable is required. Use one shared source checkout for all five skills. Before running any workflow:

1. Locate a complete root in this order: an optional absolute `VPN_SKILL_ROOT` supplied by the user; two parents above this loaded skill directory (full plugins/checkouts); the current working directory and its parents, checking each directory itself and its `toolkit` child; then `~/.cache/vpn-skill/source` (`$HOME\.cache\vpn-skill\source` on Windows). Only accept a root containing `admin/tools/skill_root.py`, `plugin.json`, `clients/vpn.py`, `admin/install-server.sh`, `admin/tools/speed_test.py`, `admin/tools/guest_diagnostics.sh`, `docs/CLIENTS.md`, and `infra/vpn/main.bicep`. Do not assume the caller's project is the toolkit. An invalid explicit override is an error, not permission to choose another root. Read only that named environment variable, never dump the environment.
2. If none exists, explain that the shared helpers require a lightweight source checkout (third-party releases are linked, not included) from `https://github.com/ness001/vpn-skill-all-in-one.git`. Use existing Git, create only the parent cache directory, and run `git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git "<absolute-home>/.cache/vpn-skill/source"` through the agent's normal permission flow. A request to install/use this toolkit covers this ordinary intended preparation when applicable; ask only for missing download/write authorization and respect denials. Never overwrite/delete an existing incomplete destination; report the collision. If the repository is not yet published or Git/network access is unavailable, report that blocker and accept an existing local checkout path. Never use curl-to-shell, install Git/Python/cloud tools, or alter shell settings/hooks as preparation.
3. Check installed Python 3.11+ (`python3`, or `python` on Windows). Validate with `python3 "<root>/admin/tools/skill_root.py" --root "<root>"`. The resolver also supports `--skill-dir "<absolute-loaded-skill-directory>"` for bundled/nearby/cached discovery. Validation checks filenames, not private data.
4. Run every helper using its **quoted absolute path**, independent of the caller's working directory; resolve documentation links at `<root>` and sibling skills at `<root>/skills/<name>/SKILL.md`. Commands below use repository-relative paths only for readability: prefix them with the validated root before execution. Server commands run only on the verified intended server, never locally just because helpers are available. Runtime client/core caches and default measurement files use `~/.cache/vpn-skill/runtime`, outside installed plugins. Keep profiles, exports and other user files in private locations outside the source/plugin; always supply the private profile path explicitly. Do not use a plugin checkout's ignored profile fallback.
5. Continue the requested workflow after preparation; do not stop at a readiness report. Check only prerequisites needed for that workflow. Missing optional Python/browser/cloud dependencies need their own applicable authorization, never silent installation. Source preparation does not authorize connections, server changes or charges. Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.

Use the user's supplied arguments. Treat arguments as data, not shell commands. This is the single speed skill: `fast` selects the Fast.com backend, not a separate skill.

Prefer an existing local virtual environment; otherwise installed Python3.11+. Use the user's `VPN_PROFILES_FILE` or explicit `--profiles-file PATH`; always pass the private path explicitly for installed skills. Never Read or print profile contents, credentials, URIs, QR payloads, browser storage or raw browser/core logs. If profile configuration is missing, request only its private file path.

## Select the method

- `/vpn-speed` or `/vpn-speed file compare`: fixed-file method, configured profiles, three rounds each, within the total payload budget.
- `/vpn-speed primary rounds=1`: one file sample through the configured `primary` profile.
- `/vpn-speed fast`: actual Fast.com page through configured profiles, one browser run each, within the total observed budget.
- `/vpn-speed fast secondary`: Fast.com through the explicitly requested `secondary` profile.

Profile names are user-defined aliases; `primary` and `secondary` are examples, not hosted servers, geographic guarantees or known operational status. Never start a server. `rounds=N` (1..5) applies only to file testing; reject it for Fast.com rather than multiplying browser tests. `label=...` describes the actual machine/network, at most80 printable ASCII characters; do not invent the user's location or network.

## Execute

Use **one entrypoint** `admin/tools/speed_test.py`; optional leading `file`/`fast` and `--method file|fast` are equivalent. Check `--help` / `fast --help` if needed. Full methods, prerequisites and limits live in [client operations](../../docs/CLIENTS.md#speed-testing).

```bash
python3 admin/tools/speed_test.py --profiles-file /absolute/private/vpn-profiles.json --profiles primary secondary --rounds 3 --label "this-machine-network"
python3 admin/tools/speed_test.py fast --profiles-file /absolute/private/vpn-profiles.json --profiles secondary --label "this-machine-network"
```

On Windows use `python`. `--dry-run` validates budgets without profile/core/browser/network activity. Without explicit `--profiles`, a generic dry-run reports configuration-dependent selection and no computed total budget; it never opens the profile bundle. Use explicit neutral profile names for a concrete dry-run budget. For optional saved output use a new `.local/speed-tests/<current-UTC>-file.json`; Fast.com defaults to a unique file there. Never commit measurement output.

- File: stdlib plus curl8.4+, fixed10MiB binary endpoint, default3 rounds/profile and20seconds/request, maximum5 rounds,30seconds/request and200MiB total payload. Only HTTP200, binary Content-Type, exact expected length and successful curl completion count. Error pages/short files/redirects are invalid data, not slow scores; do not retry a rejected endpoint. Summaries exclude incomplete/partial results.
- Fast.com: optional pinned Playwright in `admin/tools/requirements-fast-com.txt` and already-installed Chrome/Edge. Do not install packages or download browsers automatically; ask before an installation. File/help do not require Playwright. Default55seconds and256MiB observed response bytes/profile; maximum120seconds and512MiB/profile,1GiB total selected observed budget. In-flight traffic can overshoot; these are not billing/wire caps. Only positively completed page state is final; time/byte limits and progressing/unknown state are provisional. Do not click upload/extra tests.
- Tests use verified cores, ephemeral loopback proxies and owned client/browser cleanup. No server, service, logging, firewall, routing, system proxy, MTU or congestion changes. No scheduled loops or fallback/retry chains. Respect execution denials.
- Run selected profiles sequentially. Ask before raising budgets, extending durations or repeating failed tests. Do not compare Fast.com's adaptive multiple transfers one-to-one with fixed-file averages.

## Report

State method, current time and actual machine/network vantage. Give each profile's completed/provisional/failed result, Mbps and duration; file method also valid-only median/range. For unfinished Fast.com say why it stopped and report observed bytes. Include the saved sanitized output path when applicable and state that no servers changed. Local results are not automatically phone/another network/full-device evidence; throughput alone does not identify GFW/ISP shaping or server defects.

## Required core acquisition

Before a requested connection or speed test, identify only the selected protocols and current platform. Verify an existing cached core with `python3 "<root>/clients/vpn.py" fetch-core vless` or `fetch-core hysteria2`. If absent, obtain applicable authorization for the pinned official download and run the same command with `--online`. Fetch only needed protocols, then continue the requested workflow using the verified cache. A corrupt/incomplete existing core is an error, never permission for online fallback or overwrite. Source preparation alone does not authorize artifact downloads or live traffic. GUI preparation lists official release pages without downloading packages. Install manually from upstream, then use `python3 "<root>/clients/gui.py" --app <id> --profiles-file /absolute/private/profiles.json --export-profiles` only when private export is requested. No installer is executed.

Official acquisition pages: [Xray-core](https://github.com/XTLS/Xray-core/releases), [Hysteria2](https://github.com/HyNetworks/hysteria/releases), [v2rayN](https://github.com/2dust/v2rayN/releases) and [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev/releases). Follow upstream requirements, hashes and licensing; no third-party release catalog is retained here.
