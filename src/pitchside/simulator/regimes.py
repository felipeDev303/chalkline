"""Planted tactical regimes and their ground truth.

Each team's pressure intensity is a multiplier on the pressure probability:
planned spells (pressing harder or dropping off for 10-18 minutes) at seeded times,
times a trailing factor once a team is behind from 60'. Seeds divisible by
`control_every` are a control group with no regimes, which leaves their event
stream identical to a simulator without regimes.

Truth is written only by the simulator, to a `<match>.truth.json` sidecar; it never
enters the event stream, and metrics/ never reads it (tests/test_metrics_isolation.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pitchside.simulator.params import SimParams
from pitchside.simulator.rng import Rng
from pitchside.simulator.runs import RunLabel

PERIOD_MINUTES = 45
Cause = Literal["planned_press", "planned_drop", "spell_end", "trailing", "trailing_end"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Spell(_Strict):
    period: Literal[1, 2]
    start_s: float
    end_s: float
    factor: float


class RegimeChange(_Strict):
    """A change of a team's effective pressure intensity, when it took effect."""

    team_id: str
    period: Literal[1, 2]
    clock_s: float
    minute: int  # football minute: 0-59 s is 1'; the second half starts at 46'
    direction: Literal["up", "down"]
    magnitude: float  # new intensity / old intensity
    cause: Cause


class PressureSpan(_Strict):
    """A planned high-pressure spell, for evaluating windows that fall inside it."""

    team_id: str
    period: Literal[1, 2]
    start_s: float
    end_s: float
    factor: float


class MatchTruth(_Strict):
    match_id: str
    seed: int
    control_group: bool
    changes: tuple[RegimeChange, ...]
    high_pressure_spans: tuple[PressureSpan, ...]
    runs: tuple[RunLabel, ...] = ()  # planted off-ball runs (simulator/runs.py)


def truth_path(jsonl_path: Path) -> Path:
    """data/match_42.jsonl -> data/match_42.truth.json"""
    return jsonl_path.with_name(f"{jsonl_path.stem}.truth.json")


def write_truth(truth: MatchTruth, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(truth.model_dump_json(indent=2).encode() + b"\n")


def read_truth(path: Path) -> MatchTruth:
    return MatchTruth.model_validate_json(path.read_bytes())


def is_control(seed: int, params: SimParams) -> bool:
    return seed % params.control_every == 0


def plan_spells(seed: int, params: SimParams) -> tuple[tuple[Spell, ...], tuple[Spell, ...]]:
    """Seeded spells per side (home, away), from a stream separate from the match."""
    if is_control(seed, params):
        return ((), ())
    rng = Rng(f"regimes:{seed}")
    out = []
    for _side in (0, 1):
        lo, hi = params.spells_per_team
        wanted = lo + rng.index(hi - lo + 1)
        spells: list[Spell] = []
        for _attempt in range(20):
            if len(spells) == wanted:
                break
            period = 1 + rng.index(2)
            start = rng.uniform(*params.spell_start_s)
            end = min(start + rng.uniform(*params.spell_duration_s), params.spell_latest_end_s)
            high = rng.chance(params.high_spell_prob)
            factor = rng.uniform(*(params.high_factor if high else params.low_factor))
            gap = params.spell_min_gap_s
            if all(s.period != period or start >= s.end_s + gap or end <= s.start_s - gap
                   for s in spells):
                spells.append(Spell(period=period, start_s=start, end_s=end, factor=factor))
        out.append(tuple(sorted(spells, key=lambda s: (s.period, s.start_s))))
    return out[0], out[1]


@dataclass
class RegimeTracker:
    """Effective intensity per side; records each change as ground truth."""

    seed: int
    params: SimParams
    team_ids: tuple[str, str]
    spells: tuple[tuple[Spell, ...], tuple[Spell, ...]]
    changes: list[RegimeChange] = field(default_factory=list)
    _state: list[tuple[float, bool]] = field(default_factory=lambda: [(1.0, False), (1.0, False)])

    @property
    def control(self) -> bool:
        return is_control(self.seed, self.params)

    def _spell_factor(self, side: int, period: int, clock_s: float) -> float:
        for s in self.spells[side]:
            if s.period == period and s.start_s <= clock_s < s.end_s:
                return s.factor
        return 1.0

    def _trailing(self, side: int, period: int, clock_s: float, goals: list[int]) -> bool:
        if self.control or period != 2 or clock_s < self.params.trailing_from_s:
            return False
        return goals[side] < goals[1 - side]

    def intensity(self, side: int) -> float:
        factor, trailing = self._state[side]
        return factor * (self.params.trailing_factor if trailing else 1.0)

    def observe(self, period: int, clock_s: float, goals: list[int]) -> None:
        """Update both sides at the current time; record any change in intensity."""
        for side in (0, 1):
            old = self.intensity(side)
            old_factor, old_trailing = self._state[side]
            factor = self._spell_factor(side, period, clock_s)
            trailing = self._trailing(side, period, clock_s, goals)
            self._state[side] = (factor, trailing)
            new = self.intensity(side)
            if new == old:
                continue
            if factor != old_factor:
                cause: Cause = ("spell_end" if factor == 1.0
                                else "planned_press" if factor > 1.0 else "planned_drop")
            else:
                cause = "trailing" if trailing else "trailing_end"
            minute = int(clock_s // 60) + 1 + (PERIOD_MINUTES if period == 2 else 0)
            self.changes.append(RegimeChange(
                team_id=self.team_ids[side], period=period, clock_s=round(clock_s, 2),
                minute=minute, direction="up" if new > old else "down",
                magnitude=round(new / old, 2), cause=cause,
            ))

    def truth(self, match_id: str) -> MatchTruth:
        spans = tuple(
            PressureSpan(team_id=self.team_ids[side], period=s.period, start_s=round(s.start_s, 2),
                         end_s=round(s.end_s, 2), factor=round(s.factor, 2))
            for side in (0, 1) for s in self.spells[side] if s.factor > 1.0
        )
        return MatchTruth(match_id=match_id, seed=self.seed, control_group=self.control,
                          changes=tuple(self.changes), high_pressure_spans=spans)
