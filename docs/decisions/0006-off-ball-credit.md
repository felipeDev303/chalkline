# 0006 — Off-ball credit, verified against planted runs

Context: 24 rival projects share the same architecture (deterministic engine, LLM
writes, verifier, overlays). The open gap was crediting movement without the ball,
and checking those explanations against what the synthetic generator knows.

- **Schema 0.3.0.** Every event may carry a `frame` with all 22 players' positions
  (optional: a feed without tracking stays valid; tools say so in `cannot_tell`).
- **Planted runs.** Treated seeds plant free direct runs, decoys (the runner drags the
  receiver's marker away and does not receive) and tracked direct runs (the marker
  follows; no space). Labels go to `<match>.truth.json`; metrics never read them. The
  three kinds exist so that naive rules fail: "credit the recipient" misses every decoy,
  "credit whoever moved most" credits tracked runs.
- **Engine** (`metrics/off_ball.py`): counterfactual per teammate between the passer's
  reception and the pass; movement is measured relative to the team block; defenders
  who went with a runner are undone too; value = the receiver's control of the
  destination (other attackers excluded, so a decoy does not cancel); undoing the
  receiver's own run moves the pass target with them.
- **Iterations on dev seeds** (recorded so the result is not mistaken for a first try):
  team-wide control cancelled decoys; fixed-target counterfactual over-credited
  receivers; frames from the previous pass mixed in the block's shift. Each was
  diagnosed on dev seeds; test seeds 200-399 were only used for the final report.
- **Thresholds** follow the pressure-shift rule: best recall with precision >= 0.70.
  Re-tuning `pressure_shift` with the new simulator moved its delta from 1.6 to 1.8.
