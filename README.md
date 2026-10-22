# Pitchside

Explainable, personalized match intelligence from synthetic football events —
built for the Microsoft × Premier League *Inside the Game* hackathon.

| Stage | What it does |
|---|---|
| Ingest | Seeded simulator streams synthetic events (passes, shots, tackles, pressure, possession) |
| Interpret | Deterministic metrics: pass difficulty, shot speed, pressure, rhythm |
| Explain | Agents explain *why* a moment matters, grounded in tool outputs |
| Render | Timed, machine-readable overlay payloads + second-screen UI |
| Personalize | Analyst vs casual fan, favorite player focus, multiple languages |

**All data is synthetic.** Teams and players are fictional.

## Quick start
    uv sync
    uv run pytest -q

    # one synthetic match: line 1 metadata, then one event per line, plus the planted
    # tactical regimes as ground truth in data/match_42.truth.json (never read by metrics)
    uv run python -m pitchside.simulator --seed 42 --out data/match_42.jsonl

    # realism targets, detector evaluation and xT calibration on held-out seeds (~75 s)
    # writes docs/data/CALIBRATION.md
    uv run python scripts/calibrate.py

    # re-tune detector thresholds / refit the expected threat grid, on dev seeds 0-99 only
    uv run python scripts/tune_detectors.py
    uv run python scripts/fit_xt.py

Same seed, same bytes, on any OS. Current calibration: [docs/data/CALIBRATION.md](docs/data/CALIBRATION.md).
How every number is computed: [docs/METHODS.md](docs/METHODS.md).

## Agents (Microsoft Foundry)

Analyst -> narrator -> verifier on Microsoft Agent Framework, with the metric tools also
served over MCP (`python -m pitchside.agents.mcp_server --match <file>`). Keyless: run
`az login`, deploy `infra/foundry.bicep`, and set `FOUNDRY_PROJECT_ENDPOINT`,
`AI_MODEL_DEPLOYMENT` (and optionally `AI_MODEL_FALLBACK_DEPLOYMENT`) in your environment.

    # one turn of the desk; without the variables it shows the evidence-only fallback
    uv run python scripts/try_agents.py --match data/match_42.jsonl --minute 63 --lang es

    # ablation, desk vs single agent on held-out moments; writes docs/evaluation/
    uv run python scripts/evaluate_agents.py --round v2 --n 40

What is measured, and on which held-out seeds: [docs/EVALUATION.md](docs/EVALUATION.md).

Design: [docs/decisions/0005-agent-orchestration.md](docs/decisions/0005-agent-orchestration.md).

## License
MIT. See NOTICE.md for attributions.
