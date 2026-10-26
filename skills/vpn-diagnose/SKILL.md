---
name: vpn-diagnose
description: Read-only local Ubuntu or optional Azure CPU, service/listener and sanitized supported-log diagnostics with explicit settings.
---

# Reusable VPN diagnostics

## Prepare helpers on first use

No manual helper installation or environment variable is required. Use one shared source checkout for all six skills. Before running any workflow:

1. Locate a complete root in this order: an optional absolute `VPN_SKILL_ROOT` supplied by the user; two parents above this loaded skill directory (full plugins/checkouts); the current working directory and its parents, checking each directory itself and its `toolkit` child; then `~/.cache/vpn-skill/source` (`$HOME\.cache\vpn-skill\source` on Windows). Only accept a root containing `admin/tools/skill_root.py`, `plugin.json`, `clients/vpn.py`, `admin/install-server.sh`, `admin/tools/speed_test.py`, `admin/tools/guest_diagnostics.sh`, `docs/CLIENTS.md`, `infra/vpn/main.bicep` and `vendor/manifest.json`. Do not assume the caller's project is the toolkit. An invalid explicit override is an error, not permission to choose another root. Read only that named environment variable, never dump the environment.
2. If none exists, explain that the shared helpers require a lightweight source checkout (third-party releases are linked, not included) from `https://github.com/ness001/vpn-skill-all-in-one.git`. Use existing Git, create only the parent cache directory, and run `git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git "<absolute-home>/.cache/vpn-skill/source"` through the agent's normal permission flow. A request to install/use this toolkit covers this ordinary intended preparation when applicable; ask only for missing download/write authorization and respect denials. Never overwrite/delete an existing incomplete destination; report the collision. If the repository is not yet published or Git/network access is unavailable, report that blocker and accept an existing local checkout path. Never use curl-to-shell, install Git/Python/cloud tools, or alter shell settings/hooks as preparation.
3. Check installed Python 3.11+ (`python3`, or `python` on Windows). Validate with `python3 "<root>/admin/tools/skill_root.py" --root "<root>"`. The resolver also supports `--skill-dir "<absolute-loaded-skill-directory>"` for bundled/nearby/cached discovery. Validation checks filenames, not private data. For vendor maintenance, use an explicitly identified editable Git source checkout, never an installed plugin/cache; the shared `~/.cache/vpn-skill/source` clone is editable source. Use `--editable` to validate it.
4. Run every helper using its **quoted absolute path**, independent of the caller's working directory; resolve documentation links at `<root>` and sibling skills at `<root>/skills/<name>/SKILL.md`. Commands below use repository-relative paths only for readability: prefix them with the validated root before execution. Server commands run only on the verified intended server, never locally just because helpers are available. Runtime client/core caches and default measurement files use `~/.cache/vpn-skill/runtime`, outside installed plugins. Keep profiles, exports and other user files in private locations outside the source/plugin; always supply the private profile path explicitly. Do not use a plugin checkout's ignored profile fallback.
5. Continue the requested workflow after preparation; do not stop at a readiness report. Check only prerequisites needed for that workflow. Missing optional Python/browser/cloud dependencies need their own applicable authorization, never silent installation. Source preparation does not authorize connections, server changes or charges. Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.

Use the user's supplied arguments. Require an explicit mode (`local` or `azure`) and private JSON `config` path; local runs on the intended server. Accept optional integer `minutes=N`, 1–30 (default 30). Pass paths as quoted CLI arguments, never executable shell text. Do not infer a target from profile names or historical notes. The toolkit supplies no hosted server or default production target. Local mode supports Ubuntu 22.04/24.04 LTS amd64 servers and does not require an Azure account or CLI.

Use installed Python 3.11+ or an existing virtual environment from the resolved helper checkout:

```bash
python3 admin/tools/diagnose_vpn.py --mode local --config /absolute/private/diagnose-target.json --minutes 15
```

See [configuration and log support](../../docs/TROUBLESHOOTING.md#read-only-server-diagnostics). Check `--help` if uncertain. `--dry-run` validates the target and prints scope without Azure/network calls. Optional `--output .local/diagnostics/<fresh-UTC-name>.json` saves sanitized JSON locally, never automatically commit/publish it.

Local mode runs the same reviewed collector directly on the intended server. Configure service units/ports and optional supported log paths; no Azure IDs are required. Use existing read permissions; root may be needed for private logs or listener ownership, but do not elevate automatically or bypass a denial. Missing permissions or unsupported logs remain incomplete coverage, never proof of zero errors. Azure CPU-window metrics and credits are explicitly unavailable locally.

Only when Azure mode is requested, use `--mode azure` and an existing authenticated Azure CLI. Do not automatically log in, grant permissions, change global subscription context or bypass denials. The helper explicitly scopes every Azure command to the configured subscription. Only query the intended already-running VM. Never start VMs to diagnose them.

## Read-only scope and privacy

The helper queries service state, expected listener ownership, memory/disk, lifetime UDP counters and supported rolling logs; Azure mode additionally queries CPU and optionally burst credits. The reviewed guest helper runs locally or is sent through Azure as a temporary script file (`--scripts @file`). It uses the explicitly configured guest Python executable, systemctl show, ss and bounded local file reads. It never changes services, logging, ports, routing, packages, ACLs/TLS or Azure resources.

Never read private client profiles, raw logs, process command lines/environments, private configuration or TLS keys into model context. The guest inspects logs internally and returns only fixed categories/counts, safe service/resource metrics and coverage. Unexpected fields and malformed or truncated summaries are rejected or explicitly incomplete; raw Azure errors are not printed. Missing log support is **unknown**, not zero errors. Do not install a collector or enable logging as part of diagnostics.

## Interpretation and response

Report actual UTC time/window, sampled CPU/credits, service/listener state, error categories/counts and coverage gaps. Credits are not bandwidth quotas. UDP counters are since boot, not recent-window errors. An active service/collector or healthy CPU does not establish authenticated browsing. Empty/expired/partial logs do not establish absence of errors. TCP resets do not establish GFW/ISP interference. Preserve private-network ACLs; investigate loopback rejections at the client.

Distinguish observations, possible causes and what is not established. State that no settings changed. Offer `/vpn-speed` (fixed file) or `/vpn-speed fast` (Fast.com) only when speed testing is requested; diagnostics do not authorize bulk bandwidth tests or repairs.
