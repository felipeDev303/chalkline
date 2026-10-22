"""Calibration of the expected threat grid on held-out seeds.

For every pass or shot, the prediction is xT of the zone it starts from and the
outcome is whether that possession ends in a goal for the team on the ball. Used
by scripts/calibrate.py on TEST_SEEDS (the grid is fitted on DEV_SEEDS).
"""

from __future__ import annotations

from dataclasses import dataclass

from pitchside.events.match import Match
from pitchside.metrics._timeline import attack_frame, possessions
from pitchside.metrics.expected_threat import xt_at

DECILES = 10


@dataclass(frozen=True)
class Calibration:
    n: int
    base_rate: float
    brier: float
    brier_base: float
    ece: float
    bins: list[tuple[float, float, int]]  # (mean predicted, observed rate, count)

    @property
    def brier_skill(self) -> float:
        return 1 - self.brier / self.brier_base if self.brier_base else 0.0


def samples(match: Match) -> list[tuple[float, int]]:
    meta = match.metadata
    goal_possessions = set()
    for p in possessions(match.events):
        if any(e.type == "shot" and e.outcome == "goal" and e.team_id == p.team_id
               and p.first_seq <= e.seq <= p.last_seq for e in match.events):
            goal_possessions.add((p.first_seq, p.last_seq))
    owner = {}
    for p in possessions(match.events):
        for seq in range(p.first_seq, p.last_seq + 1):
            owner[seq] = (p.team_id, (p.first_seq, p.last_seq) in goal_possessions)
    out = []
    for e in match.events:
        if e.type in ("pass", "shot") and e.seq in owner and owner[e.seq][0] == e.team_id:
            out.append((xt_at(attack_frame(meta, e.team_id, e.period, e.location)),
                        int(owner[e.seq][1])))
    return out


def calibrate(matches: list[Match]) -> Calibration:
    data = sorted(s for m in matches for s in samples(m))
    n = len(data)
    base = sum(y for _, y in data) / n
    brier = sum((p - y) ** 2 for p, y in data) / n
    brier_base = sum((base - y) ** 2 for _, y in data) / n
    bins, ece = [], 0.0
    for b in range(DECILES):
        chunk = data[b * n // DECILES:(b + 1) * n // DECILES]
        pred = sum(p for p, _ in chunk) / len(chunk)
        obs = sum(y for _, y in chunk) / len(chunk)
        bins.append((pred, obs, len(chunk)))
        ece += len(chunk) / n * abs(pred - obs)
    return Calibration(n, base, brier, brier_base, ece, bins)
