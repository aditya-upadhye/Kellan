targetScope = 'resourceGroup'

@description('Azure region for the Kellan resources. Use a region enabled for the subscription and selected Foundry models.')
param location string = 'westus2'

@description('Azure region for Cosmos DB. Defaults to the main deployment region; override if Cosmos DB capacity is unavailable there.')
param cosmosLocation string = location

@description('Short environment name used in resource names.')
@minLength(2)
@maxLength(8)
param environmentName string = 'prod'

@description('API image to retain during provisioning. The deployment workflow supplies the current image for existing apps.')
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Web image to retain during provisioning. The deployment workflow supplies the current image for existing apps.')
param webImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

var suffix = uniqueString(subscription().id, resourceGroup().id)
var baseName = 'ml${environmentName}${suffix}'
var names = {
  identity: '${baseName}-id'
  workspace: '${baseName}-law'
  insights: '${baseName}-appi'
  environment: '${baseName}-standard-aca'
  api: 'kellan-api'
  web: 'kellan-web'
  eventHubs: '${baseName}-eh'
  cosmos: '${baseName}-cosmos'
  foundry: '${baseName}-ai'
  registry: replace('${baseName}acr', '-', '')
  project: 'matchlens-${environmentName}'
}

module platform 'modules/platform.bicep' = {
  name: 'matchlens-platform-${suffix}'
  params: {
    location: location
    cosmosLocation: cosmosLocation
    environmentName: environmentName
    names: names
    apiImage: apiImage
    webImage: webImage
  }
}

output location string = location
output identityId string = platform.outputs.identityId
output AZURE_CONTAINER_APPS_IDENTITY_ID string = platform.outputs.identityId
output identityPrincipalId string = platform.outputs.identityPrincipalId
output containerAppsEnvironmentId string = platform.outputs.containerAppsEnvironmentId
output containerRegistryName string = platform.outputs.containerRegistryName
output containerRegistryLoginServer string = platform.outputs.containerRegistryLoginServer
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = platform.outputs.containerRegistryLoginServer
output eventHubsNamespace string = platform.outputs.eventHubsNamespace
output eventHubsFqdn string = platform.outputs.eventHubsFqdn
output cosmosEndpoint string = platform.outputs.cosmosEndpoint
output cosmosDatabase string = platform.outputs.cosmosDatabase
output foundryProjectEndpoint string = platform.outputs.foundryProjectEndpoint
output fastModel string = 'gpt-4.1-mini'
output strongModel string = 'gpt-4.1'
output applicationInsightsConnectionString string = platform.outputs.applicationInsightsConnectionString
output webUrl string = platform.outputs.webUrl
