# Client configuration samples

These placeholders explain native core formats; they are **not working connections** or the toolkit profile-bundle schema. Use [client setup](../skills/vpn-client-setup/SKILL.md) with your existing core/CLI/GUI and private configuration. Toolkit Python commands accept the documented [profile bundle](../profiles/README.md).

- `vless-client.example.json`: VLESS/WebSocket/TLS with loopback SOCKS10808 and HTTP10809.
- `hysteria2-client.example.json`: Hysteria2 with verified TLS and the same local ports.
- `http-proxy.pac`: optional browser PAC for an already-running local HTTP proxy; localhost is direct and public requests have no direct fallback.

Never replace tracked examples with credentials or overwrite live server files with placeholders. Keep private profiles and exports outside public Git repositories. Bundled software and notices are under [vendor/](../vendor/README.md).
