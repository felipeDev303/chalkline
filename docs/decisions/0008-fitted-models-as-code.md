# 0008 — Fitted models ship as generated code, evaluated against the simulator's truth

Context: "why it matters" needs probabilities (expected goals, win probability), and
the brief asks for a pass difficulty rating. A model endpoint (Azure ML, a serving
container) would add cost, latency, a failure mode and a non-deterministic hop to a
pipeline whose numbers must be reproducible and grounded.

Decision:
- xG and xPass are logistic regressions fitted by IRLS in numpy
  (`scripts/fit_models.py`) on dev seeds 0-99 and written as a generated module,
  `metrics/_models.py`, like the xT grid. Applying them is a dot product: microseconds,
  deterministic, inside the same image on Container Apps. Metrics still never read
  files at run time.
- Logistic, not boosted trees: every number has an explanation that is itself a sum of
  facts (each feature's effect in log-odds against an average shot).
- Win probability is a closed-form Poisson model with its one prior fitted on dev seeds.
- Ground truth: the simulator already drew every shot and pass from a latent
  probability; it now also writes that probability to the truth sidecar. The event
  stream, its golden hash and every earlier evaluation are unchanged. The models are
  checked on held-out seeds against the latent probabilities, not only against noisy
  outcomes (`docs/data/CALIBRATION.md`).
- Key moments rank goals and missed big chances by win-probability impact; "chance
  quality" (a geometric 0-100 index) is retired in favour of calibrated xG.

Consequences: no extra Azure service or cost; refitting is one script plus a commit;
the models reflect the simulated league, which the README states.
