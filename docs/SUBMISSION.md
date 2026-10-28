# Submission text

The text submitted to the *Inside the Game* form (Oct 27, 2026).

## Project name

Chalkline

## One-line description

For live broadcast teams, Chalkline is an AI match desk that puts *what mattered and
why* on air in real time — where every number comes from tested code and is checked by
a verifier agent before it airs, or it doesn't air at all, and every model behind it is
measured against ground truth.

## Links

- Live demo (no login): https://ca-chalkline.greenforest-cf5df294.northcentralus.azurecontainerapps.io
- Source code: https://github.com/felipeDev303/chalkline
- Demo video: https://youtu.be/nsK9wkz4UUw

## The problem

Generative AI has moved from "can it write?" to "can it be trusted?". Anyone can now
generate fluent match commentary live, but on air a confident sentence with a wrong
number — possession, xG, win probability, who made the run — is worse than no
sentence: it forces a correction and damages trust, and no graphics desk has time to
check every figure live. So AI stays off air. Meanwhile live analytics is expected (xG,
win probability, pressing), yet today's indices have no definition, verifiers check that
an event exists rather than what was claimed about it, and models are judged by eye.

## Who it's for

Broadcast and live production teams first: put AI explanations and graphics on air
without airing a number the data doesn't support. The casual fan is who benefits —
"tell me what mattered and why, without making stuff up", in English or Spanish, at
their level. Clubs and analysts are a second market: the same measured, reproducible
tools are what they need to defend an insight internally.

## What it does

Chalkline is one pipeline in five stages, all on synthetic data:

1. **Ingest.** A seeded simulator streams a football-realistic match: passes, shots,
   tackles, pressure and possession, with all 22 players' positions at every event. It
   also plants ground truth (pressing spells, off-ball runs, the true probability of
   every shot and pass) in a file the metrics and agents can never read.
2. **Interpret.** Eleven deterministic tools compute expected goals and pass completion
   (fitted models), win probability, expected threat, control vs chaos, pressing shifts,
   and off-ball credit: which teammate's run made a pass possible, found by undoing the
   run and recomputing the space.
3. **Explain.** An agent desk on Microsoft Agent Framework explains each moment for a
   casual fan or an analyst, in English or Spanish. The narrator cites the facts behind
   every sentence; a deterministic verifier agent rejects any number that does not
   match the facts that sentence cites, and any misspelled name. One retry, then the
   narrative is hidden and only its evidence is shown.
4. **Render.** A broadcast view with a perspective camera, score bug, win-probability
   bar, a telestrator of the current move, and lower thirds aired by a producer agent
   that only knows what has happened so far; the on-air headlines are deterministic
   templates built from the facts alone. "The run that made it" replays a pass
   with and without the run. The overlay is a documented, versioned JSON contract.
5. **Personalize.** Casual or analyst, English or Spanish, side by side; follow a
   player; ask a question; and fact-check any commentator's line against what is known
   at that minute.

**Measured, on held-out matches:**

- expected goals are within 0.014 of the true scoring probability on average;
- win probability scores Brier 0.455 against final results (no information: 0.656);
- off-ball credit finds the real runner first 86% of the time (credit the receiver:
  44%);
- pressing-shift detection reaches precision 0.71 against planted pressing spells;
- a single LLM agent with tools airs a wrong or unsupported number 35-40% of the time,
  and with the verifier agent in the loop none reach the viewer (80 moments, live
  Microsoft Foundry).

We report what did not help too: splitting analyst and narrator added no measurable
quality over one agent plus the verifier.

## Impact

Before: one wrong number forces an on-air retraction, so AI stays off air. After: AI
explanations go on air with one-click evidence, documented methods and a fallback that
never airs an unsupported number. Cost scales with stories, not viewers: each verified
narrative is computed once per story, audience and language, and cached. The path to a
live feed (Event Hubs, Web PubSub, Cosmos DB, Foundry evaluations) starts in shadow mode
next to a human graphics desk — see `docs/PRODUCTION.md`.

## Microsoft technology used

- **Microsoft Foundry**: gpt-4.1-mini with a gpt-5-mini fallback for the analyst and
  narrator, on a keyless account (local auth disabled); Azure AI Speech for the
  video's voice-over.
- **Microsoft Agent Framework**: the desk is a workflow of executors (analyst,
  narrator, verifier) with a retry edge; failure recovery moves down a model chain,
  corrects tool errors, falls back to default evidence, and finally to evidence only.
- **Model Context Protocol**: the eleven metric tools are also served over MCP.
- **Azure Container Apps**: the API and UI in one container, one always-on replica.
- **Managed identity and Azure RBAC**: Foundry User, AcrPull and Storage Blob Data
  Contributor; no keys or connection strings anywhere.
- **Azure Container Registry** and **Azure Blob Storage**: the image and the cache of
  verified narratives, precomputed for every aired story so judges see them instantly.
- **Bicep and GitHub Actions**: infrastructure as code; 313 tests and a cross-OS
  reproducibility check on every push.

## Category

**Best Enterprise Solution.** Chalkline is built around the controls production needs:
every number traceable to a deterministic, tested tool and a documented method; every
AI sentence verified before it airs, with a recorded fallback when it is not; models
that are calibrated, auditable code instead of a black-box endpoint; keyless identity
end to end; a daily cap on model spend; and cost that scales with stories, not viewers.
Its claims are measured on held-out data and published, including what did not work.
The path to a live feed (Event Hubs, Web PubSub, Cosmos DB, Foundry evaluations) is in
`docs/PRODUCTION.md`.

*Alternative, if entering Best Multi-Agent System:* Chalkline's agents have distinct
roles and hand off through typed messages: a producer decides what airs from what is
known so far, an analyst picks among the metric tools (also served over MCP), a
narrator writes cited sentences, and a
verifier checks attribution and sends failures back once. It recovers from model
outages, tool errors and failed verification without ever airing an unverified number.
An ablation on 80 held-out moments shows the end-to-end outcome a single agent does not
reach: a lone agent airs errors 35-40% of the time; the verified pipeline, 0%.

## How to test

1. Open the live demo. The badge next to the logo reads **Foundry live**.
2. Pick **Halvesham Town v Westerlake City** and press **Next story**: "The run that
   made it" (11') replays the pass without the run, then with it (control 52% → 92%),
   and the desk shows a verified explanation. Tap an underlined sentence to see its
   evidence.
3. Press **Next goal** (27'): the goal airs and the win-probability bar moves from 45%
   to 77% for Westerlake.
4. Switch **Analyst**, **ES** or **Side by side**; follow a player with **Follow**.
5. In **Fact-check a line**, press **Try an example**: "85% possession" is flagged and
   the data says 52%.
6. Open **How it's measured** for the held-out results.

To run it locally (no Azure needed; without a model the desk shows evidence only):
`uv sync`, `uv run pytest -q`, `uv run python -m pitchside.api`. Details in the README.
