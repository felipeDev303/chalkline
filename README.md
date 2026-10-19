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

    # one synthetic match: line 1 metadata, then one event per line
    uv run python -m pitchside.simulator --seed 42 --out data/match_42.jsonl

    # realism targets over seeds 0-19 + long-run margins over 200 seeds (~10 s)
    # writes docs/data/CALIBRATION.md
    uv run python scripts/calibrate.py

Same seed, same bytes, on any OS. Current calibration: [docs/data/CALIBRATION.md](docs/data/CALIBRATION.md).

## License
MIT. See NOTICE.md for attributions.
