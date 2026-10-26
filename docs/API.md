# API

One process serves the API and the UI (`uv run python -m pitchside.api`, then
<http://127.0.0.1:8000>; interactive docs at `/docs`). The replay is client-driven: the
client advances `as_of_seq` and asks for the overlay, so the server holds no session.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | status, schema and overlay versions, connected models |
| GET | `/api/matches` | demo matches (`PITCHSIDE_DEMO_SEEDS`, default `42,7,3`) |
| GET | `/api/matches/{id}` | teams, players, `first_seq`, `last_seq` |
| GET | `/api/matches/{id}/overlay?as_of_seq=N` | `Overlay` at event N (below) |
| GET | `/api/matches/{id}/stories?as_of_seq=N` | every story aired by N, in airing order |
| GET | `/api/overlay/schema` | JSON Schema of `Overlay` |
| GET | `/api/tools` | tool schemas (the same the MCP server exposes) |
| POST | `/api/matches/{id}/tools/{name}` | one tool's `ToolResult`; body: its arguments |
| POST | `/api/matches/{id}/insights` | the agent desk's `Insight`; body: `TurnRequest` |
| POST | `/api/matches/{id}/stories/{story_id}/insights` | the same for one aired story; body: `persona`, `language` |

## Timed overlay (`overlay_version` 1.1.0)

Everything the screen shows next to the match at event `as_of_seq`, computed only from
events up to it. It is deterministic and needs no model, so it is instant.

- `minute`, `period`, `clock_s`, `score` (team id → goals), `possession_team_id`;
- `win_probability`: `home`, `draw`, `away` from here (`win_probability` tool; 1.1.0);
- `last_event`: type, team, player, location (and end and outcome for passes);
- `players`: the latest known position of all 22 players (absolute metres, 105×68);
- `stories`: the 5 most recent stories on air, newest first. Each has its `kind`,
  the event it is about (`seq`), when the producer aired it (`aired_at_seq`), a
  `headline` in `en` and `es` and the `facts` every headline number comes from.
  A `decisive_run` story also has a `ghost`: the runner's position with and without
  their run, the pass and every player at the moment of the pass, for drawing "the
  run that made it".

## Insights

`TurnRequest`: `as_of_seq`, `kind` (`moment`, `recap`, `question`), `persona`
(`casual`, `analyst`), `language` (`en`, `es`), optional `question` (at most 300
characters). The desk (analyst → narrator → verifier) answers with an `Insight`:
`status` (`verified`, `verified_after_retry`, `evidence_only`), the verified sentences
with their cited `evidence_ids`, the evidence, every tool result of the turn (method,
caveats, cannot tell), attempts, model, tokens and recovery notes.

- Models: Microsoft Foundry when `FOUNDRY_PROJECT_ENDPOINT` and `AI_MODEL_DEPLOYMENT`
  are set (keyless: `az login` locally, managed identity in Azure). Without them every
  insight is `evidence_only`.
- Cache: by match and request, in memory and then in a private Azure Blob container
  (`PITCHSIDE_CACHE_BLOB_URL`, keyless, `infra/storage.bicep`) or a local folder
  (`PITCHSIDE_CACHE_DIR`). A story's request is built server-side, so the answers
  `scripts/precompute_insights.py` stores before judging are the ones the UI gets
  (ADR 0007). A turn whose narrator was unavailable is not cached, so the next
  viewer retries.
- Limits: `PITCHSIDE_INSIGHTS_PER_MIN` new insights per client per minute (default 6;
  cached answers are free; no limit without a model), at most 2 desks at a time.
