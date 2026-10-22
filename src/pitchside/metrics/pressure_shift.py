"""Pressure shift: moments when a team's pressing rate jumps or drops."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from statistics import fmean
from typing import Annotated

from pydantic import Field

from pitchside.events.match import Match
from pitchside.metrics._timeline import MatchView, Window, view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact, minute_fact
from pitchside.metrics.control_vs_chaos import (
    Scope,
    WindowStats,
    window_bounds,
    window_key,
    window_length_fact,
    window_stats,
)

TOOL_NAME = "pressure_shift"
DESCRIPTION = (
    "Finds the moments when one team's pressing intensity (pressures per minute) "
    "changed sharply from one complete 5-minute window to the next: a likely tactical "
    "change. Returns each shift's window, the before and after rates and the change, "
    "plus the team's average and latest rate. Use it to explain why a team started "
    "or stopped pressing."
)

# Tuned on dev seeds 0-99 against planted pressing changes (scripts/tune_detectors.py):
# best F1 among settings with at most 1.0 false positive per control-group match.
# Evaluated on untouched seeds 200-399 in docs/data/CALIBRATION.md.
# Absence of evidence is not evidence of absence: the detector is tuned to avoid false
# alarms and misses most drops in pressing, so "no shift" must never become "pressing
# stayed the same" in a narrative.
CANNOT_TELL_NO_SHIFT = (
    "That pressing stayed the same: no detected shift does not mean no change, "
    "especially a drop in pressing, which this detector mostly misses."
)
CAVEAT_VALIDATION = (
    "Checked against planted pressing changes in simulated matches: it catches clear "
    "increases in pressing but misses most drops (docs/data/CALIBRATION.md)."
)
THRESHOLDS: dict[str, float] = {
    "min_delta_per_min": 1.8,  # absolute change in pressures per minute, at least
    "min_relative_change": 0.25,  # and at least this fraction of the earlier rate
    "min_complete_windows": 2,  # rates need this many complete windows
}


class Params(ToolParams):
    team_id: Annotated[str, Field(description="Team whose pressing to analyse, e.g. 'T06'.")]
    scope: Annotated[Scope, Field(description=(
        "'latest': the latest complete window (and a shift only if it shows there) plus "
        "the current partial window's rate; 'all': every shift so far."))]


@dataclass(frozen=True)
class Shift:
    team_id: str
    window: Window
    before_per_min: float
    after_per_min: float

    @property
    def delta_per_min(self) -> float:
        return self.after_per_min - self.before_per_min


def complete_windows(v: MatchView) -> list[WindowStats]:
    return [s for s in window_stats(v) if s.window.complete and s.eligible]


def find_shifts(complete: list[WindowStats], team_id: str, min_delta_per_min: float,
                min_relative_change: float) -> tuple[Shift, ...]:
    """Shifts between consecutive complete windows (they may straddle half time)."""
    out = []
    for prev, cur in pairwise(complete):
        before, after = prev.pressures_per_min(team_id), cur.pressures_per_min(team_id)
        delta = abs(after - before)
        if delta >= min_delta_per_min and delta >= min_relative_change * before:
            out.append(Shift(team_id, cur.window, before, after))
    return tuple(out)


def detect_shifts(v: MatchView, team_id: str) -> tuple[Shift, ...]:
    v.team(team_id)
    return find_shifts(complete_windows(v), team_id, THRESHOLDS["min_delta_per_min"],
                       THRESHOLDS["min_relative_change"])


def shift_facts(shift: Shift, prefix: str) -> list[Fact]:
    (minute, added), _ = window_bounds(shift.window)
    return [
        minute_fact(f"{prefix}.minute", "Window where the shift shows", minute, added),
        fact(f"{prefix}.before_per_min", "Pressures per minute before",
             shift.before_per_min, "per_min"),
        fact(f"{prefix}.after_per_min", "Pressures per minute after",
             shift.after_per_min, "per_min"),
        fact(f"{prefix}.delta_per_min", "Change in pressures per minute",
             shift.delta_per_min, "per_min"),
        fact(f"{prefix}.direction", "Direction", "up" if shift.delta_per_min > 0 else "down",
             "label"),
    ]


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    team_id = params.team_id
    v.team(team_id)
    stats = window_stats(v)
    complete = [s for s in stats if s.window.complete and s.eligible]
    prefix = f"pressure.team:{team_id}"
    facts: list[Fact] = []
    cannot_tell: list[str] = []
    shown: list[tuple[int, Shift]] = []
    if len(complete) < THRESHOLDS["min_complete_windows"]:
        cannot_tell.append(
            f"Fewer than {THRESHOLDS['min_complete_windows']:g} complete windows; "
            "no rate comparison yet."
        )
    else:
        shifts = find_shifts(complete, team_id, THRESHOLDS["min_delta_per_min"],
                             THRESHOLDS["min_relative_change"])
        # Numbered over the whole match, so shift3 means the same thing in either scope.
        shown = list(enumerate(shifts, start=1))
        if params.scope == "latest":
            latest = window_key(complete[-1].window)
            shown = [(k, s) for k, s in shown if window_key(s.window) == latest]
        facts += [
            window_length_fact(),
            fact(f"{prefix}.mean_per_min", "Average pressures per minute",
                 fmean(s.pressures_per_min(team_id) for s in complete), "per_min"),
            fact(f"{prefix}.latest_per_min", "Pressures per minute, latest complete window",
                 complete[-1].pressures_per_min(team_id), "per_min"),
            fact(f"{prefix}.shifts", "Pressure shifts detected", len(shifts), "count"),
        ]
        for k, shift in shown:
            facts += shift_facts(shift, f"{prefix}.shift{k}")
        cannot_tell.append(CANNOT_TELL_NO_SHIFT)
    partial = stats[-1] if stats else None
    if partial is not None and not partial.window.complete and partial.eligible:
        facts.append(fact(f"{prefix}.current_per_min",
                          "Pressures per minute so far in the current window",
                          partial.pressures_per_min(team_id), "per_min"))
    rows = tuple(
        (k, window_key(s.window), round(s.before_per_min, 1), round(s.after_per_min, 1),
         round(s.delta_per_min, 1))
        for k, s in shown
    )[-20:]
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("shift", "window", "before_per_min", "after_per_min",
                             "delta_per_min"), rows=rows) if rows else None,
        sample_size=len(complete),
        method=(
            "Pressures per minute for the team in each complete 5-minute window, compared "
            "with the previous complete window. A shift needs a change of at least "
            f"{THRESHOLDS['min_delta_per_min']:g} per minute and at least "
            f"{THRESHOLDS['min_relative_change']:.0%} of the earlier rate."
        ),
        caveats=(CAVEAT_VALIDATION,
                 "A shift says the rate changed, not why: it may be tactics, the score, "
                 "fatigue or which zone the ball was in."),
        cannot_tell=tuple(cannot_tell),
    )
