# Pitchside — Inside the Game hackathon (Microsoft × Premier League)

Explainable, personalized match intelligence from **synthetic** football events.
Deadline: Oct 27 2026, 23:59 PT. All submission materials in English.

## Non-negotiables
- All data is synthetic, produced by `src/pitchside/simulator`. No real match data,
  footage, real club/player names, or Premier League marks.
- Deterministic, tested code computes every number. Models only pick tools and explain.
- Every number in generated text must match a tool output (grounding check).
  On failure: one retry, then hide the narrative and show the evidence.
- No secrets in code. Azure auth is keyless (Entra ID / managed identity). Never read `.env`.
- Generated data goes to `data/` (gitignored). Only tiny hand-written fixtures in `tests/fixtures/`.

## Pipeline (one stage per package)
ingest → `events/` + `simulator/` · interpret → `metrics/` ·
explain + personalize → `agents/` · render → `api/`

## Rules and decisions
@docs/hackathon/RULES-SUMMARY.md
- Official wiki (read-only): ../wiki/
- Decisions: docs/decisions/. Don't reopen a recorded decision without asking.

## Commands
- `uv sync` · `uv run pytest -q` · `uv run ruff check .`
- Run tests and ruff before proposing a commit.

## Conventions
- Python 3.12, pydantic v2, `extra="forbid"`, frozen models where possible.
- Coordinates in metres on a 105×68 pitch (see `events/schema.py`).
- Bump `SCHEMA_VERSION` on any event schema change.
