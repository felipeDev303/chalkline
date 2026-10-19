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

## License
MIT. See NOTICE.md for attributions.
