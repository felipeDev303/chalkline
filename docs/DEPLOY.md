# Deploy

Everything runs in one resource group (`rg-pitchside`, North Central US) on an
Azure for Students subscription, keyless end to end: no keys, connection strings or
passwords exist anywhere.

| Resource | Bicep | Notes |
|---|---|---|
| Microsoft Foundry account + project, gpt-4.1-mini and gpt-5-mini deployments | `infra/foundry.bicep` | local auth disabled; 50k tokens/min per deployment as a cost cap |
| Budget alert | `infra/budget.bicep` | subscription scope |
| User-assigned managed identity `id-pitchside` | `infra/app.bicep` | AcrPull, Foundry User, Storage Blob Data Contributor |
| Container registry (Basic) | `infra/app.bicep` | admin user disabled; push with Entra ID |
| Storage account + private `insights` container | `infra/storage.bicep` (module) | shared keys and public access disabled |
| Container Apps environment + app `ca-chalkline` | `infra/app.bicep` | express environment, one always-on replica |

## Steps

```powershell
$me = az ad signed-in-user show --query id -o tsv
$foundry = "<foundry account name>"   # output of infra/foundry.bicep

# 1. Infra with a public placeholder image (creates the registry).
az deployment group create -g rg-pitchside -n chalkline-app -f infra/app.bicep `
  -p foundryAccountName=$foundry developerPrincipalId=$me

# 2. Build and push (Entra ID login, no admin user).
$acr = az deployment group show -g rg-pitchside -n chalkline-app --query properties.outputs.registryName.value -o tsv
az acr login -n $acr
$tag = "$acr.azurecr.io/pitchside:$(git rev-parse --short HEAD)"
docker build -t $tag .
docker push $tag
# Deploy by digest: a tag the app once failed to find can stay "not found" for a while.
$img = "$acr.azurecr.io/pitchside@" + (az acr repository show -n $acr --image $tag.Split('/')[1] --query digest -o tsv)

# 3. Point the app at the image.
az deployment group create -g rg-pitchside -n chalkline-app -f infra/app.bicep `
  -p foundryAccountName=$foundry developerPrincipalId=$me image=$img
```

The app URL is the `url` output. Logs: `az containerapp logs show -g rg-pitchside -n
ca-chalkline --follow`.

## Precomputed insights

Before judging, every aired story of the demo matches is explained once per persona
and language and stored in the Blob container (ADR 0007), so judges get verified
narratives instantly and the model is only called for new questions:

```powershell
$env:PITCHSIDE_CACHE_BLOB_URL = "<cacheContainerUrl output>"
$env:FOUNDRY_PROJECT_ENDPOINT = "<projectEndpoint output of foundry.bicep>"
$env:AI_MODEL_DEPLOYMENT = "gpt-4.1-mini"; $env:AI_MODEL_FALLBACK_DEPLOYMENT = "gpt-5-mini"
uv run python scripts/precompute_insights.py --dry-run   # how many are missing
uv run python scripts/precompute_insights.py
```

## Cost guards

- New (uncached) insights: 6 per client per minute and 300 per day across all
  clients (`PITCHSIDE_INSIGHTS_PER_MIN`, `PITCHSIDE_INSIGHTS_PER_DAY`); cached answers
  are free and unlimited. About 10k tokens per insight.
- Foundry deployments are capped at 50k tokens per minute; a subscription budget alerts.
- One replica of 0.5 vCPU / 1 GiB; idle time bills at the reduced idle rate.

## Express environment

This subscription creates Container Apps environments in express mode (built on
Container Apps Sandboxes). It supports what the app needs (HTTP ingress, user-assigned
identity for runtime and image pulls, health probes, replicas, log streaming) but not
workload profiles or Azure Monitor log routing, so `app.bicep` sets neither.
