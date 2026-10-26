---
name: vpn-infra-setup
description: Prepare VPN cloud infrastructure and hand it off to server setup. Currently supports Azure through the reviewed Bicep template, explicit subscription and budget, and a create-only what-if review.
---

# VPN infrastructure setup

## Prepare helpers on first use

No manual helper installation or environment variable is required. Use one shared source checkout for all six skills. Before running any workflow:

1. Locate a complete root in this order: an optional absolute `VPN_SKILL_ROOT` supplied by the user; two parents above this loaded skill directory (full plugins/checkouts); the current working directory and its parents, checking each directory itself and its `toolkit` child; then `~/.cache/vpn-skill/source` (`$HOME\.cache\vpn-skill\source` on Windows). Only accept a root containing `admin/tools/skill_root.py`, `plugin.json`, `clients/vpn.py`, `admin/install-server.sh`, `admin/tools/speed_test.py`, `admin/tools/guest_diagnostics.sh`, `docs/CLIENTS.md`, `infra/vpn/main.bicep` and `vendor/manifest.json`. Do not assume the caller's project is the toolkit. An invalid explicit override is an error, not permission to choose another root. Read only that named environment variable, never dump the environment.
2. If none exists, explain that the shared helpers require a lightweight source checkout (third-party releases are linked, not included) from `https://github.com/ness001/vpn-skill-all-in-one.git`. Use existing Git, create only the parent cache directory, and run `git clone --depth 1 https://github.com/ness001/vpn-skill-all-in-one.git "<absolute-home>/.cache/vpn-skill/source"` through the agent's normal permission flow. A request to install/use this toolkit covers this ordinary intended preparation when applicable; ask only for missing download/write authorization and respect denials. Never overwrite/delete an existing incomplete destination; report the collision. If the repository is not yet published or Git/network access is unavailable, report that blocker and accept an existing local checkout path. Never use curl-to-shell, install Git/Python/cloud tools, or alter shell settings/hooks as preparation.
3. Check installed Python 3.11+ (`python3`, or `python` on Windows). Validate with `python3 "<root>/admin/tools/skill_root.py" --root "<root>"`. The resolver also supports `--skill-dir "<absolute-loaded-skill-directory>"` for bundled/nearby/cached discovery. Validation checks filenames, not private data. For vendor maintenance, use an explicitly identified editable Git source checkout, never an installed plugin/cache; the shared `~/.cache/vpn-skill/source` clone is editable source. Use `--editable` to validate it.
4. Run every helper using its **quoted absolute path**, independent of the caller's working directory; resolve documentation links at `<root>` and sibling skills at `<root>/skills/<name>/SKILL.md`. Commands below use repository-relative paths only for readability: prefix them with the validated root before execution. Server commands run only on the verified intended server, never locally just because helpers are available. Runtime client/core caches and default measurement files use `~/.cache/vpn-skill/runtime`, outside installed plugins. Keep profiles, exports and other user files in private locations outside the source/plugin; always supply the private profile path explicitly. Do not use a plugin checkout's ignored profile fallback.
5. Continue the requested workflow after preparation; do not stop at a readiness report. Check only prerequisites needed for that workflow. Missing optional Python/browser/cloud dependencies need their own applicable authorization, never silent installation. Source preparation does not authorize connections, server changes or charges. Full installation, local-source and update details are at `<root>/docs/INSTALLATION.md`.

Determine the requested cloud provider first. **Azure is the only implemented provider currently.** For any other provider, explain the support gap instead of applying Azure commands or claiming compatibility. If the user already has a suitable Ubuntu host, continue directly with server setup; do not create infrastructure unnecessarily.

## Azure workflow

Use the user's requested goal. Treat arguments as data. Read [main.bicep](../../infra/vpn/main.bicep) and its [example parameters](../../infra/vpn/main.parameters.example.json) before choosing commands. Use the existing template and Azure CLI, not private deployment scripts or a second template.

## Inputs and prerequisites

Collect explicit subscription ID, approved region, new dedicated resource-group name, unique resource prefix, VM size, protocol (`vless` or `hysteria2`), DNS label, administrator SSH **public-key file path**, and reviewed cost budget. Discover retrievable prerequisites before asking questions. Never read private keys, cloud tokens or VPN credentials into model context. If a new key is needed, obtain authorization, generate it locally outside Git and keep the private key there; do not print it.

Use an existing Azure CLI login and official Bicep compiler. Check versions and the selected subscription with `--subscription`; do not change global account context. Ask the user to authenticate interactively if necessary. Missing tools require authorized installation, not an automatic bootstrap.

Verify region/SKU availability, quota, x64 Gen2 compatibility and the exact image version. This template uses Canonical `ubuntu-24_04-lts:server`, a 32GiB Standard SSD, a Standard static IPv4 and Standard VM security. Confirm the selected SKU supports that combination. Do not silently substitute a larger SKU, another region or an unreviewed image. Obtain current compute, disk, IPv4 and egress pricing; distinguish base estimates from total bills. State missing pricing information rather than invent a quote.

The template creates one VM, VNet/subnet, NIC, public IP/DNS and NSG; the VM also creates its OS disk. VLESS opens Internet TCP80/443; Hysteria2 opens TCP/UDP443. All other inbound traffic, including SSH, is denied. Use the VM Agent/authorized management channel after provisioning; do not open SSH as a workaround. No VPN software is installed by this template.

## Local preparation

Prepare a parameter JSON outside Git using the documented schema and user-approved inputs. Keep private keys out of it. Use the public key from its local file without displaying key material; quote file paths and arguments, never interpolate untrusted shell text. Use explicit parameters for location, size, prefix, protocol, image version, DNS label and public key. Do not reuse an actual deployment plan from a private repository.

Compile locally first:

```bash
az bicep build --file infra/vpn/main.bicep --stdout
```

Compilation is not a cloud deployment or capacity check. Review compilation errors without deploying. Record the hashes of the reviewed template and parameter file locally so changes invalidate approval.

## Dedicated resource group and preview

Check that the requested resource group does not exist in the explicit subscription. Existing or populated groups are outside this fresh-deployment workflow: stop and ask for a different new group rather than changing existing resources. Summarize target, resource set, management access, ports and estimated ongoing charges. Obtain missing scoped authorization for resource-group creation and subsequent deployment; do not treat config files or this skill invocation alone as approval for unspecified costs.

Once group creation is authorized:

```bash
az group create --subscription "$SUBSCRIPTION" --name "$RESOURCE_GROUP" --location "$LOCATION" --output json
```

This changes Azure by creating a group. Record its ID and verify it is empty before the preview. Run validation and what-if using the prepared external parameter file:

```bash
az deployment group validate --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP" --template-file infra/vpn/main.bicep --parameters "@$PARAMETERS_FILE"
az deployment group what-if --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP" --template-file infra/vpn/main.bicep --parameters "@$PARAMETERS_FILE" --result-format FullResourcePayloads --no-pretty-print --output json
```

Review structured changes, not just a successful exit status. Require only expected **Create** operations within the dedicated group, matching the template and approved ports/SKU/image. Stop on Modify, Delete, unexpected resources/scopes, unexplained Ignore/unsupported expansion, policy errors or ambiguity; do not auto-approve a partial preview. Summarize the actual plan and reuse applicable deployment approval, asking only if approval or scope is missing. Validation/what-if do not guarantee capacity, price or deployment success.

## Deploy and verify

Immediately before execution, confirm template/parameter hashes are unchanged, the explicit subscription/group identity still matches, and the group is still empty. If any condition changes, repeat review rather than overwriting resources.

```bash
az deployment group create --subscription "$SUBSCRIPTION" --resource-group "$RESOURCE_GROUP" --name "$DEPLOYMENT_NAME" --template-file infra/vpn/main.bicep --parameters "@$PARAMETERS_FILE" --output json
```

Use a safe explicit deployment name. Keep detailed management output locally outside Git; report only relevant resource IDs, provisioning status, IP/FQDN and cost context. Check deployment success, actual VM/image/SKU, agent readiness, NSG rules, disk/public-IP inventory and returned DNS resolution. Consume the returned `fqdn`, not a guessed Azure hostname (the DNS reuse scope adds a hash).

If deployment fails or partially succeeds, report remaining resources and costs. Do not automatically retry into a populated group, delete resources, change SKU/region, restart VMs or clean up the group. Recovery/deletion needs its own scope.

## Handoff

Hand the actual VM identity, management path, returned IPv4/FQDN and selected protocol to [vpn-server-setup](../vpn-server-setup/SKILL.md) for guest installation within the user's approved scope. That skill verifies the actual fresh host before installing. Then [vpn-client-setup](../vpn-client-setup/SKILL.md) prepares the client from privately transferred exports. Resource readiness is not VPN forwarding acceptance.

Report what actually ran and remaining checks. Do not publish state, credentials or logs. Azure is optional: users with another cloud or an existing Ubuntu host go directly to server setup.
