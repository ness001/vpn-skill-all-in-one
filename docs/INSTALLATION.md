# Install VPN Skill

The [README](../README.md#installation) lists the normal per-agent commands. Choose one installation method per agent to avoid duplicate skills, then start a fresh session or reload skills as required by that agent.
## First use

There is no separate setup skill and no required environment variable. Each of the six skills checks for complete helpers in an explicitly supplied checkout, its full plugin installation, nearby source checkouts (including a parent repository's `toolkit/`), then the shared user cache.

A copied skill-only installation, such as Gemini or the skills CLI, can prepare the missing source with existing Git:

```bash
git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git "$HOME/.cache/vpn-skill/source"
```

The agent performs this preparation when needed, explaining the lightweight source checkout (release artifacts are linked, not included) and using the host's normal permission flow. All six skills reuse that one source. On Windows the same location is `$HOME\.cache\vpn-skill\source`. An existing incomplete destination is a blocker, not something to delete or overwrite. Git and Python are not silently installed.
Full plugins already containing the helpers need no second download. Optional `VPN_SKILL_ROOT` is an absolute override for an existing full checkout, not an installation requirement; no shell-profile changes are needed. A bad override fails clearly instead of selecting unrelated code. The shared resolver validates filenames without reading profiles or executing vendor software:

```bash
python3 /absolute/path/vpn-skill-all-in-one/admin/tools/skill_root.py --skill-dir /absolute/path/installed/skills/vpn-speed
```

Use `python` on Windows. Helpers execute by absolute path regardless of the agent's current project. Relative documentation paths resolve against the source, not copied skill directories.

## Install from local source

To try or develop the plugin from a local checkout, load it for one Claude session:

```bash
claude --plugin-dir /absolute/path/vpn-skill-all-in-one
```

Other source installation options:

| Agent | Local command |
| --- | --- |
| Claude Code | `claude plugin marketplace add /absolute/path/vpn-skill-all-in-one`, then `claude plugin install vpn-skill@vpn-skill` |
| Codex | `codex plugin marketplace add /absolute/path/vpn-skill-all-in-one`, then `codex plugin add vpn-skill@vpn-skill` |
| Copilot CLI | `copilot plugin install /absolute/path/vpn-skill-all-in-one` |
| Gemini CLI | `gemini skills install /absolute/path/vpn-skill-all-in-one/skills` |
| skills CLI | `npx skills@latest add /absolute/path/vpn-skill-all-in-one` |

Quote actual paths containing spaces. For VS Code with agent-plugin support, use **Chat: Install Plugin From Source** and the local repository location or published repository URL. For local skill-only installs, invoke from the checkout or tell the agent its absolute path; no exported variable is needed.

## Updates and editable source

Use your agent's plugin update command; for skill-only installs repeat the selected Gemini install command or use `npx skills@latest update`. Refresh a separate helper clone deliberately with `git -C /absolute/path/to/source pull --ff-only` after reviewing local changes; skills do not silently update source or reset working trees. Copied skills and helper source should come from the same reviewed revision.

Vendor maintenance modifies source artifacts and must use an editable Git checkout, not an installed plugin/cache snapshot. The shared `~/.cache/vpn-skill/source` clone is editable source. Pass its path explicitly when necessary and validate it with `skill_root.py --root /absolute/path/to/source --editable`. Candidate link metadata remains separate until reviewed integration.

Private profiles and exports stay outside Git/source/plugin directories. Core runtime preparation uses `~/.cache/vpn-skill/runtime/.tools`; default optional diagnostic and speed result paths are under `~/.cache/vpn-skill/runtime/.local/`. Skills explicitly pass the private profile path. Connection and provisioning workflows run when you invoke the corresponding skill.

## Requirements and validation

- **Helpers:** installed Python 3.11+ (`python3`, or `python` on Windows). The guest server installer separately supports Python 3.10+.
- **Server setup:** fresh Ubuntu 22.04/24.04 LTS amd64/x86_64, systemd, public IPv4, domain and required ports; see [server requirements](../admin/INSTALL.md).
- **Client:** compatible existing core/CLI/GUI. Pinned official core links cover Windows x64 and Intel/Apple Silicon Macs; GUI links also cover Linux x64. Artifact downloads require explicit authorization; only needed packages are fetched outside Git. The toolkit proxy-browser path is Windows/macOS-only and requires installed Chrome/Edge. Native clients have their own import/configuration workflow.
- **Speed:** file tests need curl 8.4+; Fast.com additionally needs the optional pinned Playwright package and already-installed Chrome/Edge. Optional packages/browser downloads require applicable installation permission.
- **Azure infrastructure/diagnosis:** existing Azure CLI/login; infrastructure compilation also needs Bicep. Existing non-Azure hosts skip infrastructure creation and can use local diagnosis. No cloud tools are installed during helper preparation.
- **Install hosts:** plugin methods require an agent version supporting the documented plugin commands. Node/npm are needed only for the `npx` method; Gemini and skills CLI install skill folders, not bundled helper assets.

The package uses one portable `skills/` tree with Agent Plugins and Claude-compatible manifests. See [packaging checks](DEVELOPMENT.md#skill-packaging) for manifest, path and first-use validation.
