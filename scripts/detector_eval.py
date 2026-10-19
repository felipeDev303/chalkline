"""Evaluate metric detectors against planted regimes (simulator ground truth).

Shared by scripts/tune_detectors.py, which may only use DEV_SEEDS, and
scripts/calibrate.py, which reports on TEST_SEEDS (never used for tuning).

A detection counts as a hit if it has the same team and direction as a planted
change whose window is within WINDOW_TOLERANCE windows; each planted change can be
hit once.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pitchside.events.match import Match
from pitchside.metrics._timeline import WINDOW_S, view
from pitchside.metrics.control_vs_chaos import WindowStats, window_stats
from pitchside.metrics.pressure_shift import find_shifts
from pitchside.simulator import MatchTruth, simulate_match_with_truth

DEV_SEEDS = range(0, 100)
TEST_SEEDS = range(200, 400)
WINDOW_TOLERANCE = 1
WINDOWS_PER_PERIOD = 10  # 45 minutes + up to 5 of added time, in 5-minute windows


@dataclass(frozen=True)
class MatchData:
    match: Match
    truth: MatchTruth
    eligible: list[WindowStats]
    complete: list[WindowStats]


def load(seeds: range) -> list[MatchData]:
    out = []
    for seed in seeds:
        match, truth = simulate_match_with_truth(seed)
        stats = [s for s in window_stats(view(match, match.events[-1].seq)) if s.eligible]
        out.append(MatchData(match, truth, stats, [s for s in stats if s.window.complete]))
    return out


def ordinal(period: int, index: int) -> int:
    return index + (period - 1) * WINDOWS_PER_PERIOD


@dataclass(frozen=True)
class ShiftScore:
    hits: int
    detections: int  # in treated matches
    planted: int
    control_detections: int
    control_matches: int
    planted_by_cause: Counter
    hits_by_cause: Counter

    @property
    def precision(self) -> float:
        return self.hits / self.detections if self.detections else 0.0

    @property
    def recall(self) -> float:
        return self.hits / self.planted if self.planted else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def fp_per_control_match(self) -> float:
        return self.control_detections / self.control_matches if self.control_matches else 0.0


def score_shifts(data: list[MatchData], min_delta: float, min_relative: float) -> ShiftScore:
    hits = detections = planted = control_det = control_n = 0
    planted_by, hits_by = Counter(), Counter()
    for d in data:
        teams = (d.match.metadata.home.team_id, d.match.metadata.away.team_id)
        if d.truth.control_group:
            control_n += 1
            control_det += sum(len(find_shifts(d.complete, t, min_delta, min_relative))
                               for t in teams)
            continue
        for team in teams:
            found = [(ordinal(s.window.period, s.window.index),
                      "up" if s.delta_per_min > 0 else "down")
                     for s in find_shifts(d.complete, team, min_delta, min_relative)]
            truth = [(ordinal(c.period, int(c.clock_s // WINDOW_S)), c.direction, c.cause)
                     for c in d.truth.changes if c.team_id == team]
            planted += len(truth)
            planted_by.update(c for _, _, c in truth)
            detections += len(found)
            used: set[int] = set()
            for when, direction in found:
                for i, (t_when, t_dir, cause) in enumerate(truth):
                    close = abs(when - t_when) <= WINDOW_TOLERANCE
                    if i not in used and t_dir == direction and close:
                        used.add(i)
                        hits += 1
                        hits_by[cause] += 1
                        break
    return ShiftScore(hits, detections, planted, control_det, control_n, planted_by, hits_by)


@dataclass(frozen=True)
class ChaosScore:
    inside_windows: int
    inside_chaos: int
    outside_windows: int
    outside_chaos: int

    @property
    def inside_rate(self) -> float:
        return self.inside_chaos / self.inside_windows if self.inside_windows else 0.0

    @property
    def outside_rate(self) -> float:
        return self.outside_chaos / self.outside_windows if self.outside_windows else 0.0


def score_chaos(data: list[MatchData]) -> ChaosScore:
    """Chaos rate of windows whose midpoint lies inside vs outside a planted
    high-pressure spell (either team), over treated matches only."""
    counts = Counter()
    for d in data:
        if d.truth.control_group:
            continue
        for s in d.eligible:
            mid = (s.window.start_s + s.window.end_s) / 2
            inside = any(sp.period == s.window.period and sp.start_s <= mid < sp.end_s
                         for sp in d.truth.high_pressure_spans)
            key = "inside" if inside else "outside"
            counts[f"{key}_windows"] += 1
            counts[f"{key}_chaos"] += s.state == "chaos"
    return ChaosScore(counts["inside_windows"], counts["inside_chaos"],
                      counts["outside_windows"], counts["outside_chaos"])
