"""Off-ball credit on hand-built frames (4 v 4, T1 attacks towards x = 105).

Each scenario has two events: the pass where the passer T1-3 received the ball
(frame BEFORE) and the pass T1-3 plays (frame NOW). Only the players named in a
scenario move between the two frames. In BEFORE, T2-2 marks both T1-2 and T1-4:
a run only creates space if it starts marked.
"""

import pytest
from mini_match import build_mini_match

from pitchside.events.match import Match
from pitchside.events.schema import Frame, Pass, PlayerXY, Point
from pitchside.metrics import off_ball

BEFORE = {
    "T1-1": (5.0, 34.0), "T1-2": (78.0, 30.0), "T1-3": (60.0, 34.0), "T1-4": (81.0, 34.0),
    "T2-1": (100.0, 34.0), "T2-2": (80.0, 32.0), "T2-3": (70.0, 55.0), "T2-4": (55.0, 15.0),
}


def _frame(pos):
    return Frame(players=tuple(PlayerXY(player_id=k, x=x, y=y)
                               for k, (x, y) in sorted(pos.items())))


def _pass(seq, passer, start, end, recipient, pos):
    return Pass(event_id=f"t-{seq}", match_id="mini", seq=seq, period=1, clock_s=10.0 * seq,
                team_id="T1", player_id=passer, location=Point(x=start[0], y=start[1]),
                end_location=Point(x=end[0], y=end[1]), recipient_id=recipient,
                duration_s=1.0, outcome="complete", height="ground", under_pressure=False,
                frame=_frame(pos))


def scenario(moves: dict, recipient: str, end: tuple[float, float]) -> Match:
    now = BEFORE | moves
    events = (
        _pass(0, "T1-2", BEFORE["T1-2"], BEFORE["T1-3"], "T1-3", BEFORE),  # T1-3 receives
        _pass(1, "T1-3", BEFORE["T1-3"], end, recipient, now),
    )
    return Match(metadata=build_mini_match().metadata, events=events)


def credits(match):
    return {c.player_id: c for c in off_ball.pass_credits(match.events, 1, match.metadata)}


def test_decoy_credits_the_runner_not_the_receiver():
    # T1-4 runs wide and T2-2, who was marking T1-2, goes with him: T1-2 is now free.
    match = scenario({"T1-4": (90.0, 58.0), "T2-2": (89.0, 57.0)}, "T1-2", BEFORE["T1-2"])
    c = credits(match)
    assert max(c.values(), key=lambda x: x.credit).player_id == "T1-4"
    assert c["T1-4"].credit > off_ball.THRESHOLDS["decisive_credit"]
    assert c["T1-2"].credit == 0.0  # the receiver did not move: no run, no credit
    assert c["T1-4"].control_with > c["T1-4"].control_without


def test_free_run_into_space_is_credited():
    # T1-4 runs into space behind T2-3; nobody follows.
    match = scenario({"T1-4": (92.0, 50.0)}, "T1-4", (92.0, 50.0))
    c = credits(match)
    assert max(c.values(), key=lambda x: x.credit).player_id == "T1-4"
    assert c["T1-4"].credit > off_ball.THRESHOLDS["decisive_credit"]


def test_tracked_run_earns_little():
    # Same run, but T2-2 goes with him: lots of movement, no space created.
    match = scenario({"T1-4": (92.0, 50.0), "T2-2": (90.5, 50.0)}, "T1-4", (92.0, 50.0))
    c = credits(match)
    assert c["T1-4"].credit < off_ball.THRESHOLDS["decisive_credit"]
    free = credits(scenario({"T1-4": (92.0, 50.0)}, "T1-4", (92.0, 50.0)))["T1-4"]
    assert c["T1-4"].credit < free.credit


def test_movement_with_the_block_is_not_a_run():
    # Everyone shifts 5 m forward together: relative to the block, nobody ran.
    shifted = {pid: (x + 5.0, y) for pid, (x, y) in BEFORE.items() if pid != "T1-3"}
    match = scenario(shifted, "T1-2", (83.0, 30.0))
    assert all(c.credit == 0.0 for c in credits(match).values())


def test_no_reception_in_view_means_no_credit():
    match = scenario({"T1-4": (92.0, 50.0)}, "T1-4", (92.0, 50.0))
    lone = Match(metadata=match.metadata, events=match.events[1:])
    assert off_ball.pass_credits(lone.events, 0, lone.metadata) == []


def test_tool_reports_the_decisive_decoy():
    match = scenario({"T1-4": (90.0, 58.0), "T2-2": (89.0, 57.0)}, "T1-2", BEFORE["T1-2"])
    result = off_ball.run(match, off_ball.Params(as_of_seq=1, scope="latest"))
    d = {f.evidence_id: f.display for f in result.facts}
    assert d["offball.team:T1.decisive_runs"] == "1"
    assert d["offball.run@1.kind"] == "decoy run"
    assert d["offball.run@1.runner_shirt"] == "4"
    assert int(d["offball.run@1.control_with"][:-1]) > int(d["offball.run@1.control_without"][:-1])


def test_tool_without_positions_says_so():
    result = off_ball.run(build_mini_match(), off_ball.Params(as_of_seq=19, scope="all"))
    assert result.facts == () and "no player positions" in result.cannot_tell[0]


@pytest.mark.parametrize("pid", ["T1-2", "T1-4"])
def test_relative_moves_remove_the_block_shift(pid):
    now = {k: (x + 3.0, y - 1.0) for k, (x, y) in BEFORE.items()}
    moves = off_ball.relative_moves(now, BEFORE, {"T1-1", "T1-2", "T1-4"})
    assert moves[pid] == pytest.approx((0.0, 0.0))
