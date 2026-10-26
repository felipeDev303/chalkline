"""Producer: decides which moments go on air, causally, within an attention budget.

It walks the match in steps and only ever looks at the moments known at that step
(`key_moments.all_moments` on the match cut there), so a replay never airs what
could only be known later. "Best so far" moments (hardest pass, most threatening
pass) keep changing as the match goes on, so they are left to recaps.

Budget (all deterministic, documented in docs/METHODS.md, "Producer"):
- a story needs `min_importance`, except goals, which always air;
- stories are at least `gap_s` of match time apart, unless a goal or important enough
  to break in;
- the same kind of story for the same team does not repeat within `repeat_s`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pitchside.events.match import Match
from pitchside.metrics._timeline import view
from pitchside.metrics.key_moments import Moment, all_moments

AIRABLE = frozenset({"goal", "big_chance", "decisive_run", "swing", "pressure_shift",
                     "sequence", "milestone"})
PRODUCER: dict[str, float] = {
    "step_events": 25,  # the producer looks again every this many events
    "min_importance": 40,
    "break_in_importance": 90,  # air regardless of the gap (goals always do)
    "gap_s": 90,
    "repeat_s": 300,
}
PERIOD_OFFSET_S = 3000.0  # period 2 clock + this = monotonic match time


@dataclass(frozen=True)
class Story:
    moment: Moment
    aired_at_seq: int  # first step at which the producer knew and aired it

    @property
    def story_id(self) -> str:
        team = f".{self.moment.team_id}" if self.moment.team_id else ""
        return f"{self.moment.kind}@{self.moment.seq}{team}"


def _match_time(match: Match, seq: int) -> float:
    e = next(ev for ev in reversed(match.events) if ev.seq <= seq)
    return e.clock_s + (e.period - 1) * PERIOD_OFFSET_S


def air_schedule(match: Match) -> list[Story]:
    """Every story the producer puts on air during the match, in airing order."""
    if not match.events:
        return []
    step = int(PRODUCER["step_events"])
    last = match.events[-1].seq
    checkpoints = [*range(match.events[0].seq + step, last, step), last]
    seen: set[tuple[str, int, str | None]] = set()
    aired: list[Story] = []
    for seq in checkpoints:
        now = _match_time(match, seq)
        new = [m for m in all_moments(view(match, seq))
               if m.kind in AIRABLE and (m.kind, m.seq, m.team_id) not in seen]
        for m in sorted(new, key=lambda m: (-m.importance, m.seq)):
            seen.add((m.kind, m.seq, m.team_id))
            breaks_in = m.kind == "goal" or m.importance >= PRODUCER["break_in_importance"]
            if m.importance < PRODUCER["min_importance"] and m.kind != "goal":
                continue
            if aired and not breaks_in:
                since = now - _match_time(match, aired[-1].aired_at_seq)
                if since < PRODUCER["gap_s"]:
                    continue
                if any(s.moment.kind == m.kind and s.moment.team_id == m.team_id
                       and now - _match_time(match, s.aired_at_seq) < PRODUCER["repeat_s"]
                       for s in aired):
                    continue
            aired.append(Story(m, seq))
    return aired


def on_air(schedule: list[Story], as_of_seq: int, limit: int = 5) -> list[Story]:
    """Stories aired by `as_of_seq`, newest first."""
    return [s for s in reversed(schedule) if s.aired_at_seq <= as_of_seq][:limit]
