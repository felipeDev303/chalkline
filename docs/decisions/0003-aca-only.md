# 0003 — Azure Container Apps only
One developer, 11 days. ACA idles at cents/day; AKS costs dollars/day idle.
Decision: Docker Compose locally, ACA in Azure via Bicep. No AKS.
Public access for judges with rate limiting + Foundry budget (rule 4.8).
