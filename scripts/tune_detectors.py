"""Grid-search pressure_shift thresholds on the DEV seeds only (0-99).

Usage: uv run python scripts/tune_detectors.py
Prints precision / recall / F1 / false positives per control match for each grid
point. Copy the chosen values into metrics/pressure_shift.py THRESHOLDS and
docs/METHODS.md; scripts/calibrate.py then reports them on the untouched TEST seeds.
"""

from __future__ import annotations

from collections import Counter

from detector_eval import DEV_SEEDS, TEST_SEEDS, load, score_shifts

from pitchside.metrics.control_vs_chaos import STATES

DELTAS = (0.6, 0.8, 1.0, 1.2, 1.4, 1.6)
RELATIVES = (0.25, 0.5, 0.75, 1.0)


def main() -> None:
    assert not set(DEV_SEEDS) & set(TEST_SEEDS), "tuning must never see test seeds"
    data = load(DEV_SEEDS)
    rows = []
    for delta in DELTAS:
        for rel in RELATIVES:
            s = score_shifts(data, delta, rel)
            rows.append((s.f1, delta, rel, s))
    print("delta  rel   precision recall  f1     fp/control")
    for f1, delta, rel, s in sorted(rows, key=lambda r: -r[0]):
        print(f"{delta:4.1f}  {rel:4.2f}  {s.precision:8.3f} {s.recall:6.3f}  {f1:5.3f}  "
              f"{s.fp_per_control_match:6.2f}")
    states = Counter(w.state for d in data for w in d.eligible)
    total = sum(states.values())
    print("control_vs_chaos split on dev seeds:",
          {k: round(states[k] / total, 3) for k in STATES})


if __name__ == "__main__":
    main()
