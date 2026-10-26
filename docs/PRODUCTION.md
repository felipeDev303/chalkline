# Path to production

Pitchside runs today on synthetic matches, in one container on Azure Container Apps.
This is how it becomes a production service for a broadcaster, a league app or a club,
and what does not have to change.

## What carries over unchanged

- **The event contract.** Every stage reads `events/schema.py` (versioned,
  `schema_version` on every event and match). A real data provider is an adapter that
  writes this schema; metrics, agents and the overlay never see the source.
- **No look-ahead by construction.** Every tool is a pure function of the events up to
  `as_of_seq`, so live and replay are the same code path.
- **The trust contract.** Numbers come only from deterministic tools; every sentence
  cites its facts; the verifier blocks anything unsupported; a failed narrative falls
  back to evidence, never to an unverified claim.
- **Cost that scales with stories, not viewers.** A verified narrative is computed once
  per story, audience and language and cached; a million viewers of one goal cost one
  set of model calls (about 10k tokens each).
- **Keyless operation.** Managed identity and Azure RBAC for the model, the registry and
  storage; no secrets to rotate.

## What changes

| Area | Demo today | Production |
|---|---|---|
| Ingest | Seeded simulator, matches built at startup | Provider feed adapter → **Azure Event Hubs**; a consumer on Container Apps appends events per match and advances `as_of_seq` |
| Render | Client polls `GET /overlay` | Overlays pushed with **Azure Web PubSub** (one group per match); the same versioned overlay contract |
| Explain | Desk runs on demand, cached in Blob | Desk triggered by the producer when a story airs, so narratives are ready before viewers ask; **Foundry** evaluations (groundedness) as a second, independent check; tracing to **Application Insights** |
| Personalize | Persona and language in the request | Viewer profiles (favourite club and player, language) in **Azure Cosmos DB**; the producer's budget per profile |
| Scale and access | One replica, per-client and daily limits | API Management for per-tenant quotas, Front Door, several replicas; the cache moves to Blob plus a CDN for overlays |
| Operations | Bicep, GitHub Actions, budget alert | Same Bicep per environment, staged rollout, alerts on model errors, cache hit rate and verifier rejection rate |

## Earning trust on real data

The demo's strongest claim, that every number is measured against ground truth, rests
on the simulator planting that truth. Real football has no planted truth, so the
evidence changes:

1. **Refit the models on licensed historical data** (`scripts/fit_models.py` takes any
   event set in the schema) and evaluate on held-out seasons: calibration of xG and pass
   completion against outcomes, win probability against results, as the demo already
   does against its truth.
2. **Validate the detectors with analysts.** Pressing shifts and decisive runs flagged
   on a held-out season are labelled by analysts; precision and recall are reported the
   same way as in `docs/data/CALIBRATION.md`.
3. **Shadow mode first.** Pitchside's stories and narratives run alongside a human
   graphics desk; only what the desk would have aired, and what passes the verifier, is
   compared before anything goes to air.
4. **Monitor drift.** Calibration and verifier rejection rates are tracked per match;
   a model that drifts is refitted, not patched.

## Known gaps to close

- Positions are per event without velocities; with tracking data, the off-ball
  counterfactual and the control model can use player speeds.
- The simulator has no corners, cards or substitutions; the schema and tools need those
  event types for real matches.
- Free-text fact-checking attributes numbers with a fixed English and Spanish word list;
  more languages need their word lists and tests.
