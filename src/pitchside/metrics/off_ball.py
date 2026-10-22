"""Off-ball credit: which teammate's movement made a pass possible.

For a pass, compare two frames: when the passer received the ball, and when they
passed it. Whatever teammates did in between is off-ball movement. For each one,
build a counterfactual: put them back where they were (and any defender who went
with them), recompute how much the attacking team controls the pass destination,
and credit them with the difference.

Receiver's control (after Fernandez & Bornn, 2018, simplified): every player
projects a Gaussian influence of width SIGMA_M; the receiver's control of the pass
destination is a logistic of their influence minus all defenders'. Other attackers
do not count: a teammate standing nearby does not make the receiver freer, and
counting them would cancel a decoy (runner and marker leaving together). Frames
are event-level (no velocities), so influence is isotropic. It is an index in
[0, 1], not a probability.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from pitchside.events.match import Match
from pitchside.events.schema import Frame, MatchEvent, MatchMetadata, Pass
from pitchside.metrics._timeline import XY, attack_frame, in_final_third, match_minute, view
from pitchside.metrics.contract import (
    Fact,
    Table,
    ToolParams,
    ToolResult,
    fact,
    minute_fact,
)

TOOL_NAME = "off_ball_credit"
DESCRIPTION = (
    "Credits the off-ball runs that made passes into the final third possible: who ran, "
    "who received, and how much the receiver's control of the destination rose because "
    "of the run (with versus without it). Covers direct runs into space and decoy runs "
    "that drag a defender away from a teammate. Use it to explain a chance that started "
    "without the ball, or to praise a player whose work does not show in the stats."
)

SIGMA_M = 6.0  # width of a player's influence (chosen on dev seeds, see METHODS.md)
BETA = 3.0  # steepness of the control logistic
FOLLOW_RADIUS_M = 3.0  # a defender this close to a mover after the move...
FOLLOW_MIN_MOVE_M = 3.0  # ...who also moved this much, went with them
MIN_RUN_M = 4.0  # a teammate who moved less made no run: no credit
THRESHOLDS: dict[str, float] = {
    "decisive_credit": 0.3,  # receiver-control points a run must add to be decisive
    "min_run_m": MIN_RUN_M,
    "shown": 5,  # decisive runs listed with scope 'all', strongest first
}


@dataclass(frozen=True)
class Credit:
    player_id: str
    credit: float  # control at the destination with the movement minus without
    control_with: float
    control_without: float
    moved_m: float
    now_xy: XY = (0.0, 0.0)  # where the player was at the pass
    without_xy: XY = (0.0, 0.0)  # where they would have been without their run


def positions(frame: Frame) -> dict[str, XY]:
    return {p.player_id: (p.x, p.y) for p in frame.players}


def rosters(metadata: MatchMetadata) -> dict[str, str]:
    """player_id -> team_id."""
    return {p.player_id: t.team_id for t in (metadata.home, metadata.away) for p in t.players}


def influence(xy: XY, point: XY) -> float:
    d2 = (xy[0] - point[0]) ** 2 + (xy[1] - point[1]) ** 2
    return math.exp(-d2 / (2 * SIGMA_M ** 2))


def control(point: XY, receiver: XY, defenders: Sequence[XY]) -> float:
    """The receiver's control of `point` against every defender, in [0, 1]."""
    total = influence(receiver, point) - sum(influence(d, point) for d in defenders)
    return 1.0 / (1.0 + math.exp(-BETA * total))


def intended_receiver(p: Pass, now: dict[str, XY], attackers: set[str]) -> str | None:
    """The recipient of a completed pass; otherwise the teammate nearest its end."""
    if p.recipient_id is not None:
        return p.recipient_id
    end = (p.end_location.x, p.end_location.y)
    mates = sorted(attackers - {p.player_id}, key=lambda pid: (math.dist(now[pid], end), pid))
    return mates[0] if mates else None


def reception_event(events: Sequence[MatchEvent], index: int) -> MatchEvent | None:
    """The event at which the passer of events[index] got the ball, if in view."""
    passer = events[index].player_id
    for e in reversed(events[:index]):
        if e.period != events[index].period:
            return None
        if e.type == "pass" and e.outcome == "complete" and e.recipient_id == passer:
            return e
        if e.type == "possession_change":
            return e if e.player_id == passer else None
    return None


def pass_credits(events: Sequence[MatchEvent], index: int, metadata: MatchMetadata,
                 teams: dict[str, str] | None = None) -> list[Credit]:
    """Credit of every teammate's off-ball movement for the pass at events[index].

    Empty when the pass has no frames, or the reception is not in view. Pass
    `teams` (from `rosters`) when scoring many passes.
    """
    p = events[index]
    if p.type != "pass" or p.frame is None:
        return []
    before_event = reception_event(events, index)
    if before_event is None or before_event.frame is None:
        return []
    teams = teams if teams is not None else rosters(metadata)
    now, before = positions(p.frame), positions(before_event.frame)
    attackers = {pid for pid in now if teams.get(pid) == p.team_id}
    receiver = intended_receiver(p, now, attackers)
    if receiver is None:
        return []
    end = (p.end_location.x, p.end_location.y)

    def receiver_control(pos: dict[str, XY], target: XY) -> float:
        return control(target, pos[receiver], [xy for pid, xy in pos.items()
                                               if pid not in attackers])

    own = relative_moves(now, before, attackers - {p.player_id})
    other = relative_moves(now, before, set(now) - attackers)
    base = receiver_control(now, end)
    out = []
    for pid in sorted(own):
        move = own[pid]
        moved = math.hypot(*move)
        without_xy = (now[pid][0] - move[0], now[pid][1] - move[1])
        if moved < MIN_RUN_M:
            out.append(Credit(pid, 0.0, base, base, moved, now[pid], without_xy))
            continue
        # Without the run: moved with the block, not on their own; so did any
        # defender who went with them.
        counterfactual = dict(now)
        counterfactual[pid] = without_xy
        for did, dmove in other.items():
            if (math.dist(now[did], now[pid]) <= FOLLOW_RADIUS_M
                    and math.hypot(*dmove) >= FOLLOW_MIN_MOVE_M):
                counterfactual[did] = (now[did][0] - dmove[0], now[did][1] - dmove[1])
        # Had the receiver not moved, the pass would have gone to where they were.
        target = (end[0] - move[0], end[1] - move[1]) if pid == receiver else end
        without = receiver_control(counterfactual, target)
        out.append(Credit(pid, base - without, base, without, moved, now[pid], without_xy))
    return sorted(out, key=lambda c: (-c.credit, c.player_id))


def relative_moves(now: dict[str, XY], before: dict[str, XY],
                   players: set[str]) -> dict[str, XY]:
    """Each player's displacement minus their group's median displacement.

    The block shifts with the ball; a run is moving differently from the block.
    """
    common = sorted(pid for pid in players if pid in before)
    if not common:
        return {}
    dx = sorted(now[pid][0] - before[pid][0] for pid in common)
    dy = sorted(now[pid][1] - before[pid][1] for pid in common)
    mx, my = dx[len(dx) // 2], dy[len(dy) // 2]
    return {pid: (now[pid][0] - before[pid][0] - mx, now[pid][1] - before[pid][1] - my)
            for pid in common}


@dataclass(frozen=True)
class DecisiveRun:
    pass_event: Pass
    runner: Credit
    recipient_id: str


def decisive_runs(events: Sequence[MatchEvent], metadata: MatchMetadata,
                  threshold: float) -> list[DecisiveRun]:
    """Completed passes into the final third whose top off-ball credit >= threshold."""
    teams = rosters(metadata)
    out = []
    for i, e in enumerate(events):
        if e.type != "pass" or e.outcome != "complete" or e.frame is None:
            continue
        end = attack_frame(metadata, e.team_id, e.period, e.end_location)
        if not in_final_third(end):
            continue
        credits = pass_credits(events, i, metadata, teams)
        if credits and credits[0].credit >= threshold:
            out.append(DecisiveRun(e, credits[0], e.recipient_id or ""))
    return out


# --- the tool ------------------------------------------------------------------

class Params(ToolParams):
    scope: Annotated[Literal["latest", "all"], Field(description=(
        "'latest': the most recent decisive run; 'all': the strongest decisive runs so "
        "far and a count per team."))]


def run_facts(run: DecisiveRun, prefix: str, metadata: MatchMetadata) -> list[Fact]:
    """Facts to quote one decisive run (also used by key_moments)."""
    names = {pl.player_id: pl for t in (metadata.home, metadata.away) for pl in t.players}
    runner, recipient = names[run.runner.player_id], names.get(run.recipient_id)
    p = run.pass_event
    minute, added = match_minute(p.period, p.clock_s)
    facts = [
        minute_fact(f"{prefix}.minute", "Minute of the pass the run made", minute, added),
        fact(f"{prefix}.runner", "Runner", runner.name, "label"),
        fact(f"{prefix}.runner_shirt", "Runner's shirt number", runner.shirt_number, "count"),
        fact(f"{prefix}.control_with", "Receiver's control of the destination with the run",
             100 * run.runner.control_with, "share"),
        fact(f"{prefix}.control_without", "Receiver's control without the run",
             100 * run.runner.control_without, "share"),
        fact(f"{prefix}.kind", "Kind of run",
             "own run" if run.runner.player_id == run.recipient_id else "decoy run", "label"),
    ]
    if recipient is not None:
        facts.append(fact(f"{prefix}.recipient", "Receiver", recipient.name, "label"))
    return facts


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    if not any(e.frame is not None for e in v.events):
        return ToolResult(
            tool_name=TOOL_NAME, params=params.model_dump(), as_of_seq=v.as_of_seq, facts=(),
            sample_size=0, method="Needs player positions in the feed.",
            cannot_tell=("This feed has no player positions, so off-ball movement cannot "
                         "be credited.",))
    runs = decisive_runs(v.events, v.metadata, THRESHOLDS["decisive_credit"])
    facts: list[Fact] = []
    for team in v.teams:
        facts.append(fact(f"offball.team:{team.team_id}.decisive_runs",
                          "Decisive off-ball runs", sum(r.pass_event.team_id == team.team_id
                                                        for r in runs), "count"))
    if params.scope == "latest":
        shown = runs[-1:]
    else:
        shown = sorted(runs, key=lambda r: (-r.runner.credit, r.pass_event.seq))
        shown = shown[:int(THRESHOLDS["shown"])]
    for r in shown:
        facts += run_facts(r, f"offball.run@{r.pass_event.seq}", v.metadata)
    rows = tuple((r.pass_event.seq, r.runner.player_id, r.recipient_id,
                  round(100 * r.runner.control_with), round(100 * r.runner.control_without))
                 for r in shown)
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("seq", "runner", "recipient", "control_with", "control_without"),
                    rows=rows) if rows else None,
        sample_size=len(runs),
        method=(
            "For each completed pass into the final third, every teammate's movement since "
            "the passer got the ball (relative to their team's shift) is undone in turn, "
            "with any defender who went with them, and the receiver's control of the pass "
            "destination is recomputed. The run whose absence costs the most control is "
            "credited; it is decisive if it added at least "
            f"{100 * THRESHOLDS['decisive_credit']:.0f} control points."
        ),
        caveats=("Control is a geometric index from positions at each event, not a "
                 "probability; positions are event-level, without velocities.",
                 "Checked against planted runs in simulated matches "
                 "(docs/data/CALIBRATION.md)."),
        cannot_tell=("Runs that no pass used.", "Whether the runner meant it as a decoy."),
    )
