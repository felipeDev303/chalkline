"""Off-ball attribution against planted runs (simulator truth), on given seeds.

Used by scripts/calibrate.py on TEST_SEEDS; the engine's constants were chosen on
dev seeds only. For every planted run whose pass went to its beneficiary:
- effective runs (free direct, decoy): does the engine credit the runner first?
  Compared with two naive rules: credit the recipient, credit whoever moved most.
- tracked runs: the engine should not credit them; "most moved" would.
- separation: AUC of the runner's credit, effective vs tracked.
- decisive runs (top credit >= threshold, any pass): precision against planted
  effective runs credited to their runner, and recall of those runs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pitchside.metrics import off_ball
from pitchside.simulator import simulate_match_with_truth


@dataclass
class OffBallScore:
    n: Counter = field(default_factory=Counter)
    engine: Counter = field(default_factory=Counter)
    recipient: Counter = field(default_factory=Counter)
    most_moved: Counter = field(default_factory=Counter)
    credit_effective: list[float] = field(default_factory=list)
    credit_tracked: list[float] = field(default_factory=list)
    flagged: int = 0
    flagged_true: int = 0
    planted_effective: int = 0
    matches: int = 0

    @property
    def auc(self) -> float:
        eff, trk = self.credit_effective, self.credit_tracked
        if not eff or not trk:
            return 0.0
        wins = sum((a > b) + 0.5 * (a == b) for a in eff for b in trk)
        return wins / (len(eff) * len(trk))


def kind_of(run) -> str:  # noqa: ANN001 - RunLabel
    return "decoy" if run.kind == "decoy" else ("tracked" if run.tracked else "free")


def score(seeds: range) -> OffBallScore:
    s = OffBallScore()
    threshold = off_ball.THRESHOLDS["decisive_credit"]
    for seed in seeds:
        match, truth = simulate_match_with_truth(seed)
        if truth.control_group:
            continue
        s.matches += 1
        events, meta = match.events, match.metadata
        teams = off_ball.rosters(meta)
        index = {e.seq: i for i, e in enumerate(events)}
        effective = {}
        for run in truth.runs:
            if not run.pass_to_beneficiary or run.pass_seq is None:
                continue
            i = index[run.pass_seq]
            credits = off_ball.pass_credits(events, i, meta, teams)
            if not credits:
                continue
            k = kind_of(run)
            s.n[k] += 1
            s.engine[k] += credits[0].player_id == run.player_id
            s.recipient[k] += events[i].recipient_id == run.player_id
            s.most_moved[k] += max(credits, key=lambda c: c.moved_m).player_id == run.player_id
            mine = next(c.credit for c in credits if c.player_id == run.player_id)
            (s.credit_effective if run.effective else s.credit_tracked).append(mine)
            if run.effective:
                effective[run.pass_seq] = run.player_id
        s.planted_effective += len(effective)
        for i, e in enumerate(events):
            if e.type != "pass":
                continue
            credits = off_ball.pass_credits(events, i, meta, teams)
            if credits and credits[0].credit >= threshold:
                s.flagged += 1
                s.flagged_true += effective.get(e.seq) == credits[0].player_id
    return s
