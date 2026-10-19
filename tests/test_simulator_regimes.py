import hashlib

import pytest

from pitchside.events.match import to_jsonl_bytes
from pitchside.simulator import DEFAULT_PARAMS, simulate_match_with_truth
from pitchside.simulator.__main__ import main
from pitchside.simulator.regimes import is_control, plan_spells, read_truth

# Event streams of control seeds before regimes existed (schema 0.2.0, commit 8e5e14c).
# Regimes draw from their own random stream, so the control group must be unchanged.
CONTROL_V1_SHA256 = {
    0: "6442d7b083a56d0f0bf54405486db245f08feb9f7d6a08f23c363b450d4d8236",
    5: "0da9845ccb5e82da8c933d34e892069b94f489e7ac643816585ae438f1e668e9",
    10: "c2c2599a7e420de6aa17ea525f79f96ad5661bc5aa0badfebc006ac50e56f265",
}


@pytest.mark.parametrize("seed", sorted(CONTROL_V1_SHA256))
def test_control_group_matches_simulator_without_regimes(seed):
    match, truth = simulate_match_with_truth(seed)
    assert truth.control_group and truth.changes == () and truth.high_pressure_spans == ()
    assert hashlib.sha256(to_jsonl_bytes(match)).hexdigest() == CONTROL_V1_SHA256[seed]


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
