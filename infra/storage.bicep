// Insight cache for the Pitchside demo: one keyless storage account and one private
// container. Readers and writers get Storage Blob Data Contributor (Entra ID only):
// a user locally (precompute), the container app's managed identity in Azure.
//
//   az deployment group create -g rg-pitchside -f infra/storage.bicep \
//     -p principalId=$(az ad signed-in-user show --query id -o tsv)

targetScope = 'resourceGroup'

param location string = resourceGroup().location

@description('Globally unique, 3-24 lowercase letters and digits.')
param accountName string = 'stpitch${uniqueString(resourceGroup().id)}'

param containerName string = 'insights'

@description('Object id that gets blob data access (a user locally, the app identity in Azure).')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

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

resource blobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(container.id, principalId, blobDataContributorRoleId)
  scope: container
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
  }
}

output containerUrl string = '${account.properties.primaryEndpoints.blob}${container.name}'
