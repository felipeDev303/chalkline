"""Held-out evaluation of the fitted models: xG and xPass against the simulator's truth,
win probability against final results.

The simulator draws every shot and pass outcome from a latent probability and writes
it to the truth sidecar (never the events). A model is good when its predictions
match those latent probabilities, not only the noisy 0/1 outcomes. Used by
scripts/calibrate.py on TEST_SEEDS (models are fitted on DEV_SEEDS).
"""

from __future__ import annotations

from dataclasses import dataclass

from pitchside.metrics._models import GOALS_PER_TEAM_90
from pitchside.metrics.models import xg, xpass
from pitchside.metrics.win_probability import outcome_probs, played_minutes, probs_at
from pitchside.simulator import simulate_match, simulate_match_with_truth

BINS = 10


@dataclass(frozen=True)
class ModelCheck:
    n: int
    brier: float  # model vs outcomes
    brier_truth: float  # the latent probabilities vs outcomes: the best any model can do
    brier_base: float  # the base rate vs outcomes
    mae_truth: float  # mean |model - latent probability|
    ece: float  # weighted |mean predicted - observed| over deciles of the prediction
    bins: list[tuple[float, float, float, int]]  # (predicted, latent, observed, count)


def check(rows: list[tuple[float, float, int]]) -> ModelCheck:
    """rows: (model prediction, latent probability, outcome 0/1)."""
    rows = sorted(rows)
    n = len(rows)
    base = sum(y for _, _, y in rows) / n
    bins, ece = [], 0.0
    for b in range(BINS):
        chunk = rows[b * n // BINS:(b + 1) * n // BINS]
        pred = sum(r[0] for r in chunk) / len(chunk)
        latent = sum(r[1] for r in chunk) / len(chunk)
        obs = sum(r[2] for r in chunk) / len(chunk)
        bins.append((pred, latent, obs, len(chunk)))
        ece += len(chunk) / n * abs(pred - obs)
    return ModelCheck(
        n=n,
        brier=sum((p - y) ** 2 for p, _, y in rows) / n,
        brier_truth=sum((t - y) ** 2 for _, t, y in rows) / n,
        brier_base=sum((base - y) ** 2 for _, _, y in rows) / n,
        mae_truth=sum(abs(p - t) for p, t, _ in rows) / n,
        ece=ece,
        bins=bins,
    )


@dataclass(frozen=True)
class WinCheck:
    matches: int
    n: int  # checkpoints (every 5 minutes of every match)
    brier: float  # model, three outcomes (home, draw, away), summed
    brier_score_only: float  # score and time only, every team at the league average
    brier_constant: float  # no information: the outcome frequencies
    bins: list[tuple[float, float, int]]  # home win: (predicted, observed, count)


def evaluate_wins(seeds: range) -> WinCheck:
    """Win probability at 5-minute checkpoints against the final result."""
    rows = []  # (model probs, score-only probs, outcome index)
    for seed in seeds:
        match = simulate_match(seed)
        meta = match.metadata
        side = {meta.home.team_id: 0, meta.away.team_id: 1}
        goals, xgs = [0, 0], [0.0, 0.0]
        checks = []
        nxt = 5.0
        for e in match.events:
            played = played_minutes(e.period, e.clock_s)
            while played >= nxt and nxt < 90:
                left = (90 - nxt) / 90 * GOALS_PER_TEAM_90
                checks.append((probs_at(goals, xgs, nxt), outcome_probs(goals, [left, left])))
                nxt += 5
            if e.type == "shot":
                xgs[side[e.team_id]] += xg(meta, e)
                goals[side[e.team_id]] += e.outcome == "goal"
        result = 0 if goals[0] > goals[1] else 1 if goals[0] == goals[1] else 2
        rows += [(m, s, result) for m, s in checks]

    def brier(probs, y: int) -> float:
        return sum((p - (k == y)) ** 2 for k, p in enumerate((probs.home, probs.draw, probs.away)))

    n = len(rows)
    freq = [sum(r[2] == k for r in rows) / n for k in range(3)]
    ordered = sorted(rows, key=lambda r: r[0].home)
    bins = []
    for b in range(BINS):
        chunk = ordered[b * n // BINS:(b + 1) * n // BINS]
        bins.append((sum(r[0].home for r in chunk) / len(chunk),
                     sum(r[2] == 0 for r in chunk) / len(chunk), len(chunk)))
    return WinCheck(
        matches=len(seeds), n=n,
        brier=sum(brier(m, y) for m, _, y in rows) / n,
        brier_score_only=sum(brier(s, y) for _, s, y in rows) / n,
        brier_constant=sum(sum((freq[k] - (k == y)) ** 2 for k in range(3))
                           for _, _, y in rows) / n,
        bins=bins,
    )


def evaluate(seeds: range) -> tuple[ModelCheck, ModelCheck]:
    shots, passes = [], []
    for seed in seeds:
        match, truth = simulate_match_with_truth(seed)
        meta = match.metadata
        by_seq = {e.seq: e for e in match.events}
        for t in truth.shots:
            s = by_seq[t.seq]
            shots.append((xg(meta, s), t.p, int(s.outcome == "goal")))
        for t in truth.passes:
            p = by_seq[t.seq]
            passes.append((xpass(meta, p), t.p, int(p.outcome == "complete")))
    return check(shots), check(passes)
