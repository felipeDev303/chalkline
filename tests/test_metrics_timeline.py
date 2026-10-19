import pytest
from mini_match import build_mini_match

from pitchside.events.match import Match
from pitchside.events.schema import Point
from pitchside.metrics._timeline import (
    Possession,
    attack_frame,
    formation,
    in_box,
    in_final_third,
    match_minute,
    possession_seconds,
    possessions,
    view,
    windows,
)
from pitchside.metrics.contract import ToolError


@pytest.fixture(scope="module")
def mini():
    return build_mini_match()


def test_view_cuts_at_as_of_seq(mini):
    assert [e.seq for e in view(mini, 7).events] == list(range(8))
    assert view(mini, 19).events == mini.events
    truncated = Match(metadata=mini.metadata, events=mini.events[:8])
    assert view(truncated, 7) == view(mini, 7)


def test_view_rejects_out_of_range(mini):
    with pytest.raises(ToolError) as err:
        view(mini, 20)
    assert err.value.code == "as_of_out_of_range"


def test_team_and_player_lookup(mini):
    v = view(mini, 19)
    assert v.opponent("T1").team_id == "T2"
    assert v.player("T2-4")[0].team_id == "T2"
    with pytest.raises(ToolError) as err:
        v.team("T9")
    assert err.value.code == "unknown_team"
    with pytest.raises(ToolError) as err:
        v.player("T1-9")
    assert err.value.code == "unknown_player"


def test_attack_frame_follows_metadata_and_swaps_at_half_time(mini):
    meta = mini.metadata
    shot = Point(x=12.0, y=30.0)
    assert attack_frame(meta, "T1", 1, shot) == (12.0, 30.0)
    assert attack_frame(meta, "T2", 1, shot) == (93.0, 38.0)
    assert attack_frame(meta, "T2", 2, shot) == (12.0, 30.0)
    assert in_box((93.0, 38.0)) and not in_box((80.0, 34.0))
    assert in_box((88.5, 13.84)) and not in_box((88.5, 13.83))
    assert in_final_third((70.0, 0.0)) and not in_final_third((69.9, 0.0))


@pytest.mark.parametrize(
    ("period", "clock", "expected"),
    [(1, 0.0, (1, 0)), (1, 59.9, (1, 0)), (1, 60.0, (2, 0)), (1, 2699.0, (45, 0)),
     (1, 2705.0, (45, 1)), (2, 0.0, (46, 0)), (2, 2700.0, (90, 1)), (2, 2830.0, (90, 3))],
)
def test_match_minute(period, clock, expected):
    assert match_minute(period, clock) == expected


def test_possessions(mini):
    assert possessions(view(mini, 19).events) == (
        Possession("T1", 1, 0, 4, 3, 0.0, 8.0),
        Possession("T2", 1, 5, 7, 1, 9.5, 20.0),
        Possession("T1", 1, 8, 11, 2, 80.0, 85.0),
        Possession("T2", 1, 12, 14, 1, 105.0, 112.0),
        Possession("T1", 1, 15, 15, 0, 112.0, 112.0),
        Possession("T2", 2, 17, 18, 1, 0.0, 0.0),
    )


def test_possession_in_progress_is_included(mini):
    assert possessions(view(mini, 6).events)[-1] == Possession("T2", 1, 5, 6, 1, 9.5, 12.0)


def test_possession_seconds_exclude_dead_time(mini):
    assert possession_seconds(view(mini, 19)) == {"T1": 14.5, "T2": 17.5}
    assert possession_seconds(view(mini, 7)) == {"T1": 9.5, "T2": 10.5}


def test_windows_full_match(mini):
    ws = windows(view(mini, 19))
    assert [(w.period, w.index) for w in ws] == [(1, i) for i in range(10)] + [(2, 0)]
    first = ws[0]
    assert first.complete and first.observed_s == 300.0
    assert [e.seq for e in first.events] == list(range(16))
    assert all(w.complete and not w.events for w in ws[1:9])
    assert (ws[9].observed_s, ws[9].complete, [e.seq for e in ws[9].events]) == (5.0, False, [16])
    assert (ws[10].observed_s, ws[10].complete) == (10.0, False)


def test_current_window_is_partial(mini):
    (only,) = windows(view(mini, 7))
    assert (only.observed_s, only.complete, len(only.events)) == (20.0, False, 8)


def test_formation(mini):
    assert formation(mini.metadata.home) == "1-1-1"
