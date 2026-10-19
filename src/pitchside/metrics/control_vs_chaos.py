"""Control vs chaos: how settled each 5-minute window of play is, plus game rhythm."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from statistics import fmean
from typing import Annotated, Literal

from pydantic import Field

from pitchside.events.match import Match
from pitchside.metrics._timeline import (
    PERIOD_MINUTES,
    WINDOW_S,
    MatchView,
    Window,
    is_restart,
    possessions,
    possessor_after,
    view,
    windows,
)
from pitchside.metrics.contract import (
    Fact,
    Table,
    ToolParams,
    ToolResult,
    fact,
    minute_fact,
)

TOOL_NAME = "control_vs_chaos"
DESCRIPTION = (
    "Classifies each 5-minute window of the match so far as 'control' (one team keeps "
    "the ball calmly), 'contested' or 'chaos' (frequent turnovers, scrappy passing), "
    "with the window's possession split, turnovers/min, pressures/min and pass "
    "completion; also the overall rhythm (events per minute, passes per possession). "
    "Use it to describe the flow of the game or to explain a change of momentum."
)

# Chosen from eligible windows over simulated seeds 0-199 so that about a quarter
# are control and a quarter chaos (25% / 51% / 24%); see docs/METHODS.md.
THRESHOLDS: dict[str, float] = {
    "min_window_s": 120.0,  # windows with less observed play are not classified
    "min_window_passes": 5,  # completion is only shown with this many passes
    "control_share_pct": 56.0,  # dominant team's possession share, at least
    "control_turnovers_per_min": 1.2,  # and open-play turnovers/min, at most
    "chaos_turnovers_per_min": 2.0,  # chaos: turnovers/min at least, or
    "chaos_completion_pct": 70.0,  # pass completion below this
}
OPEN_PLAY_TURNOVERS = frozenset({"interception", "tackle"})
STATES = ("control", "contested", "chaos")
CAVEAT_THRESHOLDS = (
    "Thresholds are percentile-based and not tuned against ground truth; in simulated "
    "matches, windows inside planted high-pressure spells are classified chaos more often "
    "(docs/data/CALIBRATION.md)."
)


Scope = Literal["latest", "all"]
SCOPE_DESCRIPTION = (
    "'latest': only the most recent complete window plus the current partial one (if it "
    "can be classified); 'all': every classified window so far."
)


class Params(ToolParams):
    scope: Annotated[Scope, Field(description=SCOPE_DESCRIPTION)]


def latest_or_all(eligible: list[WindowStats], scope: Scope) -> list[WindowStats]:
    if scope == "all":
        return eligible
    complete = [s for s in eligible if s.window.complete]
    chosen = complete[-1:]
    if eligible and not eligible[-1].window.complete:
        chosen.append(eligible[-1])
    return chosen


@dataclass(frozen=True)
class WindowStats:
    window: Window
    possession_s: dict[str, float]
    turnovers: int
    pressures: dict[str, int]
    passes: int
    completed: int

    @property
    def minutes(self) -> float:
        return self.window.observed_s / 60

    @property
    def eligible(self) -> bool:
        """Enough observed play to classify, and something happened in it."""
        return bool(self.window.events) and self.window.observed_s >= THRESHOLDS["min_window_s"]

    def share(self, team_id: str) -> float | None:
        total = sum(self.possession_s.values())
        return 100 * self.possession_s[team_id] / total if total > 0 else None

    @property
    def dominant(self) -> tuple[str, float] | None:
        shares = [(t, self.share(t)) for t in self.possession_s]
        if shares[0][1] is None:
            return None
        return max(shares, key=lambda ts: (ts[1], ts[0]))  # type: ignore[return-value]

    @property
    def turnovers_per_min(self) -> float:
        return self.turnovers / self.minutes

    def pressures_per_min(self, team_id: str) -> float:
        return self.pressures[team_id] / self.minutes

    @property
    def completion_pct(self) -> float | None:
        if self.passes < THRESHOLDS["min_window_passes"]:
            return None
        return 100 * self.completed / self.passes

    @property
    def state(self) -> str:
        completion = self.completion_pct
        if self.turnovers_per_min >= THRESHOLDS["chaos_turnovers_per_min"] or (
            completion is not None and completion < THRESHOLDS["chaos_completion_pct"]
        ):
            return "chaos"
        dominant = self.dominant
        if (
            dominant is not None
            and dominant[1] >= THRESHOLDS["control_share_pct"]
            and self.turnovers_per_min <= THRESHOLDS["control_turnovers_per_min"]
        ):
            return "control"
        return "contested"


def window_stats(v: MatchView) -> tuple[WindowStats, ...]:
    """Per-window counts; possession uses the same in-play rule as the match total."""
    owner = dict(zip((e.seq for e in v.events), possessor_after(v.events), strict=True))
    team_ids = [t.team_id for t in v.teams]
    out = []
    for w in windows(v):
        seconds = dict.fromkeys(team_ids, 0.0)
        for prev, cur in pairwise(w.events):
            team = owner[prev.seq]
            if team is not None and not is_restart(cur):
                seconds[team] += cur.clock_s - prev.clock_s
        passes = [e for e in w.events if e.type == "pass"]
        out.append(WindowStats(
            window=w,
            possession_s=seconds,
            turnovers=sum(1 for e in w.events if e.type == "possession_change"
                          and e.cause in OPEN_PLAY_TURNOVERS),
            pressures={t: sum(1 for e in w.events if e.type == "pressure" and e.team_id == t)
                       for t in team_ids},
            passes=len(passes),
            completed=sum(1 for e in passes if e.outcome == "complete"),
        ))
    return tuple(out)


def window_key(w: Window) -> str:
    return f"p{w.period}.w{w.index:02d}"


def window_bounds(w: Window) -> tuple[tuple[int, int], tuple[int, int]]:
    """(minute, added) marks for the window's start and end: 15'-20', 45'-45+5'."""
    base = 0 if w.period == 1 else PERIOD_MINUTES
    def mark(seconds: float) -> tuple[int, int]:
        minute = int(seconds // 60)
        if minute > PERIOD_MINUTES:
            return base + PERIOD_MINUTES, minute - PERIOD_MINUTES
        return base + minute, 0
    return mark(w.start_s), mark(w.end_s)


def window_facts(stats: WindowStats, prefix: str) -> list[Fact]:
    """Facts that let a narrative quote one window: bounds, state, rates."""
    (start_m, start_a), (end_m, end_a) = window_bounds(stats.window)
    facts = [
        minute_fact(f"{prefix}.start", "Window start", start_m, start_a),
        minute_fact(f"{prefix}.end", "Window end", end_m, end_a),
        fact(f"{prefix}.state", "Window state", stats.state, "label"),
        fact(f"{prefix}.turnovers_per_min", "Open-play turnovers per minute",
             stats.turnovers_per_min, "per_min"),
    ]
    for team_id in stats.possession_s:
        share = stats.share(team_id)
        if share is not None:
            facts.append(fact(f"{prefix}.team:{team_id}.possession_share",
                              "Possession share in window", share, "share"))
        facts.append(fact(f"{prefix}.team:{team_id}.pressures_per_min",
                          "Pressures per minute in window",
                          stats.pressures_per_min(team_id), "per_min"))
    if stats.completion_pct is not None:
        facts.append(fact(f"{prefix}.completion_pct", "Pass completion in window",
                          stats.completion_pct, "pct"))
    return facts


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    stats = window_stats(v)
    eligible = [s for s in stats if s.eligible]
    shown = latest_or_all(eligible, params.scope)
    facts: list[Fact] = []
    cannot_tell: list[str] = []
    for s in shown:
        facts += window_facts(s, f"window.{window_key(s.window)}")
    if eligible:
        current = eligible[-1]
        facts.append(fact("window.current.state", "Latest classified window state",
                          current.state, "label"))
        for state in STATES:
            share = 100 * sum(1 for s in eligible if s.state == state) / len(eligible)
            facts.append(fact(f"window.all.{state}_share", f"Share of windows in {state}",
                              share, "share"))
    else:
        cannot_tell.append(
            f"No window has {THRESHOLDS['min_window_s']:g} s of play yet; nothing classified."
        )

    played_min = sum(s.minutes for s in stats)
    poss = possessions(v.events)
    if played_min >= THRESHOLDS["min_window_s"] / 60:
        facts.append(fact("rhythm.events_per_min", "Events per minute",
                          len(v.events) / played_min, "per_min"))
    if poss:
        facts.append(fact("rhythm.mean_possession_passes", "Passes per possession",
                          fmean(p.passes for p in poss), "decimal"))

    rows = []
    for s in shown[-20:]:
        (start_m, start_a), (end_m, end_a) = window_bounds(s.window)
        completion = s.completion_pct
        rows.append((window_key(s.window), f"{start_m}+{start_a}" if start_a else start_m,
                     f"{end_m}+{end_a}" if end_a else end_m, s.state,
                     round(s.turnovers_per_min, 1),
                     None if completion is None else round(completion, 1)))
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("window", "from", "to", "state", "turnovers_per_min",
                             "completion_pct"), rows=tuple(rows)) if rows else None,
        sample_size=len(eligible),
        method=(
            f"Play is cut into {WINDOW_S / 60:g}-minute windows per half. A window is chaos "
            "if open-play turnovers (interceptions, tackles) or failed passes are frequent, "
            "control if one team holds most of the in-play possession with few turnovers, "
            "otherwise contested."
        ),
        caveats=(CAVEAT_THRESHOLDS,
                 "Rates use the window's observed play, so the current window is partial."),
        cannot_tell=tuple(cannot_tell),
    )
