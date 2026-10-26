# Development

## Offline checks

Run from the repository root with Python 3.11+ (`python` on Windows):

```bash
python3 -m unittest discover -s clients/tests
python3 -m unittest discover -s admin/tools/tests
python3 -m unittest discover -s admin/installer -p 'test_*.py'
python3 -m unittest discover -s infra/vpn -p 'test*.py'
bash -n admin/install-server.sh
```

Template checks require Azure CLI and Bicep. On macOS, use a canonical temporary directory such as `TMPDIR=/private/tmp` when running tests that reject symlink paths. Platform-specific and optional-dependency tests may be skipped when their prerequisites are unavailable.

These checks use synthetic configurations and mocks; live installation and forwarding require separate validation. See [installer checks](../admin/INSTALL.md#local-developer-checks) for server-specific coverage.

## Skill packaging

The five portable skills live only under `skills/`. Root `plugin.json` uses [Agent Plugins 1.0](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json) for current Codex/Copilot; `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` provide [Claude-compatible packaging](https://code.claude.com/docs/en/plugins-reference), also used by the [reference skill repository](https://github.com/mattpocock/skills#installation-30-second-setup). Both manifests intentionally share metadata and default `skills/` discovery, with no hooks, MCP servers or automatic settings. `.agents/plugins/marketplace.json` supplies the current Codex catalog policy fields; the Claude-compatible catalog stays minimal. Both catalogs select the same root plugin and five skills, not separate copies.

Installation syntax is based on [Codex plugin packaging](https://developers.openai.com/plugins/build/plugins), [Copilot marketplaces](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-marketplace), [Gemini skills](https://geminicli.com/docs/cli/skills/) and the [skills CLI](https://github.com/vercel-labs/skills). Check those references when updating installer commands or package schemas.

```bash
python3 -m unittest discover -s admin/tools/tests -p 'test_skill_packaging.py'
claude plugin validate .claude-plugin/plugin.json --strict
claude plugin validate .claude-plugin/marketplace.json --strict
python3 admin/tools/skill_root.py --root /absolute/path/vpn-skill-all-in-one
```

The resolver checks required filenames only and never reads profiles or release artifacts or installs dependencies. An explicit `--root` overrides optional `VPN_SKILL_ROOT`; otherwise it checks the full plugin/source skill path, validated current/ancestor checkout candidates (including `toolkit/`), then `~/.cache/vpn-skill/source`. It never accepts an unrelated project without all required helpers. All five copied skill definitions include the same first-use source preparation instructions, so they can acquire the shared source even before the resolver exists. Commands use quoted absolute helper paths. `--editable` can require a Git checkout for source development. Runtime core caches and default measurement output live under `~/.cache/vpn-skill/runtime`, not the plugin cache. See [installation and first use](INSTALLATION.md).

Packaging tests use synthetic paths (including spaces and copied-skill layouts), check all five skill definitions and documentation links, and keep the two plugin manifests synchronized. CLI manifest validation is not an agent/model API call and does not install the plugin. Actual installation/discovery in other agents and live VPN/cloud actions require separate validation.
