"""The scoring rules behind the precision / recall reported in CALIBRATION.md."""

import sys
from pathlib import Path

import pytest
from mini_match import build_pressure_match

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import detector_eval  # noqa: E402
from detector_eval import MatchData, score_chaos, score_shifts  # noqa: E402

from pitchside.metrics._timeline import view  # noqa: E402
from pitchside.metrics.control_vs_chaos import window_stats  # noqa: E402
from pitchside.simulator.regimes import MatchTruth, PressureSpan, RegimeChange  # noqa: E402


def _data(changes=(), spans=(), control=False) -> MatchData:
    # T1 presses 0.4, 0.4, 2.4, 2.4 per minute: one detected shift up in window 2.
    match = build_pressure_match()
    truth = MatchTruth(match_id="mini", seed=1, control_group=control, changes=tuple(changes),
                       high_pressure_spans=tuple(spans))
    stats = [s for s in window_stats(view(match, match.events[-1].seq)) if s.eligible]
    return MatchData(match, truth, stats, [s for s in stats if s.window.complete])


def _change(clock_s, direction="up", team="T1"):
    return RegimeChange(team_id=team, period=1, clock_s=clock_s, minute=int(clock_s // 60) + 1,
                        direction=direction, magnitude=2.0 if direction == "up" else 0.5,
                        cause="planned_press" if direction == "up" else "planned_drop")


@pytest.mark.parametrize(("clock_s", "hit"), [(650, True), (350, True), (950, True),
                                              (1250, False)])
def test_hit_within_one_window(clock_s, hit):
    s = score_shifts([_data([_change(clock_s)])], 1.6, 0.25)
    assert (s.detections, s.planted, s.hits) == (1, 1, int(hit))


def test_direction_and_team_must_match():
    assert score_shifts([_data([_change(650, "down")])], 1.6, 0.25).hits == 0
    assert score_shifts([_data([_change(650, team="T2")])], 1.6, 0.25).hits == 0


def test_each_planted_change_is_hit_once():
    s = score_shifts([_data([_change(650), _change(700)])], 1.6, 0.25)
    assert (s.hits, s.planted, s.precision, s.recall) == (1, 2, 1.0, 0.5)


def test_control_matches_only_count_false_positives():
    s = score_shifts([_data(control=True)], 1.6, 0.25)
    assert (s.detections, s.planted, s.control_detections, s.fp_per_control_match) == (
        0, 0, 1, 1.0)


def test_chaos_inside_vs_outside_spans():
    span = PressureSpan(team_id="T1", period=1, start_s=600, end_s=900, factor=2.5)
    c = score_chaos([_data(spans=[span])])
    assert (c.inside_windows, c.outside_windows) == (1, 3)  # window 2's midpoint is inside


def test_dev_and_test_seeds_are_disjoint():
    assert not set(detector_eval.DEV_SEEDS) & set(detector_eval.TEST_SEEDS)
