"""A 20-event hand-built match. Expected values in the tests are worked out here.

T1 (home) attacks towards x = 105 in period 1; T2 towards x = 0. Ends swap at
half time. Each team: GK, DF, MF, FW -> formation "1-1-1".

seq  P  clock  event                                    in possession after
  0  1    0.0  kickoff T1                               T1
  1  1    0.0  pass T1-4 -> T1-3, complete              T1
  2  1    4.0  pass T1-3 -> T1-4, complete (low)        T1
  3  1    8.0  pressure T2-2 on T1-4                    T1
  4  1    8.0  pass T1-4, incomplete, under pressure    T1
  5  1    9.5  possession T2-2, interception            T2
  6  1   12.0  pass T2-2 -> T2-4, complete              T2
  7  1   20.0  shot T2-4 at (12, 30): goal              T2
  8  1   80.0  kickoff T1                               T1
  9  1   80.0  possession T1-4, shot_end                T1
 10  1   80.0  pass T1-4 -> T1-3, complete              T1
 11  1   85.0  pass T1-3, out                           T1
 12  1  105.0  possession T2-3, out_of_play             T2
 13  1  110.0  pass T2-3 -> T2-2, complete (low)        T2
 14  1  112.0  tackle T1-2 on T2-2, won                 T2
 15  1  112.0  possession T1-2, tackle                  T1
 16  1 2705.0  half time                                -
 17  2    0.0  kickoff T2                               T2
 18  2    0.0  pass T2-4 -> T2-3, complete              T2
 19  2   10.0  full time                                -

Possessions: T1 0-4 (3 passes), T2 5-7 (1), T1 8-11 (2), T2 12-14 (1),
T1 15-15 (0), T2 17-18 (1).

In-play possession seconds (gaps ending in a restart are dead time):
T1 = 4 + 4 + 0 + 1.5 (1->2, 2->3, 3->4, 4->5) + 0 + 5 (9->10, 10->11) = 14.5
T2 = 2.5 + 8 (5->6, 6->7) + 5 + 2 + 0 (12->13, 13->14, 14->15) = 17.5
Dead: 7->8 kickoff, 8->9 shot_end, 11->12 out_of_play, 15->16 and 18->19 phases.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pitchside.events.match import Match
from pitchside.events.schema import (
    MatchMetadata,
    Pass,
    Phase,
    Player,
    Point,
    PossessionChange,
    Pressure,
    Shot,
    Tackle,
    Team,
)

CENTRE = (52.5, 34.0)


def _team(n: int, name: str) -> Team:
    positions = ("GK", "DF", "MF", "FW")
    surnames = ("Keeper", "Back", "Middle", "Forward")  # no digits: names are labels
    return Team(
        team_id=f"T{n}",
        name=name,
        short_name=name[:3].upper(),
        players=tuple(
            Player(player_id=f"T{n}-{i}", name=f"{name.split()[0]} {surnames[i - 1]}",
                   shirt_number=i, position=pos)
            for i, pos in enumerate(positions, start=1)
        ),
    )


def _base(seq: int, period: int, clock: float, team: str, player: str | None,
          at: tuple[float, float]) -> dict:
    return {
        "event_id": f"mini-{seq:03d}", "match_id": "mini", "seq": seq, "period": period,
        "clock_s": clock, "team_id": team, "player_id": player,
        "location": Point(x=at[0], y=at[1]),
    }


def _pass(seq, period, clock, team, player, at, end, recipient, outcome,
          height="ground", duration=1.0, pressured=False) -> Pass:
    return Pass(**_base(seq, period, clock, team, player, at),
                end_location=Point(x=end[0], y=end[1]), recipient_id=recipient,
                duration_s=duration, outcome=outcome, height=height,
                under_pressure=pressured)


def _change(seq, clock, team, player, at, from_team, cause, period=1) -> PossessionChange:
    return PossessionChange(**_base(seq, period, clock, team, player, at),
                            from_team_id=from_team, cause=cause)


def _phase(seq, period, clock, team, phase) -> Phase:
    return Phase(**_base(seq, period, clock, team, None, CENTRE), phase=phase)


def build_pressure_match(pressures_per_window: tuple[int, ...] = (2, 2, 12, 12)) -> Match:
    """T2 keeps the ball (12 short passes per 5-minute window) while T1 presses
    `pressures_per_window[i]` times in window i. One last pass at 20:50 opens a partial
    window. With the default counts, T1 presses 0.4, 0.4, 2.4, 2.4 per minute: one
    upward shift (+2.0/min) in the window starting at 10'.
    """
    timeline: list[tuple[float, str]] = [(0.0, "kickoff")]
    for i, count in enumerate(pressures_per_window):
        base = i * 300.0
        timeline += [(base + 2 + 20 * j, "pass") for j in range(12)]
        timeline += [(base + 5 + 20 * j, "pressure") for j in range(count)]
    timeline.append((len(pressures_per_window) * 300.0 + 50, "pass"))
    events = []
    for seq, (clock, kind) in enumerate(sorted(timeline)):
        if kind == "kickoff":
            events.append(_phase(seq, 1, clock, "T2", "kickoff"))
        elif kind == "pass":
            events.append(_pass(seq, 1, clock, "T2", "T2-3", (50.0, 34.0), (45.0, 34.0),
                                "T2-2", "complete"))
        else:
            events.append(Pressure(**_base(seq, 1, clock, "T1", "T1-2", (50.0, 34.0)),
                                   target_player_id="T2-3", duration_s=1.0))
    return Match(metadata=build_mini_match().metadata, events=tuple(events))


def build_mini_match() -> Match:
    metadata = MatchMetadata(
        match_id="mini",
        seed=0,
        home=_team(1, "Alder Town"),
        away=_team(2, "Birch Rovers"),
        competition="Fixture League",
        venue="Test Ground",
        kickoff_utc=datetime(2026, 1, 1, 15, 0, tzinfo=UTC),
        home_attacks_high_x_in_period_1=True,
    )
    events = (
        _phase(0, 1, 0.0, "T1", "kickoff"),
        _pass(1, 1, 0.0, "T1", "T1-4", CENTRE, (45.0, 34.0), "T1-3", "complete", duration=0.8),
        _pass(2, 1, 4.0, "T1", "T1-3", (45.0, 34.0), (75.0, 50.0), "T1-4", "complete",
              height="low", duration=2.0),
        Pressure(**_base(3, 1, 8.0, "T2", "T2-2", (75.0, 50.0)),
                 target_player_id="T1-4", duration_s=1.5),
        _pass(4, 1, 8.0, "T1", "T1-4", (75.0, 50.0), (90.0, 40.0), None, "incomplete",
              duration=1.2, pressured=True),
        _change(5, 9.5, "T2", "T2-2", (90.0, 40.0), "T1", "interception"),
        _pass(6, 1, 12.0, "T2", "T2-2", (90.0, 40.0), (60.0, 30.0), "T2-4", "complete",
              duration=2.5),
        Shot(**_base(7, 1, 20.0, "T2", "T2-4", (12.0, 30.0)), outcome="goal",
             body_part="right_foot", speed_kmh=95.0, under_pressure=False),
        _phase(8, 1, 80.0, "T1", "kickoff"),
        _change(9, 80.0, "T1", "T1-4", CENTRE, "T2", "shot_end"),
        _pass(10, 1, 80.0, "T1", "T1-4", CENTRE, (40.0, 30.0), "T1-3", "complete"),
        _pass(11, 1, 85.0, "T1", "T1-3", (40.0, 30.0), (70.0, 68.0), None, "out",
              duration=2.0),
        _change(12, 105.0, "T2", "T2-3", (70.0, 68.0), "T1", "out_of_play"),
        _pass(13, 1, 110.0, "T2", "T2-3", (70.0, 68.0), (75.0, 60.0), "T2-2", "complete",
              height="low", duration=0.6),
        Tackle(**_base(14, 1, 112.0, "T1", "T1-2", (75.0, 60.0)), opponent_id="T2-2", won=True),
        _change(15, 112.0, "T1", "T1-2", (75.0, 60.0), "T2", "tackle"),
        _phase(16, 1, 2705.0, "T1", "half_time"),
        _phase(17, 2, 0.0, "T2", "kickoff"),
        _pass(18, 2, 0.0, "T2", "T2-4", CENTRE, (60.0, 34.0), "T2-3", "complete", duration=0.9),
        _phase(19, 2, 10.0, "T1", "full_time"),
    )
    return Match(metadata=metadata, events=events)
