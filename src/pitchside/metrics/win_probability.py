"""Win probability: how likely each result is from here, and how much each shot moved it.

Goals still to come are Poisson for each team (independent). A team's rate for the
time left shrinks from the league's average towards its own xG rate in this match as
the match goes on:

    lambda = (t_left / 90) * ((1 - a) * prior + a * xg_so_far / t_played * 90),  a = t_played / 90

so early on every team is average, late on its own chances count most. A goal moves
the probabilities through the score; every shot also moves them a little through the
xG rate. Each shot's impact compares the probabilities just before it with the ones
had it gone in: a missed chance's leverage is its xG times that difference.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from pitchside.events.match import Match
from pitchside.events.schema import MatchEvent, MatchMetadata, Shot
from pitchside.metrics._models import GOALS_PER_TEAM_90
from pitchside.metrics._timeline import match_minute, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact
from pitchside.metrics.models import xg

TOOL_NAME = "win_probability"
DESCRIPTION = (
    "Chance of a home win, a draw and an away win right now, and how much each goal "
    "moved them (each team's chance of winning before and after). Also the missed "
    "chance that would have changed the most. Use it to say why a goal or a miss "
    "mattered, not only that it happened."
)

THRESHOLDS: dict[str, float] = {
    "max_goals": 10,  # Poisson sums truncated at this many further goals per team
    "every_min": 5,  # checkpoints in the table
    "goals_shown": 6,  # the most recent goals, with their before and after
}
MATCH_MINUTES = 90.0


class Params(ToolParams):
    scope: Annotated[Literal["now", "goals"], Field(description=(
        "'now': the current probabilities and the highest-leverage missed chance; "
        "'goals': also each goal's before and after."))]


@dataclass(frozen=True)
class Probs:
    home: float
    draw: float
    away: float

    def win(self, side: int) -> float:
        """Win probability of side 0 (home) or 1 (away)."""
        return self.home if side == 0 else self.away


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def outcome_probs(goals: Sequence[int], lams: Sequence[float]) -> Probs:
    """Final-result probabilities given the score now and each side's goals still to come."""
    n = int(THRESHOLDS["max_goals"])
    ph = [poisson(k, lams[0]) for k in range(n)]
    pa = [poisson(k, lams[1]) for k in range(n)]
    home = draw = 0.0
    for i in range(n):
        for j in range(n):
            diff = (goals[0] + i) - (goals[1] + j)
            if diff > 0:
                home += ph[i] * pa[j]
            elif diff == 0:
                draw += ph[i] * pa[j]
    total = sum(ph) * sum(pa)  # renormalise the truncated tails
    return Probs(home / total, draw / total, 1 - (home + draw) / total)


def played_minutes(period: int, clock_s: float) -> float:
    """Minutes of the 90 played; added time counts as no time left."""
    return min(clock_s / 60, 45.0) + (45.0 if period == 2 else 0.0)


def remaining_rate(xg_so_far: float, played: float) -> float:
    left = max(MATCH_MINUTES - played, 0.0)
    if left == 0.0:
        return 0.0
    alpha = played / MATCH_MINUTES
    own = xg_so_far / played * MATCH_MINUTES if played > 0 else GOALS_PER_TEAM_90
    return left / MATCH_MINUTES * ((1 - alpha) * GOALS_PER_TEAM_90 + alpha * own)


def probs_at(goals: Sequence[int], xgs: Sequence[float], played: float) -> Probs:
    return outcome_probs(goals, [remaining_rate(xgs[s], played) for s in (0, 1)])


@dataclass(frozen=True)
class ShotImpact:
    shot: Shot
    side: int  # 0 home, 1 away
    xg: float
    before: Probs  # just before the shot
    if_scored: Probs  # had it gone in

    @property
    def win_before(self) -> float:
        return self.before.win(self.side)

    @property
    def win_if_scored(self) -> float:
        return self.if_scored.win(self.side)

    @property
    def swing(self) -> float:
        """Change in the shooting team's win probability a goal makes."""
        return self.win_if_scored - self.win_before

    @property
    def leverage(self) -> float:
        """Expected change from the shot: its xG times the swing a goal makes."""
        return self.xg * self.swing


@dataclass(frozen=True)
class Timeline:
    shots: tuple[ShotImpact, ...]
    checkpoints: tuple[tuple[int, Probs], ...]  # (minute, probabilities)
    now: Probs
    goals: tuple[int, int]
    xgs: tuple[float, float]


def timeline(events: Sequence[MatchEvent], metadata: MatchMetadata) -> Timeline:
    """Walk the events once: every shot's impact, checkpoints, and the state now."""
    side = {metadata.home.team_id: 0, metadata.away.team_id: 1}
    goals, xgs = [0, 0], [0.0, 0.0]
    shots, checkpoints = [], []
    every = THRESHOLDS["every_min"]
    next_check = every
    played = 0.0
    for e in events:
        played = played_minutes(e.period, e.clock_s)
        while played >= next_check and next_check <= MATCH_MINUTES:
            checkpoints.append((int(next_check), probs_at(goals, xgs, next_check)))
            next_check += every
        if e.type != "shot":
            continue
        s, shot_xg = side[e.team_id], xg(metadata, e)
        before = probs_at(goals, xgs, played)
        xgs[s] += shot_xg
        scored = list(goals)
        scored[s] += 1
        shots.append(ShotImpact(e, s, shot_xg, before, probs_at(scored, xgs, played)))
        if e.outcome == "goal":
            goals[s] += 1
    final = bool(events) and events[-1].type == "phase" and events[-1].phase == "full_time"
    now = probs_at(goals, xgs, MATCH_MINUTES if final else played)
    return Timeline(tuple(shots), tuple(checkpoints), now, (goals[0], goals[1]),
                    (xgs[0], xgs[1]))


def goal_facts(impact: ShotImpact, prefix: str, metadata: MatchMetadata) -> list[Fact]:
    """A goal's before and after, for the scoring team (also used by key_moments)."""
    team = (metadata.home, metadata.away)[impact.side].name
    return [
        fact(f"{prefix}.win_before", f"{team} chance of winning before the goal",
             100 * impact.win_before, "share"),
        fact(f"{prefix}.win_after", f"{team} chance of winning after the goal",
             100 * impact.win_if_scored, "share"),
    ]


def miss_facts(impact: ShotImpact, prefix: str, metadata: MatchMetadata) -> list[Fact]:
    """A missed chance's stakes, for the shooting team (also used by key_moments)."""
    team = (metadata.home, metadata.away)[impact.side].name
    return [
        fact(f"{prefix}.win_now", f"{team} chance of winning at the time",
             100 * impact.win_before, "share"),
        fact(f"{prefix}.win_if_scored", f"{team} chance of winning had it gone in",
             100 * impact.win_if_scored, "share"),
    ]


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    meta = v.metadata
    t = timeline(v.events, meta)
    last = v.events[-1]
    minute, added = match_minute(last.period, last.clock_s)
    facts: list[Fact] = [
        minute_fact("wp.minute", "Minute", minute, added),
        fact(f"wp.team:{meta.home.team_id}.win", f"{meta.home.name} chance of winning",
             100 * t.now.home, "share"),
        fact("wp.draw", "Chance of a draw", 100 * t.now.draw, "share"),
        fact(f"wp.team:{meta.away.team_id}.win", f"{meta.away.name} chance of winning",
             100 * t.now.away, "share"),
    ]
    goals = [s for s in t.shots if s.shot.outcome == "goal"]
    if params.scope == "goals":
        for g in goals[-int(THRESHOLDS["goals_shown"]):]:
            gm, ga = match_minute(g.shot.period, g.shot.clock_s)
            prefix = f"wp.goal@{g.shot.seq}"
            facts += [minute_fact(f"{prefix}.minute", "Minute of the goal", gm, ga),
                      fact(f"{prefix}.team", "Scoring team",
                           (meta.home, meta.away)[g.side].name, "label"),
                      *goal_facts(g, prefix, meta)]
    misses = [s for s in t.shots if s.shot.outcome != "goal"]
    if misses:
        m = max(misses, key=lambda s: (s.leverage, -s.shot.seq))
        mm, ma = match_minute(m.shot.period, m.shot.clock_s)
        prefix = f"wp.miss@{m.shot.seq}"
        names = {p.player_id: p.name for t_ in (meta.home, meta.away) for p in t_.players}
        facts += [minute_fact(f"{prefix}.minute", "Minute of the costliest miss", mm, ma),
                  fact(f"{prefix}.shooter", "Shooter", names[m.shot.player_id or ""], "label"),
                  fact(f"{prefix}.xg", "Expected goals of the chance", m.xg, "xg"),
                  *miss_facts(m, prefix, meta)]
    rows = tuple((m_, round(100 * p.home), round(100 * p.draw), round(100 * p.away))
                 for m_, p in t.checkpoints[-20:])
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("minute", "home_win", "draw", "away_win"), rows=rows)
        if rows else None,
        sample_size=len(t.shots),
        method=(
            "Goals still to come are Poisson for each team. A team's rate for the time "
            "left moves from the league average towards its own expected-goals rate as "
            "the match goes on. A goal changes the probabilities through the score; a "
            "missed chance's stakes are the difference a goal would have made."
        ),
        caveats=(
            "Teams are equal before kickoff and do not change how they play with the "
            "score; there are no red cards. Added time counts as no time left.",
            "Calibrated against final results on held-out simulated matches "
            "(docs/data/CALIBRATION.md).",
        ),
        cannot_tell=("Who will win: these are probabilities, not a prediction.",),
    )
