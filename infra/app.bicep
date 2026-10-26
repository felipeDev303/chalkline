// Chalkline on Azure Container Apps: the API + UI container, its registry, its
// identity and everything that identity may touch. Keyless end to end: a user-assigned
// managed identity pulls the image (AcrPull), calls the Foundry models (Foundry User)
// and reads/writes the insight cache (Storage Blob Data Contributor). No secrets.
//
// First deploy (placeholder image), then build/push and deploy again with `image`:
// see docs/DEPLOY.md.

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param name string = 'pitchside'

@description('The container app, which names its public URL (the product is Chalkline).')
param appName string = 'ca-chalkline'

@description('Existing Foundry account and project (infra/foundry.bicep).')
param foundryAccountName string
param foundryProjectName string = 'pitchside'
param primaryDeployment string = 'gpt-4.1-mini'
param fallbackDeployment string = 'gpt-5-mini'

@description('Container image; the default is a public placeholder for the first deploy.')
param image string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Object id of the developer who runs the precompute (gets blob access).')
param developerPrincipalId string

@description('Global daily cap on new (uncached) insights: bounds model spend.')
param insightsPerDay int = 300

var suffix = uniqueString(resourceGroup().id)
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Foundry User
var registryName = 'acr${name}${suffix}'
var loginServer = '${registryName}.azurecr.io'
var usesRegistry = startsWith(image, '${loginServer}/')

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-${name}'
  location: location
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: registryName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false // pulls with the managed identity, pushes with Entra ID
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' existing = {
  name: foundryAccountName
}

resource foundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, identity.id, foundryUserRoleId)
  scope: foundry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
  }
}

module storage 'storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    principals: [
      { id: identity.properties.principalId, type: 'ServicePrincipal' }
      { id: developerPrincipalId, type: 'User' }
    ]
  }
}

// This subscription gets Container Apps express environments (Sandboxes-based):
// consumption only, no workload profiles, no Azure Monitor log routing. Logs are
// read by streaming: az containerapp logs show -g rg-pitchside -n ca-pitchside --follow
resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'cae-${name}'
  location: location
  properties: {}
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: usesRegistry ? [{ server: loginServer, identity: identity.id }] : []
    }
    template: {
      containers: [
        {
          name: 'pitchside'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}' }
            { name: 'AI_MODEL_DEPLOYMENT', value: primaryDeployment }
            { name: 'AI_MODEL_FALLBACK_DEPLOYMENT', value: fallbackDeployment }
            { name: 'PITCHSIDE_CACHE_BLOB_URL', value: storage.outputs.containerUrl }
            { name: 'PITCHSIDE_INSIGHTS_PER_MIN', value: '6' }
            { name: 'PITCHSIDE_INSIGHTS_PER_DAY', value: string(insightsPerDay) }
            { name: 'FORWARDED_ALLOW_IPS', value: '*' } // only the ingress reaches the app
          ]
          probes: usesRegistry ? [
            {
              type: 'Startup'
              httpGet: { path: '/api/health', port: 8000 }
              periodSeconds: 5
              failureThreshold: 24 // the demo matches are simulated at startup
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/health', port: 8000 }
              periodSeconds: 15
            }
          ] : []
        }
      ]
      // One always-on replica: no cold start for judges, and the in-memory rate
      // limits and cache are exact. Idle replicas bill at the reduced idle rate.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [acrPull, foundryUser]
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
output registryLoginServer string = registry.properties.loginServer
output registryName string = registry.name
output cacheContainerUrl string = storage.outputs.containerUrl
