"""Each tool on hand-built matches; expected values worked out in the comments.

Event list and possession arithmetic: tests/mini_match.py.
"""

import pytest
from mini_match import build_mini_match, build_pressure_match

from pitchside.metrics import (
    control_vs_chaos,
    key_moments,
    match_summary,
    pass_profile,
    player_focus,
    pressure_shift,
    shot_profile,
)
from pitchside.metrics.contract import ToolError


@pytest.fixture(scope="module")
def mini():
    return build_mini_match()


def displays(result) -> dict[str, str]:
    return {f.evidence_id: f.display for f in result.facts}


# --- match_summary ---------------------------------------------------------------

def test_match_summary(mini, monkeypatch):
    # 32 s in play is under the 60 s minimum; lower it to check the share arithmetic.
    monkeypatch.setitem(match_summary.THRESHOLDS, "min_in_play_s", 10.0)
    d = displays(match_summary.run(mini, match_summary.Params(as_of_seq=19)))
    assert d["summary.scoreline"] == "0-1"  # T2's goal at seq 7
    assert d["summary.minute"] == "46'"  # full time at 0:10 of period 2
    assert (d["summary.team:T1.passes"], d["summary.team:T2.passes"]) == ("5", "3")
    assert (d["summary.team:T2.shots"], d["summary.team:T2.shots_on_target"]) == ("1", "1")
    assert d["summary.team:T1.formation"] == "1-1-1"
    # 14.5 / 32 = 45.3% -> 45%; 17.5 / 32 = 54.7% -> 55%
    assert (d["summary.team:T1.possession_share"], d["summary.team:T2.possession_share"]) == (
        "45%", "55%")
    assert "summary.team:T1.completion_pct" not in d  # 5 passes < 15


def test_match_summary_withholds_weak_numbers(mini):
    result = match_summary.run(mini, match_summary.Params(as_of_seq=19))
    ids = {f.evidence_id for f in result.facts}
    assert not any("possession_share" in i or "completion_pct" in i for i in ids)
    assert len(result.cannot_tell) == 3  # two completion notes, one possession note


# --- pass_profile ----------------------------------------------------------------

def test_pass_difficulty_by_hand(mini):
    meta = mini.metadata
    p1, p2, p10 = mini.events[1], mini.events[2], mini.events[10]
    # p2: 34 m (0.30 * 0.68) + low (0.15 * 0.5) + 30 m forward (0.20) + ends in final
    # third (0.15 * 0.5) = 0.554
    assert pass_profile.pass_difficulty(meta, p2) == pytest.approx(55.4)
    # p1: 7.5 m backwards on the ground: only length, 0.30 * 0.15 = 0.045
    assert pass_profile.pass_difficulty(meta, p1) == pytest.approx(4.5)
    # p10: 13.12 m backwards: 0.30 * 13.124 / 50
    assert pass_profile.pass_difficulty(meta, p10) == pytest.approx(7.87, abs=0.01)
    assert pass_profile.pass_speed_kmh(p2) == pytest.approx(61.2)  # 34 m in 2 s


def test_pass_profile_team(mini, monkeypatch):
    monkeypatch.setitem(pass_profile.THRESHOLDS, "min_passes", 1)
    params = pass_profile.Params(as_of_seq=19, subject="team", subject_id="T1")
    d = displays(pass_profile.run(mini, params))
    assert d["pass.team:T1.count"] == "5"
    assert d["pass.team:T1.completion_pct"] == "60.0%"  # seqs 1, 2, 10 of 1, 2, 4, 10, 11
    # (7.5 + 34 + 18.03 + 13.12 + 48.41) / 5 = 24.21
    assert d["pass.team:T1.mean_distance_m"] == "24.2 m"
    # (33.75 + 61.2 + 54.08 + 47.25 + 87.15) / 5 = 56.69
    assert d["pass.team:T1.mean_speed_kmh"] == "56.7 km/h"
    assert (d["pass.team:T1.hardest1.difficulty"], d["pass.team:T1.hardest1.minute"],
            d["pass.team:T1.hardest1.distance_m"]) == ("55", "1'", "34.0 m")
    assert (d["pass.team:T1.hardest2.difficulty"], d["pass.team:T1.hardest2.minute"]) == (
        "8", "2'")


def test_pass_profile_player_and_min_sample(mini):
    params = pass_profile.Params(as_of_seq=19, subject="player", subject_id="T1-4")
    result = pass_profile.run(mini, params)
    d = displays(result)
    assert d["pass.player:T1-4.count"] == "3"  # seqs 1, 4, 10
    assert "pass.player:T1-4.completion_pct" not in d
    assert result.cannot_tell


def test_pass_profile_unknown_subject(mini):
    with pytest.raises(ToolError) as err:
        pass_profile.run(mini, pass_profile.Params(as_of_seq=19, subject="player",
                                                   subject_id="T1-9"))
    assert err.value.code == "unknown_player"


# --- shot_profile ----------------------------------------------------------------

def test_chance_quality_by_hand(mini):
    # T2 attacks x = 0 in period 1, so (12, 30) is (93, 38) in its frame. Posts at
    # y = 30.34 and 37.66: angle = atan2(87.84, 146.60) = 0.5397 rad. From the penalty
    # spot: 2 * atan(3.66 / 11) = 0.6423 rad. 0.5397 / 0.6423 = 84.03%.
    assert shot_profile.chance_quality(mini.metadata, mini.events[7]) == pytest.approx(
        84.03, abs=0.01)
    assert shot_profile.goal_mouth_angle(94.0, 34.0) == pytest.approx(
        shot_profile.REFERENCE_ANGLE)


def test_shot_profile(mini):
    params = shot_profile.Params(as_of_seq=19, subject="team", subject_id="T2")
    result = shot_profile.run(mini, params)
    d = displays(result)
    assert (d["shot.team:T2.shots"], d["shot.team:T2.on_target"], d["shot.team:T2.goals"]) == (
        "1", "1", "1")
    assert d["shot.team:T2.max_speed_kmh"] == "95.0 km/h"
    assert (d["shot.team:T2.best_chance.quality"], d["shot.team:T2.best_chance.minute"]) == (
        "84", "1'")
    assert "shot.team:T2.mean_speed_kmh" not in d and result.cannot_tell  # 1 shot < 3


# --- control_vs_chaos ------------------------------------------------------------

def test_control_vs_chaos(mini):
    result = control_vs_chaos.run(mini, control_vs_chaos.Params(as_of_seq=19, scope="all"))
    d = displays(result)
    # Only window p1.w00 has events and >= 120 s of play.
    assert result.sample_size == 1
    w = "window.p1.w00"
    assert (d[f"{w}.start"], d[f"{w}.end"]) == ("0'", "5'")
    # interception (seq 5) + tackle (seq 15) in 5 minutes
    assert d[f"{w}.turnovers_per_min"] == "0.4/min"
    assert d[f"{w}.completion_pct"] == "71.4%"  # 5 of 7 passes
    assert (d[f"{w}.team:T1.possession_share"], d[f"{w}.team:T2.possession_share"]) == (
        "45%", "55%")
    assert d[f"{w}.team:T2.pressures_per_min"] == "0.2/min"
    # 55% < 56% for control, 0.4 < 2.0 turnovers/min and 71.4% >= 70% for chaos
    assert d[f"{w}.state"] == "contested"
    assert d["window.all.contested_share"] == "100%"
    # 8 passes over 6 possessions
    assert d["rhythm.mean_possession_passes"] == "1.3"
    # 20 events over 45.25 minutes of observed play (2705 s + 10 s)
    assert d["rhythm.events_per_min"] == "0.4/min"
    assert control_vs_chaos.CAVEAT_THRESHOLDS in result.caveats


def test_control_vs_chaos_before_any_window(mini):
    result = control_vs_chaos.run(mini, control_vs_chaos.Params(as_of_seq=7, scope="all"))
    assert result.sample_size == 0 and result.cannot_tell


def test_window_classification_rules(mini):
    stats = control_vs_chaos.window_stats(
        control_vs_chaos.view(build_pressure_match(), 52))[0]
    # T2 has every in-play second, no turnovers, all passes complete: control.
    assert stats.dominant == ("T2", 100.0)
    assert stats.state == "control"


# --- pressure_shift --------------------------------------------------------------

def test_pressure_shift_detects_planted_change():
    match = build_pressure_match()
    result = pressure_shift.run(match, pressure_shift.Params(as_of_seq=match.events[-1].seq,
                                                             team_id="T1", scope="all"))
    d = displays(result)
    assert d["pressure.team:T1.shifts"] == "1"
    s = "pressure.team:T1.shift1"
    assert (d[f"{s}.minute"], d[f"{s}.before_per_min"], d[f"{s}.after_per_min"],
            d[f"{s}.delta_per_min"], d[f"{s}.direction"]) == (
        "10'", "0.4/min", "2.4/min", "2.0/min", "up")
    assert d["pressure.team:T1.mean_per_min"] == "1.4/min"  # (0.4+0.4+2.4+2.4) / 4
    assert d["pressure.team:T1.latest_per_min"] == "2.4/min"


def test_no_shift_is_never_evidence_of_no_change():
    match = build_pressure_match((2, 2, 2, 2))  # flat pressing: nothing detected
    last = match.events[-1].seq
    for scope in ("latest", "all"):
        result = pressure_shift.run(match, pressure_shift.Params(as_of_seq=last, team_id="T1",
                                                                 scope=scope))
        assert displays(result)["pressure.team:T1.shifts"] == "0"
        assert pressure_shift.CANNOT_TELL_NO_SHIFT in result.cannot_tell
    moments = key_moments.run(match, key_moments.Params(as_of_seq=last, limit=5))
    assert pressure_shift.CANNOT_TELL_NO_SHIFT in moments.cannot_tell


def test_pressure_shift_needs_both_conditions():
    # +1.4/min (0.4 -> 1.8) is under the 1.6 absolute threshold
    match = build_pressure_match((2, 2, 9, 9))
    d = displays(pressure_shift.run(match, pressure_shift.Params(
        as_of_seq=match.events[-1].seq, team_id="T1", scope="all")))
    assert d["pressure.team:T1.shifts"] == "0"


def test_pressure_shift_min_sample(mini):
    params = pressure_shift.Params(as_of_seq=19, team_id="T1", scope="all")
    result = pressure_shift.run(mini, params)
    assert result.facts == () and result.cannot_tell


def _seq_at(match, clock_s):
    return next(e.seq for e in match.events if e.clock_s >= clock_s)


def test_pressure_shift_latest_scope():
    match = build_pressure_match()
    # Just after 15:00 the latest complete window is w02, where the shift shows.
    early = pressure_shift.run(match, pressure_shift.Params(
        as_of_seq=_seq_at(match, 900), team_id="T1", scope="latest"))
    assert "pressure.team:T1.shift1.minute" in displays(early)
    # At 17:02 (122 s into w03) w03 is partial but classifiable: its rate is shown.
    mid = displays(pressure_shift.run(match, pressure_shift.Params(
        as_of_seq=_seq_at(match, 1022), team_id="T1", scope="latest")))
    assert "pressure.team:T1.current_per_min" in mid and "pressure.team:T1.shift1.minute" in mid
    # At the end the latest complete window is w03: no shift there, but the count stays.
    late = displays(pressure_shift.run(match, pressure_shift.Params(
        as_of_seq=match.events[-1].seq, team_id="T1", scope="latest")))
    assert late["pressure.team:T1.shifts"] == "1"
    assert not any(k.startswith("pressure.team:T1.shift1.") for k in late)


def test_control_vs_chaos_latest_scope():
    match = build_pressure_match()
    last = _seq_at(match, 1022)  # w03 partial with 122 s of play

    def keys(scope):
        result = control_vs_chaos.run(match, control_vs_chaos.Params(as_of_seq=last,
                                                                      scope=scope))
        return sorted({".".join(f.evidence_id.split(".")[1:3]) for f in result.facts
                       if f.evidence_id.startswith("window.p")})

    assert keys("all") == ["p1.w00", "p1.w01", "p1.w02", "p1.w03"]
    assert keys("latest") == ["p1.w02", "p1.w03"]  # latest complete + current partial


# --- key_moments -----------------------------------------------------------------

def test_key_moments(mini):
    result = key_moments.run(mini, key_moments.Params(as_of_seq=19, limit=5))
    # Candidates: T2's goal (100) and the hardest completed pass, seq 2 (35).
    assert [row[2] for row in result.table.rows] == ["goal", "hardest_pass"]
    d = displays(result)
    assert (d["moment:goal@7.minute"], d["moment:goal@7.scoreline"],
            d["moment:goal@7.chance_quality"]) == ("1'", "0-1", "84")
    assert (d["moment:hardest_pass@2.difficulty"], d["moment:hardest_pass@2.distance_m"]) == (
        "55", "34.0 m")


def test_key_moments_ranks_and_caps():
    match = build_pressure_match()
    result = key_moments.run(match, key_moments.Params(as_of_seq=match.events[-1].seq,
                                                       limit=5))
    kinds = [(row[2], row[3]) for row in result.table.rows]
    # One 49-pass possession from the kickoff (seq 0): 30 + 2 * 39 = 108, capped at 90;
    # then the pressure shift (40).
    assert kinds[0] == ("sequence", 90.0)
    assert ("pressure_shift", 40.0) in kinds
    assert displays(result)["moment:sequence@0.passes"] == "49"


def test_key_moments_limit(mini):
    result = key_moments.run(mini, key_moments.Params(as_of_seq=19, limit=5))
    assert len(result.table.rows) <= 5


# --- player_focus ----------------------------------------------------------------

def test_player_focus_scorer(mini):
    result = player_focus.run(mini, player_focus.Params(as_of_seq=19, player_id="T2-4"))
    d = displays(result)
    assert d["player:T2-4.shirt_number"] == "4"
    assert d["player:T2-4.touches"] == "2"  # shot (seq 7) and pass (seq 18)
    assert (d["player:T2-4.goals"], d["player:T2-4.key_moments"]) == ("1", "1")
    assert d["moment:goal@7.minute"] == "1'"  # the goal's own evidence travels along


def test_player_focus_defender(mini):
    d = displays(player_focus.run(mini, player_focus.Params(as_of_seq=19, player_id="T1-2")))
    assert (d["player:T1-2.tackles"], d["player:T1-2.tackles_won"]) == ("1", "1")
    assert d["player:T1-2.touches"] == "1"  # the possession won at seq 15


def test_player_focus_sees_no_future(mini):
    d = displays(player_focus.run(mini, player_focus.Params(as_of_seq=6, player_id="T2-4")))
    assert (d["player:T2-4.goals"], d["player:T2-4.key_moments"]) == ("0", "0")
