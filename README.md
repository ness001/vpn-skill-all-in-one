# VPN Skill All in One

An extensible collection of agent skills for VPN infrastructure, server and client setup, diagnosis, speed testing and software maintenance. Add support for new cloud providers, protocols and clients as the project grows.

## Quick start

[Install for your agent](#installation), then describe what you want to do:

```text
/vpn-skill:vpn-server-setup Set up Hysteria2 on my Ubuntu server.
/vpn-skill:vpn-client-setup Configure my client using the server's exported file.
```

Use the skill name shown by your agent; Claude plugin names include the `vpn-skill:` prefix. The agent checks prerequisites and gathers the settings for your request. Provide connection files by local path rather than pasting credentials into chat.

## Skills

### [`vpn-infra-setup`](skills/vpn-infra-setup/SKILL.md)

Prepare cloud infrastructure for a new VPN server.

Currently supports:

- Azure

### [`vpn-server-setup`](skills/vpn-server-setup/SKILL.md)

Install and configure VPN server software, then generate client connection files.

Currently supports:

- VLESS over WebSocket/TLS
- Hysteria2 (Hy2)

**Environment:** fresh Ubuntu 22.04 / 24.04 LTS · x64 · systemd

### [`vpn-client-setup`](skills/vpn-client-setup/SKILL.md)

Configure a client, import server exports and validate the connection.

Currently supports:

- Xray
- Hysteria2
- v2rayN
- Clash Verge Rev

### [`vpn-diagnose`](skills/vpn-diagnose/SKILL.md)

Inspect services, listeners, resources and supported logs.

Currently supports:

- Local Ubuntu
- Azure

### [`vpn-speed`](skills/vpn-speed/SKILL.md)

Measure throughput through selected VPN connections.

Currently supports:

- Fixed-file download
- Fast.com

### [`vpn-vendor-update`](skills/vpn-vendor-update/SKILL.md)

Maintain official acquisition links and client compatibility instructions.

Currently supports:

- Xray
- Hysteria2
- v2rayN
- Clash Verge Rev

## Installation

Install for your agent, then invoke a skill. Skills reuse available helpers or prepare one shared checkout on first use. [Local installs, updates and requirements](docs/INSTALLATION.md).

### Claude Code

```bash
claude plugin marketplace add ness001/vpn-skill-all-in-one
claude plugin install vpn-skill@vpn-skill
```

### Codex

```bash
codex plugin marketplace add ness001/vpn-skill-all-in-one
codex plugin add vpn-skill@vpn-skill
```

### GitHub Copilot

```bash
copilot plugin marketplace add ness001/vpn-skill-all-in-one
copilot plugin install vpn-skill@vpn-skill
```

In VS Code, use **Chat: Install Plugin From Source** with this repository's URL.

### Gemini CLI

```bash
gemini skills install https://github.com/ness001/vpn-skill-all-in-one.git --path skills
```

### Other agents

```bash
npx skills@latest add ness001/vpn-skill-all-in-one
```

Choose your agent and the VPN skills in the installer. Python helpers require Python 3.11+; the standalone server installer supports Python 3.10+. See [requirements and validation coverage](docs/INSTALLATION.md#requirements-and-validation).

## Documentation

- [Server installation](admin/INSTALL.md) · [Azure infrastructure](infra/vpn/)
- [Client operations](docs/CLIENTS.md) · [Device setup](docs/DEVICES.md)
- [VPN concepts](docs/CONCEPTS.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Profile format](profiles/README.md) · [Configuration examples](examples/README.md)
- [Official client acquisition](skills/vpn-client-setup/SKILL.md) · [Software-link maintenance](skills/vpn-vendor-update/SKILL.md)
- [Development and testing](docs/DEVELOPMENT.md)
