"""Realism targets for synthetic matches and the per-match counts checked against them.

Shared by tests/test_simulator.py and scripts/calibrate.py. These are plain counts
for calibration, not match metrics (those live in `pitchside.metrics`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import fmean

from pitchside.events.schema import MatchEvent

CALIBRATION_SEEDS = range(20)

# A 20-seed mean is noisy (goals especially), so robustness is judged on the
# long-run mean over many seeds: it must sit at least MIN_MARGIN_SE standard
# errors of a 20-seed mean (std / sqrt(20)) inside the nearest bound. Then any
# 20 seeds, not just CALIBRATION_SEEDS, very likely meet the targets.
ROBUSTNESS_SEEDS = range(200)
MIN_MARGIN_SE = 2.0

# Averaged over CALIBRATION_SEEDS; inclusive bounds.
TARGETS: dict[str, tuple[float, float]] = {
    "passes": (900, 1100),
    "pass_completion": (0.80, 0.88),
    "shots": (20, 30),
    "goals": (2, 4),
}


def summarize(events: Sequence[MatchEvent]) -> dict[str, float]:
    passes = [e for e in events if e.type == "pass"]
    shots = [e for e in events if e.type == "shot"]
    complete = sum(1 for e in passes if e.outcome == "complete")
    return {
        "passes": len(passes),
        "pass_completion": complete / len(passes),
        "mean_pass_length_m": fmean(
            math.dist((e.location.x, e.location.y), (e.end_location.x, e.end_location.y))
            for e in passes
        ),
        "shots": len(shots),
        "goals": sum(1 for e in shots if e.outcome == "goal"),
        "shots_on_target": sum(1 for e in shots if e.outcome in ("goal", "saved")),
        "tackles": sum(1 for e in events if e.type == "tackle"),
        "pressures": sum(1 for e in events if e.type == "pressure"),
        "possession_changes": sum(1 for e in events if e.type == "possession_change"),
        "events": len(events),
    }
