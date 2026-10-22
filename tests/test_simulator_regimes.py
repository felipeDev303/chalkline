import pytest

from pitchside.simulator import DEFAULT_PARAMS, simulate_match_with_truth
from pitchside.simulator.__main__ import main
from pitchside.simulator.regimes import is_control, plan_spells, read_truth


@pytest.mark.parametrize("seed", [0, 5, 10])
def test_control_group_has_nothing_planted(seed):
    _, truth = simulate_match_with_truth(seed)
    assert truth.control_group
    assert truth.changes == () and truth.high_pressure_spans == () and truth.runs == ()


def test_treated_matches_plant_all_three_kinds_of_run():
    kinds = set()
    for seed in (1, 2, 3):
        _, truth = simulate_match_with_truth(seed)
        assert not truth.control_group and truth.runs
        for r in truth.runs:
            assert r.effective == (r.kind == "decoy" or not r.tracked)
            assert r.kind == "direct" or r.beneficiary_id != r.player_id
            kinds.add((r.kind, r.tracked))
    assert kinds == {("direct", False), ("direct", True), ("decoy", True)}


def test_frames_carry_every_player_and_the_carrier_on_the_ball():
    match, _ = simulate_match_with_truth(3)
    roster = {p.player_id for t in (match.metadata.home, match.metadata.away) for p in t.players}
    for e in match.events:
        assert e.frame is not None and {p.player_id for p in e.frame.players} == roster
        if e.type == "pass":
            carrier = next(p for p in e.frame.players if p.player_id == e.player_id)
            assert (carrier.x, carrier.y) == (e.location.x, e.location.y)


def test_control_group_is_one_seed_in_five():
    assert sum(is_control(s, DEFAULT_PARAMS) for s in range(100)) == 20


def test_spells_are_well_formed():
    p = DEFAULT_PARAMS
    for seed in range(1, 60):
        if is_control(seed, p):
            continue
        for spells in plan_spells(seed, p):
            assert p.spells_per_team[0] <= len(spells) <= p.spells_per_team[1]
            for s in spells:
                assert p.spell_start_s[0] <= s.start_s < s.end_s <= p.spell_latest_end_s
                assert s.factor > 1.0 or s.factor < 1.0
            for a, b in zip(spells, spells[1:], strict=False):
                assert a.period != b.period or b.start_s >= a.end_s + p.spell_min_gap_s


def test_truth_records_spells_and_trailing():
    causes = set()
    for seed in range(1, 40):
        match, truth = simulate_match_with_truth(seed)
        team_ids = {match.metadata.home.team_id, match.metadata.away.team_id}
        for c in truth.changes:
            assert c.team_id in team_ids
            assert (c.direction == "up") == (c.magnitude > 1)
            if c.cause in ("trailing", "trailing_end"):
                assert c.period == 2 and c.clock_s >= DEFAULT_PARAMS.trailing_from_s
            causes.add(c.cause)
        for span in truth.high_pressure_spans:
            assert span.factor > 1.0
    assert causes == {"planned_press", "planned_drop", "spell_end", "trailing", "trailing_end"}


def test_truth_is_deterministic():
    assert simulate_match_with_truth(7)[1] == simulate_match_with_truth(7)[1]


def test_cli_writes_truth_sidecar(tmp_path):
    out = tmp_path / "match_7.jsonl"
    assert main(["--seed", "7", "--out", str(out)]) == 0
    truth = read_truth(tmp_path / "match_7.truth.json")
    assert truth == simulate_match_with_truth(7)[1]
    assert b"\r" not in (tmp_path / "match_7.truth.json").read_bytes()
