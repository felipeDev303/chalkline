"""Key moments: the ranked list of what mattered so far, each with its evidence."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field

from pitchside.events.match import Match
from pitchside.events.schema import MatchEvent
from pitchside.metrics._timeline import MatchView, match_minute, possessions, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact
from pitchside.metrics.control_vs_chaos import window_bounds, window_stats
from pitchside.metrics.expected_threat import pass_threat
from pitchside.metrics.models import odds_one_in
from pitchside.metrics.off_ball import THRESHOLDS as OFF_BALL_THRESHOLDS
from pitchside.metrics.off_ball import decisive_runs, run_facts
from pitchside.metrics.pass_profile import hardest_completed, pass_difficulty, pass_distance_m
from pitchside.metrics.pressure_shift import CANNOT_TELL_NO_SHIFT, detect_shifts, shift_facts
from pitchside.metrics.win_probability import goal_facts, miss_facts, timeline

TOOL_NAME = "key_moments"
DESCRIPTION = (
    "Ranked list of the most important moments so far (goals, big chances, swings "
    "between control and chaos, pressure shifts, long passing sequences, the hardest "
    "completed pass, the pass that added the most expected threat, decisive off-ball "
    "runs, milestones such as a player's 50th pass). Goals and big chances are ranked "
    "by how much they moved, or could have moved, the chance of winning. Each moment "
    "has its minute, an importance score and the evidence ids behind it. Use it for "
    "recaps, highlights or to decide what to talk about."
)

THRESHOLDS: dict[str, float] = {
    # Missed shots with expected goals at least this: about 2 per team per simulated
    # match (seeds 0-39), close to typical "big chance" counts.
    "big_chance_xg": 0.2,
    "sequence_passes": 10,  # possessions with at least this many passes
    "milestone_passes": 50,  # a player's n-th pass
}
# Importance scores, documented in docs/METHODS.md. Goals score 60-100 by how much
# they moved the scoring team's chance of winning (full marks at a 50-point swing);
# big chances 40-90 by leverage, xG x the swing a goal would have made (full marks at
# 0.15, about the 99th percentile of missed shots).
IMPORTANCE = {
    "goal_base": 60.0,
    "goal_span": 40.0,
    "goal_full_swing": 0.5,
    "big_chance_base": 40.0,
    "big_chance_span": 50.0,
    "big_chance_full_leverage": 0.15,
    "swing": 50.0,
    "pressure_shift": 40.0,
    "hardest_pass": 35.0,
    "threat_pass": 35.0,  # the completed pass that added the most expected threat
    "decisive_run": 55.0,  # an off-ball run that made a pass into the final third
    "decisive_runs_shown": 3,  # the strongest few, so they do not flood the list
    "milestone": 20.0,
    "sequence_cap": 90.0,  # a long sequence never outranks a goal
}


class Params(ToolParams):
    limit: Annotated[Literal[5, 10, 20], Field(description="How many moments to return.")]


@dataclass(frozen=True)
class Moment:
    kind: str
    seq: int
    importance: float
    team_id: str | None
    player_id: str | None
    facts: tuple[Fact, ...]

    @property
    def moment_id(self) -> str:
        return f"moment:{self.kind}@{self.seq}"

    @property
    def minute(self) -> Fact:
        return self.facts[0]


def _minute(mid: str, e: MatchEvent) -> Fact:
    minute, added = match_minute(e.period, e.clock_s)
    return minute_fact(f"{mid}.minute", "Minute", minute, added)


def _moment(kind: str, e: MatchEvent, importance: float, extra: list[Fact] | None = None,
            *, team_id: str | None = None, player_id: str | None = None) -> Moment:
    mid = f"moment:{kind}@{e.seq}"
    return Moment(kind, e.seq, importance, team_id, player_id,
                  (_minute(mid, e), *(extra or [])))


def all_moments(v: MatchView) -> list[Moment]:
    """Every candidate moment up to the view, unranked."""
    meta = v.metadata
    home, away = meta.home.team_id, meta.away.team_id
    out: list[Moment] = []

    goals = {home: 0, away: 0}
    imp = IMPORTANCE
    for shot in timeline(v.events, meta).shots:
        e = shot.shot
        if e.outcome == "goal":
            goals[e.team_id] += 1
            mid = f"moment:goal@{e.seq}"
            weight = min(abs(shot.swing) / imp["goal_full_swing"], 1.0)
            out.append(_moment("goal", e, imp["goal_base"] + imp["goal_span"] * weight, [
                fact(f"{mid}.scoreline", "Scoreline after the goal",
                     f"{goals[home]}-{goals[away]}", "scoreline"),
                fact(f"{mid}.xg", "Expected goals of the chance", shot.xg, "xg"),
                *goal_facts(shot, mid, meta),
            ], team_id=e.team_id, player_id=e.player_id))
        elif shot.xg >= THRESHOLDS["big_chance_xg"]:
            mid = f"moment:big_chance@{e.seq}"
            weight = min(max(shot.leverage, 0.0) / imp["big_chance_full_leverage"], 1.0)
            out.append(_moment("big_chance", e,
                               imp["big_chance_base"] + imp["big_chance_span"] * weight, [
                fact(f"{mid}.xg", "Expected goals of the chance", shot.xg, "xg"),
                fact(f"{mid}.odds_one_in", "Scored about once every this many such shots",
                     odds_one_in(shot.xg), "count"),
                fact(f"{mid}.outcome", "Outcome", e.outcome.replace("_", " "), "label"),
                *miss_facts(shot, mid, meta),
            ], team_id=e.team_id, player_id=e.player_id))

    eligible = [s for s in window_stats(v) if s.eligible and s.window.events]
    for prev, cur in pairwise(eligible):
        if {prev.state, cur.state} == {"control", "chaos"}:
            first = cur.window.events[0]
            mid = f"moment:swing@{first.seq}"
            (minute, added), _ = window_bounds(cur.window)
            out.append(Moment("swing", first.seq, IMPORTANCE["swing"], None, None, (
                minute_fact(f"{mid}.minute", "Window start", minute, added),
                fact(f"{mid}.from_state", "State before", prev.state, "label"),
                fact(f"{mid}.to_state", "State after", cur.state, "label"),
            )))

    for team_id in (home, away):
        for shift in detect_shifts(v, team_id):
            if not shift.window.events:
                continue
            first = shift.window.events[0]
            mid = f"moment:pressure_shift@{first.seq}.team:{team_id}"
            facts = shift_facts(shift, mid)
            out.append(Moment("pressure_shift", first.seq, IMPORTANCE["pressure_shift"],
                              team_id, None, tuple(facts)))

    for p in possessions(v.events):
        n = p.passes
        if n >= THRESHOLDS["sequence_passes"]:
            start = next(e for e in v.events if e.seq == p.first_seq)
            importance = min(30.0 + 2.0 * (n - THRESHOLDS["sequence_passes"]),
                             IMPORTANCE["sequence_cap"])
            out.append(_moment("sequence", start, importance,
                               [fact(f"moment:sequence@{start.seq}.passes",
                                     "Passes in the sequence", n, "count")],
                               team_id=p.team_id))

    passes = [e for e in v.events if e.type == "pass"]
    hardest = hardest_completed(meta, passes, 1)
    if hardest:
        p = hardest[0]
        out.append(_moment("hardest_pass", p, IMPORTANCE["hardest_pass"], [
            fact(f"moment:hardest_pass@{p.seq}.difficulty", "Pass difficulty",
                 pass_difficulty(meta, p), "score"),
            fact(f"moment:hardest_pass@{p.seq}.distance_m", "Pass length",
                 pass_distance_m(p), "m"),
        ], team_id=p.team_id, player_id=p.player_id))

    threats = [(p, pass_threat(meta, p)) for p in passes if p.outcome == "complete"]
    if threats:
        p, delta = max(threats, key=lambda pd: (pd[1] or 0.0, -pd[0].seq))
        already = bool(hardest) and hardest[0].seq == p.seq  # same pass, one moment
        if delta and delta > 0 and not already:
            out.append(_moment("threat_pass", p, IMPORTANCE["threat_pass"], [
                fact(f"moment:threat_pass@{p.seq}.xt_added", "Expected threat added",
                     delta, "xg"),
            ], team_id=p.team_id, player_id=p.player_id))

    runs = decisive_runs(v.events, meta, OFF_BALL_THRESHOLDS["decisive_credit"])
    runs = sorted(runs, key=lambda r: (-r.runner.credit, r.pass_event.seq))
    for r in runs[:int(IMPORTANCE["decisive_runs_shown"])]:
        p = r.pass_event
        out.append(Moment("decisive_run", p.seq, IMPORTANCE["decisive_run"], p.team_id,
                          r.runner.player_id,
                          tuple(run_facts(r, f"moment:decisive_run@{p.seq}", meta))))

    counts: dict[str, int] = {}
    for p in passes:
        if p.player_id is None:
            continue
        counts[p.player_id] = counts.get(p.player_id, 0) + 1
        if counts[p.player_id] == THRESHOLDS["milestone_passes"]:
            out.append(_moment("milestone", p, IMPORTANCE["milestone"], [
                fact(f"moment:milestone@{p.seq}.passes", "Pass number",
                     THRESHOLDS["milestone_passes"], "count"),
            ], team_id=p.team_id, player_id=p.player_id))
    return out


def ranked(moments: list[Moment]) -> list[Moment]:
    return sorted(moments, key=lambda m: (-m.importance, m.seq, m.moment_id))


def moment_ids(m: Moment) -> str:
    return " ".join(f.evidence_id for f in m.facts)


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    candidates = all_moments(v)
    top = ranked(candidates)[:params.limit]
    rows = tuple(
        (rank, m.minute.display, m.kind, round(m.importance, 1), m.team_id, m.player_id,
         moment_ids(m))
        for rank, m in enumerate(top, start=1)
    )
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(f for m in top for f in m.facts),
        table=Table(columns=("rank", "minute", "kind", "importance", "team", "player",
                             "evidence_ids"), rows=rows) if rows else None,
        sample_size=len(candidates),
        method=(
            "Goals score 60-100 by how much they moved the scoring team's chance of "
            "winning; missed big chances (xG 0.2 or more) 40-90 by their leverage, xG times "
            "the change a goal would have made. Other moments have fixed weights "
            "(decisive run 55, control/chaos swing 50, pressure shift 40, hardest pass and "
            "most threatening pass 35, long sequence 30 + 2 per pass beyond 10, milestone "
            "20). Ranked by score, then time."
        ),
        caveats=("Win-probability impact comes from a model with equal teams and no game-"
                 "state effects; weights for the other moments are editorial.",
                 "Pressure shifts catch clear increases in pressing but miss most drops; "
                 "swings use percentile-based thresholds (docs/data/CALIBRATION.md)."),
        cannot_tell=(CANNOT_TELL_NO_SHIFT,) + (() if candidates else ("No notable moment yet.",)),
    )
