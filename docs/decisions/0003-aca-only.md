# 0003 — Azure Container Apps only
One developer, 11 days. ACA idles at cents/day; AKS costs dollars/day idle.
Decision: Docker Compose locally, ACA in Azure via Bicep. No AKS.
Public access for judges with rate limiting + Foundry budget (rule 4.8).

Update (Oct 22): the subscription provisions ACA environments in express mode, which
has no workload profiles or Azure Monitor log routing; the app needs neither (logs are
streamed). Image registry: ACR Basic, pulled with the app's managed identity. See
docs/DEPLOY.md.
