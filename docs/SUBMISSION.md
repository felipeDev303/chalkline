# Submission text

Copy-ready text for the *Inside the Game* submission form. Replace the video link once
the video is uploaded.

## Project name

Pitchside

## One-line description

Pitchside replays a football match and tells you what mattered and why, with every
number computed by tested code, every sentence checked by a verifier agent, and every
claim about the game measured against ground truth.

## Links

- Live demo (no login): https://ca-pitchside.greenforest-cf5df294.northcentralus.azurecontainerapps.io
- Source code: https://github.com/felipeDev303/pitchside
- Demo video: <YouTube or Vimeo link>

## The problem

Fans, broadcasters and clubs want to know *why* a moment mattered, not only that it
happened, and AI can now write that story live. But a confident sentence with a wrong
number is worse than no sentence, and today nobody can show that their AI insights are
right: indices have no definition, verifiers check that an event exists rather than
what was claimed about it, and models are judged by eye.

## What it does

Pitchside is one pipeline in five stages, all on synthetic data:

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
   that only knows what has happened so far. "The run that made it" replays a pass
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

## Microsoft technology used

- **Microsoft Foundry**: gpt-4.1-mini with a gpt-5-mini fallback for the analyst and
  narrator, on a keyless account (local auth disabled).
- **Microsoft Agent Framework**: the desk is a workflow of executors (analyst,
  narrator, verifier) with a retry edge; failure recovery moves down a model chain,
  corrects tool errors, falls back to default evidence, and finally to evidence only.
- **Model Context Protocol**: the eleven metric tools are also served over MCP.
- **Azure Container Apps**: the API and UI in one container, one always-on replica.
- **Managed identity and Azure RBAC**: Foundry User, AcrPull and Storage Blob Data
  Contributor; no keys or connection strings anywhere.
- **Azure Container Registry** and **Azure Blob Storage**: the image and the cache of
  verified narratives, precomputed for every aired story so judges see them instantly.
- **Bicep and GitHub Actions**: infrastructure as code; 312 tests and a cross-OS
  reproducibility check on every push.

## Category

**Best Enterprise Solution.** Pitchside is built around the controls production needs:
every number traceable to a deterministic, tested tool and a documented method; every
AI sentence verified before it airs, with a recorded fallback when it is not; models
that are calibrated, auditable code instead of a black-box endpoint; keyless identity
end to end; a daily cap on model spend; and cost that scales with stories, not viewers.
Its claims are measured on held-out data and published, including what did not work.
The path to a live feed (Event Hubs, Web PubSub, Cosmos DB, Foundry evaluations) is in
`docs/PRODUCTION.md`.

*Alternative, if entering Best Multi-Agent System:* Pitchside's agents have distinct
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
