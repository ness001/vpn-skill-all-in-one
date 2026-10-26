"""Local template contracts; requires Azure CLI + Bicep, never contacts Azure."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent


class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        az = shutil.which("az")
        if not az:
            raise unittest.SkipTest("Optional Azure CLI and its official Bicep compiler are unavailable")
        result = subprocess.run(
            [az, "bicep", "build", "--file", str(ROOT / "main.bicep"), "--stdout"],
            capture_output=True, text=True, timeout=120, check=True,
        )
        if result.stderr.strip():
            raise AssertionError(result.stderr)
        cls.template = json.loads(result.stdout)
        cls.resources = {r["type"].split("/")[-1]: r for r in cls.template["resources"]}

    def test_only_minimal_group_scoped_resources(self):
        self.assertIn("2019-04-01/deploymentTemplate.json", self.template["$schema"])
        self.assertEqual(set(self.resources), {
            "virtualMachines", "networkSecurityGroups", "virtualNetworks",
            "networkInterfaces", "publicIPAddresses",
        })
        for resource in self.resources.values():
            self.assertEqual(resource["location"], "[parameters('location')]")
            self.assertIn("parameters('resourcePrefix')", resource["name"])
            self.assertNotIn("scope", resource)

    def test_reusable_inputs_and_placeholder_example(self):
        parameters = self.template["parameters"]
        self.assertEqual(parameters["location"]["defaultValue"], "[resourceGroup().location]")
        for name in ("vmSize", "resourcePrefix", "sshPublicKey"):
            self.assertNotIn("defaultValue", parameters[name])
        self.assertEqual(parameters["sshPublicKey"]["type"].lower(), "securestring")
        self.assertEqual(parameters["profile"]["allowedValues"], ["vless", "hysteria2"])
        self.assertEqual(parameters["profile"]["defaultValue"], "vless")
        example = json.loads((ROOT / "main.parameters.example.json").read_text())["parameters"]
        self.assertLessEqual(set(example), set(parameters))
        self.assertEqual(example["profile"]["value"], "vless")
        self.assertTrue(example["location"]["value"].startswith("REPLACE_WITH_"))
        self.assertTrue(example["sshPublicKey"]["value"].startswith("REPLACE_WITH_"))

    def test_profile_port_selection_and_deny_override(self):
        variables = self.template["variables"]
        self.assertEqual(variables["allowedTransports"],
            "[if(equals(parameters('profile'), 'vless'), "
            "createArray(createObject('protocol', 'Tcp', 'ports', createArray('80', '443'))), "
            "createArray(createObject('protocol', 'Tcp', 'ports', createArray('443')), "
            "createObject('protocol', 'Udp', 'ports', createArray('443'))))]")
        rule = next(item for item in variables["copy"] if item["name"] == "allowRules")["input"]["properties"]
        self.assertEqual(rule["sourceAddressPrefix"], "Internet")
        self.assertEqual((rule["access"], rule["direction"]), ("Allow", "Inbound"))
        rules = self.resources["networkSecurityGroups"]["properties"]["securityRules"]
        for fragment in ("concat(variables('allowRules')", "'priority', 4096", "'access', 'Deny'",
                         "'direction', 'Inbound'", "'protocol', '*'", "'sourceAddressPrefix', '*'",
                         "'destinationAddressPrefix', '*'", "'destinationPortRange', '*'"):
            self.assertIn(fragment, rules)

    def test_network_is_isolated_and_explicitly_addressed(self):
        subnet = self.resources["virtualNetworks"]["properties"]["subnets"][0]["properties"]
        self.assertFalse(subnet["defaultOutboundAccess"])
        self.assertIn("Microsoft.Network/networkSecurityGroups", subnet["networkSecurityGroup"]["id"])
        nic = self.resources["networkInterfaces"]["properties"]
        self.assertFalse(nic["enableAcceleratedNetworking"])
        self.assertFalse(nic["enableIPForwarding"])
        self.assertIn("publicIPAddress", nic["ipConfigurations"][0]["properties"])
        ip = self.resources["publicIPAddresses"]
        self.assertEqual(ip["sku"], {"name": "Standard", "tier": "Regional"})
        self.assertEqual(ip["properties"]["publicIPAllocationMethod"], "Static")
        self.assertEqual(ip["properties"]["publicIPAddressVersion"], "IPv4")
        self.assertEqual(ip["properties"]["dnsSettings"]["domainNameLabelScope"], "ResourceGroupReuse")

    def test_vm_uses_small_disk_key_only_auth_and_agent(self):
        vm = self.resources["virtualMachines"]["properties"]
        self.assertEqual(vm["securityProfile"], {"securityType": "Standard"})
        self.assertEqual(vm["storageProfile"]["imageReference"], {
            "publisher": "Canonical", "offer": "ubuntu-24_04-lts", "sku": "server",
            "version": "[parameters('imageVersion')]",
        })
        disk = vm["storageProfile"]["osDisk"]
        self.assertEqual(disk["diskSizeGB"], 32)
        self.assertEqual(disk["managedDisk"]["storageAccountType"], "StandardSSD_LRS")
        self.assertNotIn("dataDisks", vm["storageProfile"])
        self.assertNotIn("adminPassword", vm["osProfile"])
        linux = vm["osProfile"]["linuxConfiguration"]
        self.assertTrue(linux["disablePasswordAuthentication"])
        self.assertTrue(linux["provisionVMAgent"])
        self.assertEqual(linux["ssh"]["publicKeys"][0]["keyData"], "[parameters('sshPublicKey')]")
        self.assertFalse(vm["diagnosticsProfile"]["bootDiagnostics"]["enabled"])

    def test_outputs_are_names_and_endpoints_only(self):
        outputs = self.template["outputs"]
        self.assertEqual(set(outputs), {
            "resourceGroupName", "virtualMachineName", "networkSecurityGroupName",
            "virtualNetworkName", "networkInterfaceName", "publicIpName", "osDiskName",
            "publicIpAddress", "fqdn",
        })
        self.assertNotIn("sshPublicKey", json.dumps(outputs))
        self.assertNotIn("adminUsername", json.dumps(outputs))


if __name__ == "__main__":
    unittest.main()
