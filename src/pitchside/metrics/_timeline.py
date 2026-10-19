"""Derivations every metric tool builds on, defined once.

Consumes only `pitchside.events`. Definitions are documented in docs/METHODS.md
("Shared definitions"); keep the two in step.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from pitchside.events.match import Match, attacks_high_x
from pitchside.events.schema import (
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    MatchEvent,
    MatchMetadata,
    Player,
    Point,
    Team,
)
from pitchside.metrics.contract import ToolError

BOX_DEPTH_M = 16.5
BOX_HALF_WIDTH_M = 20.16
FINAL_THIRD_X = PITCH_LENGTH_M * 2 / 3
PERIOD_MINUTES = 45
WINDOW_S = 300.0
# A possession change with one of these causes restarts play after dead time.
RESTART_CAUSES = frozenset({"out_of_play", "foul", "other", "shot_end"})

XY = tuple[float, float]


# --- the visible part of a match ----------------------------------------------

@dataclass(frozen=True)
class MatchView:
    """Metadata plus the events a tool may see: everything up to `as_of_seq`."""

    metadata: MatchMetadata
    events: tuple[MatchEvent, ...]

    @property
    def as_of_seq(self) -> int:
        return self.events[-1].seq

    @property
    def teams(self) -> tuple[Team, Team]:
        return (self.metadata.home, self.metadata.away)

    def team(self, team_id: str) -> Team:
        for team in self.teams:
            if team.team_id == team_id:
                return team
        known = ", ".join(t.team_id for t in self.teams)
        raise ToolError("unknown_team", f"no team {team_id!r}; known: {known}")

    def opponent(self, team_id: str) -> Team:
        self.team(team_id)
        return next(t for t in self.teams if t.team_id != team_id)

    def player(self, player_id: str) -> tuple[Team, Player]:
        for team in self.teams:
            for player in team.players:
                if player.player_id == player_id:
                    return team, player
        raise ToolError("unknown_player", f"no player {player_id!r} in this match")


Subject = Literal["team", "player"]


def by_subject(v: MatchView, subject: Subject, subject_id: str) -> Callable[[MatchEvent], bool]:
    """Predicate for events credited to a team (`team_id`) or a player (`player_id`)."""
    if subject == "team":
        v.team(subject_id)
        return lambda e: e.team_id == subject_id
    v.player(subject_id)
    return lambda e: e.player_id == subject_id


def view(match: Match, as_of_seq: int) -> MatchView:
    """Cut the match at `as_of_seq`. Tools must compute from this view only."""
    if not match.events:
        raise ToolError("as_of_out_of_range", "the match has no events yet")
    first, last = match.events[0].seq, match.events[-1].seq
    if not first <= as_of_seq <= last:
        raise ToolError("as_of_out_of_range", f"as_of_seq must be in [{first}, {last}]")
    n = bisect_right([e.seq for e in match.events], as_of_seq)
    return MatchView(metadata=match.metadata, events=match.events[:n])


# --- geometry -------------------------------------------------------------------

def attack_frame(metadata: MatchMetadata, team_id: str, period: int, p: Point) -> XY:
    """`p` seen by `team_id`, which then attacks towards x = 105 (rotated 180 if needed)."""
    if attacks_high_x(metadata, team_id, period):
        return (p.x, p.y)
    return (PITCH_LENGTH_M - p.x, PITCH_WIDTH_M - p.y)


def in_box(p: XY) -> bool:
    """Inside the opponent's penalty area (attacking frame)."""
    deep_enough = p[0] >= PITCH_LENGTH_M - BOX_DEPTH_M
    return deep_enough and abs(p[1] - PITCH_WIDTH_M / 2) <= BOX_HALF_WIDTH_M


def in_final_third(p: XY) -> bool:
    return p[0] >= FINAL_THIRD_X


# --- time -----------------------------------------------------------------------

def match_minute(period: int, clock_s: float) -> tuple[int, int]:
    """(minute, added) in football convention: 0-59 s is 1'; 2nd half starts at 46'.

    Time beyond 45 minutes of a period is added time: 45+2', 90+1'.
    """
    base = 0 if period == 1 else PERIOD_MINUTES
    minute = int(clock_s // 60) + 1
    if minute > PERIOD_MINUTES:
        return base + PERIOD_MINUTES, minute - PERIOD_MINUTES
    return base + minute, 0


# --- possession -----------------------------------------------------------------

@dataclass(frozen=True)
class Possession:
    team_id: str
    period: int
    first_seq: int
    last_seq: int
    passes: int
    start_clock_s: float
    end_clock_s: float


def is_restart(e: MatchEvent) -> bool:
    """Play resumes after dead time (kickoff, throw-in, goal kick, free kick...)."""
    return e.type == "phase" or (e.type == "possession_change" and e.cause in RESTART_CAUSES)


def possessor_after(events: Sequence[MatchEvent]) -> tuple[str | None, ...]:
    """Team in possession right after each event (None between periods)."""
    current: str | None = None
    out = []
    for e in events:
        if e.type == "phase":
            current = e.team_id if e.phase == "kickoff" else None
        elif e.type == "possession_change" or (current is None and e.type in ("pass", "shot")):
            current = e.team_id
        out.append(current)
    return tuple(out)


def possessions(events: Sequence[MatchEvent]) -> tuple[Possession, ...]:
    """Split the events into possessions.

    A kickoff starts a new possession; a possession change starts one unless the
    team already has the ball (the change that follows a kickoff after a goal);
    half time and full time close the current one. Pressures and tackles by the
    defending team stay inside the attacking team's possession.
    """
    out: list[Possession] = []
    team: str | None = None
    first = last = passes = 0
    start = end = 0.0
    period = 1

    def close() -> None:
        if team is not None:
            out.append(Possession(team, period, first, last, passes, start, end))

    for e in events:
        starts = (e.type == "phase" and e.phase == "kickoff") or (
            e.type == "possession_change" and e.team_id != team
        ) or (team is None and e.type in ("pass", "shot"))
        if e.type == "phase" and e.phase != "kickoff":
            close()
            team = None
            continue
        if starts:
            close()
            team, period, first, passes, start = e.team_id, e.period, e.seq, 0, e.clock_s
        if team is None:
            continue
        last, end = e.seq, e.clock_s
        if e.type == "pass" and e.team_id == team:
            passes += 1
    close()
    return tuple(out)


def possession_seconds(view: MatchView) -> dict[str, float]:
    """In-play seconds each team had the ball.

    The gap between two consecutive events goes to the team in possession after
    the first, unless the second is a restart (that gap is dead time) or a new
    period starts.
    """
    seconds = {t.team_id: 0.0 for t in view.teams}
    owner = possessor_after(view.events)
    for i, (prev, cur) in enumerate(pairwise(view.events)):
        team = owner[i]
        if team is None or cur.period != prev.period or is_restart(cur):
            continue
        seconds[team] += cur.clock_s - prev.clock_s
    return seconds


# --- windows --------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    """A fixed slice of one period: [start_s, end_s) on the period clock."""

    period: int
    index: int
    start_s: float
    end_s: float
    observed_s: float  # how much of the window has been played (as of the view)
    events: tuple[MatchEvent, ...]

    @property
    def complete(self) -> bool:
        return self.observed_s >= self.end_s - self.start_s


def windows(view: MatchView, length_s: float = WINDOW_S) -> tuple[Window, ...]:
    """Consecutive non-overlapping windows per period, up to the last visible event.

    A period's horizon is its last visible event (half/full time once played), so
    the current window and the added-time window are partial (`complete` False).
    """
    out: list[Window] = []
    periods = sorted({e.period for e in view.events})
    for period in periods:
        evs = [e for e in view.events if e.period == period]
        horizon = evs[-1].clock_s
        for i in range(int(horizon // length_s) + 1):
            start, end = i * length_s, (i + 1) * length_s
            inside = tuple(e for e in evs if start <= e.clock_s < end)
            out.append(Window(
                period=period,
                index=i,
                start_s=start,
                end_s=end,
                observed_s=max(0.0, min(end, horizon) - start),
                events=inside,
            ))
    return tuple(out)


# --- squads ---------------------------------------------------------------------

def formation(team: Team) -> str:
    """Outfield shape from listed positions, defenders first: '4-3-3'."""
    counts = [sum(1 for p in team.players if p.position == pos) for pos in ("DF", "MF", "FW")]
    return "-".join(str(c) for c in counts)
