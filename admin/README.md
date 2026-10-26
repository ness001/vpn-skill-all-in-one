# Server administration tools

Tools and skills for provisioning infrastructure, installing VPN software and maintaining official acquisition links.

- [Infrastructure setup](../skills/vpn-infra-setup/SKILL.md): `/vpn-infra-setup` prepares a new cloud host; Azure is currently supported.
- [Server setup](../skills/vpn-server-setup/SKILL.md): `/vpn-server-setup` verifies the target and coordinates authorized installation and private handoff.
- [Client setup](../skills/vpn-client-setup/SKILL.md): `/vpn-client-setup` prepares existing cores/CLI/GUI clients and validates connections. Install the skills using the repository README.
- [Fresh-host installer](INSTALL.md): `install-server.sh` and `installer/`, for Ubuntu22.04/24.04 LTS x86_64 with systemd, independent of cloud provider. Explicit domain/public-IP/profile inputs; refuses foreign installations. Local dry-run is not a live installation.
- [Azure infrastructure templates](../infra/vpn/): VM, network and public-IP definitions used by infrastructure setup.
- Reusable read-only diagnosis and bounded speed tests live under `tools/`; their portable skills are under `skills/` at the toolkit root. Fast.com is a mode of `/vpn-speed`, not a separate skill. Supply your own private settings; no production targets are included. Diagnostics can run locally on the Ubuntu server without Azure; Azure CLI/Monitor are required only for the optional Azure mode.
- [Client profile format](../profiles/README.md) and [client exports](../docs/CLIENTS.md): keep credentials and generated connection files private.

Keep deployment plans, server inventory, management credentials, operational history, logs and rollback material outside this public repository. Protocol choices are `vless` and `hysteria2`; profile names identify your own configured connections. Cloud/egress charges, DNS/firewall changes, cutover and acceptance testing require their own explicit scope. Do not replay installation on a working server or expose public SSH/unauthenticated proxies as shortcuts.

Preserve a verified recovery path before changing a deployed service. Keep TLS verification and server private-network ACLs enabled. Listener/startup checks alone do not prove authenticated forwarding, invalid-auth rejection, device browsing, reboot recovery or future certificate renewal.
