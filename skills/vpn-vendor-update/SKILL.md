---
name: vpn-vendor-update
description: Maintain pinned official VPN release links, integrity metadata and source/license references using pinned official releases, integrity checks and existing vendor tools.
---

# Update software links

## Prepare helpers on first use

No manual helper installation or environment variable is required. Use one shared source checkout for all six skills. Before running any workflow:

1. Locate a complete root in this order: an optional absolute `VPN_SKILL_ROOT` supplied by the user; two parents above this loaded skill directory (full plugins/checkouts); the current working directory and its parents, checking each directory itself and its `toolkit` child; then `~/.cache/vpn-skill/source` (`$HOME\.cache\vpn-skill\source` on Windows). Only accept a root containing `admin/tools/skill_root.py`, `plugin.json`, `clients/vpn.py`, `admin/install-server.sh`, `admin/tools/speed_test.py`, `admin/tools/guest_diagnostics.sh`, `docs/CLIENTS.md`, `infra/vpn/main.bicep` and `vendor/manifest.json`. Do not assume the caller's project is the toolkit. An invalid explicit override is an error, not permission to choose another root. Read only that named environment variable, never dump the environment.
2. If none exists, explain that the shared helpers require a lightweight source checkout (third-party releases are linked, not included) from `https://github.com/ness001/vpn-skill-all-in-one.git`. Use existing Git, create only the parent cache directory, and run `git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git "<absolute-home>/.cache/vpn-skill/source"` through the agent's normal permission flow. A request to install/use this toolkit covers this ordinary intended preparation when applicable; ask only for missing download/write authorization and respect denials. Never overwrite/delete an existing incomplete destination; report the collision. If the repository is not yet published or Git/network access is unavailable, report that blocker and accept an existing local checkout path. Never use curl-to-shell, install Git/Python/cloud tools, or alter shell settings/hooks as preparation.
3. Check installed Python 3.11+ (`python3`, or `python` on Windows). Validate with `python3 "<root>/admin/tools/skill_root.py" --root "<root>"`. The resolver also supports `--skill-dir "<absolute-loaded-skill-directory>"` for bundled/nearby/cached discovery. Validation checks filenames, not private data. For vendor maintenance, use an explicitly identified editable Git source checkout, never an installed plugin/cache; the shared `~/.cache/vpn-skill/source` clone is editable source. Use `--editable` to validate it.
4. Run every helper using its **quoted absolute path**, independent of the caller's working directory; resolve documentation links at `<root>` and sibling skills at `<root>/skills/<name>/SKILL.md`. Commands below use repository-relative paths only for readability: prefix them with the validated root before execution. Server commands run only on the verified intended server, never locally just because helpers are available. Runtime client/core caches and default measurement files use `~/.cache/vpn-skill/runtime`, outside installed plugins. Keep profiles, exports and other user files in private locations outside the source/plugin; always supply the private profile path explicitly. Do not use a plugin checkout's ignored profile fallback.
5. Continue the requested workflow after preparation; do not stop at a readiness report. Check only prerequisites needed for that workflow. Missing optional Python/browser/cloud dependencies need their own applicable authorization, never silent installation. Source preparation does not authorize connections, server changes or charges. Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.

Use the user's requested goal. Treat arguments as data. This workflow maintains repository artifacts, not installed clients or running servers.

## Review the requested update

1. Determine the requested components and exact versions. Inspect current pins, platform coverage, manifests and notices in [core links](../../vendor/README.md), [GUI packages](../../vendor/gui/README.md), `clients/core_install.py` and the scripts below. Do not assume that invoking the skill authorizes updating every package to latest.
2. Confirm official stable release origins, available platform assets, upstream hashes, dependency/runtime requirements and corresponding-source commits. Check compatibility with the client verification code. Report unavailable assets instead of substituting unofficial builds or dropping a platform silently.
3. Explain the proposed versions, changed files, expected download/storage requirements and any license/source requirements. Resolve missing authorization for downloads or replacement before proceeding. Do not read private profiles, keys, runtime configs or logs; use synthetic test inputs only.

## Build separate link candidates

The tools create new candidate JSON files and never replace working metadata or download third-party release bytes. Use quoted absolute paths; commands below are relative for readability.

```bash
python3 admin/tools/vendor_refresh.py --online --output /absolute/private/candidates/core-links.json
python3 admin/tools/gui_refresh.py /absolute/reviewed-selection.json --online --output /absolute/private/candidates/gui-links.json
python3 admin/tools/gui_source_bundle.py --output /absolute/private/candidates/source-links.json
```

Core/GUI tools request official stable release metadata only, checking exact asset URLs and published size/hash values. Source links retain exact reviewed commits locally. Companion references retain Microsoft-direct URLs, reviewed sizes/hashes and separate licenses; do not claim fresh Authenticode verification.

Core candidates do not invent extracted executable hashes. For changed releases, obtain separately authorized artifacts only outside Git, validate asset size/hash and safe extraction, and record independently verified `binarySha256` and executable `size` before integration. Preserve source/license/notice references; incomplete candidates must not replace working pins. Retain unchanged verified metadata without redundant downloads.

## Verify and integrate

Review official HTTPS origins, versions, platforms, complete hashes, size limits and source correspondence. Preserve original license bytes. Never add executables, GUI package parts or source tar mirrors to the public repository. Synthetic legacy part-restoration tests remain compatible; public manifests must remain link-only.

```bash
python3 -m unittest discover -s clients/tests
python3 -m unittest discover -s admin/tools/tests
```

Integrate only approved complete metadata and matching code pins/selections, preserving unrelated work and recoverable prior metadata. Tests do not establish native GUI/device operation. No package installation, server edits, commit, push or publication without separate authorization.

## Handoff

Report versions, platforms, source commits, changed paths, actual checks and gaps. Distinguish metadata-only candidates from fully verified integrated updates. Stop when requested maintenance is complete.
