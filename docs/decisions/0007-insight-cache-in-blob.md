# 0007 — Precomputed insights live in Azure Blob, keyless

Context: judges must see verified narratives instantly and the demo must stay up until
Nov 10 within a student budget. Generated data is never committed (CLAUDE.md), so the
precomputed desk answers cannot ship in the repo or be baked into the image without
calling the model on every build.

Decision:
- `scripts/precompute_insights.py` runs the desk once per aired story x persona x
  language of the demo matches and writes each `Insight` as JSON to a private Blob
  container (`infra/storage.bicep`). The app reads the same keys
  (`api/cache.py`: hash of match + TurnRequest; story turns are built server-side so
  both agree).
- Keyless: the storage account has shared keys disabled; the app's managed identity
  and the developer get Storage Blob Data Contributor on the container. Azure Files
  was rejected because a Container Apps volume mount needs the account key.
- Turns whose narrator was unavailable are never stored; a rerun or the next viewer
  retries them. Free questions and recaps at arbitrary moments are answered live,
  rate-limited, and cached the same way.
- Locally the store is a folder under `data/` (`PITCHSIDE_CACHE_DIR`).
