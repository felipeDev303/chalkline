// Microsoft Foundry for the Chalkline agent desk: one AI Services account (keyless),
// one project, a primary and a fallback model deployment, and data-plane access.
//
//   az deployment group create -g rg-pitchside -f infra/foundry.bicep \
//     -p principalId=$(az ad signed-in-user show --query id -o tsv)

targetScope = 'resourceGroup'

@description('Region allowed by the subscription policy and with model quota.')
param location string = resourceGroup().location

@description('Globally unique account name; also the custom subdomain.')
param accountName string = 'pitchside-${uniqueString(resourceGroup().id)}'

param projectName string = 'pitchside'

@description('Object id that gets the Foundry User role (a user locally, the app identity in Azure).')
param principalId string

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

param primaryModel string = 'gpt-4.1-mini'
param primaryVersion string = '2025-04-14'
param fallbackModel string = 'gpt-5-mini'
param fallbackVersion string = '2025-08-07'

@description('Tokens per minute, in thousands, per deployment. Kept well below quota as a cost cap.')
param capacityK int = 50

var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Foundry User

resource account 'Microsoft.CognitiveServices/accounts@2026-07-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    disableLocalAuth: true // keyless: Entra ID only
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-07-01' = {
  parent: account
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Chalkline'
    description: 'Explainable match intelligence from synthetic football events.'
  }
}

resource primary 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: account
  name: primaryModel
  sku: { name: 'GlobalStandard', capacity: capacityK }
  properties: {
    model: { format: 'OpenAI', name: primaryModel, version: primaryVersion }
  }
  dependsOn: [project] // the account accepts one operation at a time
}

resource fallback 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: account
  name: fallbackModel
  sku: { name: 'GlobalStandard', capacity: capacityK }
  properties: {
    model: { format: 'OpenAI', name: fallbackModel, version: fallbackVersion }
  }
  dependsOn: [primary] // deployments on one account are created one at a time
}

resource foundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, principalId, foundryUserRoleId)
  scope: account
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
  }
}

output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output primaryDeployment string = primary.name
output fallbackDeployment string = fallback.name
