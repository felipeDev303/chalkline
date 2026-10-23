// Insight cache for the Pitchside demo: one keyless storage account and one private
// container. Readers and writers get Storage Blob Data Contributor (Entra ID only):
// the container app's managed identity, and the developer who runs the precompute.
// Deployed as a module of infra/app.bicep.

targetScope = 'resourceGroup'

param location string = resourceGroup().location

@description('Globally unique, 3-24 lowercase letters and digits.')
param accountName string = 'stpitch${uniqueString(resourceGroup().id)}'

param containerName string = 'insights'

@description('Who gets blob data access: [{ id: objectId, type: \'User\' | \'ServicePrincipal\' }].')
param principals array

var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' // Storage Blob Data Contributor

resource account 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: accountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false // keyless: Entra ID only
    allowBlobPublicAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: account
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: containerName
  properties: { publicAccess: 'None' }
}

resource blobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for p in principals: {
  name: guid(container.id, p.id, blobDataContributorRoleId)
  scope: container
  properties: {
    principalId: p.id
    principalType: p.type
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
  }
}]

output containerUrl string = '${account.properties.primaryEndpoints.blob}${container.name}'
