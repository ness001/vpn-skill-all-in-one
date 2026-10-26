targetScope = 'resourceGroup'

@description('Azure region; the caller must verify approval, capacity and pricing before deployment.')
param location string = resourceGroup().location

@description('Explicitly approved x64 Gen2 VM size. There is no implicit compute-cost choice.')
@minLength(1)
param vmSize string

@description('Unique resource prefix in a dedicated new resource group; existing-server exclusions belong to the caller.')
@minLength(3)
@maxLength(40)
param resourcePrefix string

@description('Installer protocol: vless (WebSocket/TLS) or hysteria2. No value selects a region.')
@allowed(['vless', 'hysteria2'])
param profile string = 'vless'

@description('Verified Canonical Ubuntu 24.04 LTS Gen2 x64 image version; review before changing.')
param imageVersion string = '24.04.202609040'

@description('New Azure public-IP DNS label; the FQDN output includes an Azure-generated reuse-scope hash.')
@minLength(3)
@maxLength(63)
param dnsLabel string = toLower('${resourcePrefix}-${uniqueString(resourceGroup().id)}')

@description('Administrator for Azure guest-agent management; public SSH remains closed.')
param adminUsername string = 'vpnadmin'

@description('SSH public key only. Password authentication is disabled and inbound SSH stays blocked.')
@secure()
@minLength(1)
param sshPublicKey string

// One reusable template: approval, production exclusions and create-only checks are caller responsibilities.
var tags = {
  purpose: 'personal-vpn'
  location: location
}
var allowedTransports = profile == 'vless' ? [
  { protocol: 'Tcp', ports: ['80', '443'] }
] : [
  { protocol: 'Tcp', ports: ['443'] }
  { protocol: 'Udp', ports: ['443'] }
]

var allowRules = [for (transport, index) in allowedTransports: {
  name: 'Allow-Internet-${transport.protocol}'
  properties: {
    priority: 100 + index
    direction: 'Inbound'
    access: 'Allow'
    protocol: transport.protocol
    sourceAddressPrefix: 'Internet'
    sourcePortRange: '*'
    destinationAddressPrefix: '*'
    destinationPortRanges: transport.ports
  }
}]

resource networkSecurityGroup 'Microsoft.Network/networkSecurityGroups@2025-09-01' = {
  name: 'nsg-${resourcePrefix}'
  location: location
  tags: tags
  properties: {
    securityRules: concat(allowRules, [
      {
        // Override default VNet/load-balancer allows; SSH and unselected ports stay closed.
        name: 'Deny-All-Inbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ])
  }
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2025-09-01' = {
  name: 'vnet-${resourcePrefix}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: ['10.42.0.0/24']
    }
    subnets: [
      {
        name: 'snet-vpn'
        properties: {
          addressPrefix: '10.42.0.0/27'
          // Outbound uses the NIC's explicit public IP, not an implicit Azure IP.
          defaultOutboundAccess: false
          networkSecurityGroup: {
            id: networkSecurityGroup.id
          }
        }
      }
    ]
  }
}

resource publicIp 'Microsoft.Network/publicIPAddresses@2025-09-01' = {
  name: 'pip-${resourcePrefix}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
    dnsSettings: {
      domainNameLabel: dnsLabel
      domainNameLabelScope: 'ResourceGroupReuse'
    }
  }
}

resource networkInterface 'Microsoft.Network/networkInterfaces@2025-09-01' = {
  name: 'nic-${resourcePrefix}'
  location: location
  tags: tags
  properties: {
    enableAcceleratedNetworking: false
    enableIPForwarding: false
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          primary: true
          privateIPAddressVersion: 'IPv4'
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: virtualNetwork.properties.subnets[0].id
          }
          publicIPAddress: {
            id: publicIp.id
          }
        }
      }
    ]
  }
}

resource virtualMachine 'Microsoft.Compute/virtualMachines@2026-04-01' = {
  name: 'vm-${resourcePrefix}'
  location: location
  tags: tags
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    // B1ms does not require Trusted Launch; explicitly avoid its Gen2 default.
    securityProfile: {
      securityType: 'Standard'
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: imageVersion
      }
      osDisk: {
        name: 'osdisk-${resourcePrefix}'
        createOption: 'FromImage'
        diskSizeGB: 32
        caching: 'ReadWrite'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    osProfile: {
      computerName: 'vm-${resourcePrefix}'
      adminUsername: adminUsername
      allowExtensionOperations: true
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: networkInterface.id
          properties: {
            primary: true
          }
        }
      ]
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: false
      }
    }
  }
}

output resourceGroupName string = resourceGroup().name
output virtualMachineName string = virtualMachine.name
output networkSecurityGroupName string = networkSecurityGroup.name
output virtualNetworkName string = virtualNetwork.name
output networkInterfaceName string = networkInterface.name
output publicIpName string = publicIp.name
output osDiskName string = virtualMachine.properties.storageProfile.osDisk.name!
output publicIpAddress string = publicIp.properties.ipAddress
output fqdn string = publicIp.properties.dnsSettings.fqdn
