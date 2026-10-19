import hashlib
from itertools import pairwise
from statistics import fmean

import pytest

from pitchside.events.match import attacks_high_x, read_jsonl, to_jsonl_bytes, write_jsonl
from pitchside.events.schema import MatchEventAdapter, MatchMetadata
from pitchside.simulator import simulate_match
from pitchside.simulator.__main__ import main
from pitchside.simulator.realism import CALIBRATION_SEEDS, TARGETS, summarize

# Update deliberately when the simulator's output changes, and rerun
# scripts/calibrate.py so docs/data/CALIBRATION.md matches.
GOLDEN_SEED_42_SHA256 = "35a49ad3f413c2500cfe0f9f83eed143392757e5bc78c380f46316cf01e68dbf"


@pytest.fixture(scope="module")
def match42():
    return simulate_match(42)


@pytest.fixture(scope="module")
def calibration_summaries():
    return [summarize(simulate_match(seed).events) for seed in CALIBRATION_SEEDS]


# --- determinism -------------------------------------------------------------

def test_same_seed_is_byte_identical(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl(simulate_match(7), a)
    write_jsonl(simulate_match(7), b)
    assert a.read_bytes() == b.read_bytes()


def test_different_seeds_differ():
    assert to_jsonl_bytes(simulate_match(7)) != to_jsonl_bytes(simulate_match(8))


def test_output_uses_lf_line_endings(tmp_path, match42):
    path = tmp_path / "m.jsonl"
    write_jsonl(match42, path)
    assert b"\r" not in path.read_bytes()


def test_golden_sha256_seed_42(tmp_path, match42):
    """Cross-OS reproducibility: CI on Linux must reproduce the hash made on Windows."""
    path = tmp_path / "m.jsonl"
    write_jsonl(match42, path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == GOLDEN_SEED_42_SHA256


# --- validity ----------------------------------------------------------------

def test_every_line_validates_and_roundtrips(tmp_path, match42):
    path = tmp_path / "m.jsonl"
    write_jsonl(match42, path)
    first, *rest = path.read_bytes().splitlines()
    MatchMetadata.model_validate_json(first)
    for line in rest:
        MatchEventAdapter.validate_json(line)
    assert read_jsonl(path) == match42


def test_metadata_is_synthetic_with_full_squads(match42):
    meta = match42.metadata
    assert meta.synthetic is True
    assert meta.seed == 42
    assert meta.home.team_id != meta.away.team_id
    for team in (meta.home, meta.away):
        assert len(team.players) == 11
        assert len({p.shirt_number for p in team.players}) == 11
        assert len({p.name for p in team.players}) == 11
        assert [p.position for p in team.players].count("GK") == 1


def test_rosters_are_stable_across_matches():
    squads = {}
    for seed in range(10):
        meta = simulate_match(seed).metadata
        for team in (meta.home, meta.away):
            assert squads.setdefault(team.team_id, team) == team


def test_shots_go_towards_the_declared_goal():
    """The metadata's attacking direction must agree with where teams actually shoot."""
    for seed in range(5):
        match = simulate_match(seed)
        for e in match.events:
            if e.type == "shot":
                high = attacks_high_x(match.metadata, e.team_id, e.period)
                assert (e.location.x > 52.5) == high, e.event_id


def test_event_ids_are_unique(match42):
    ids = [e.event_id for e in match42.events]
    assert len(set(ids)) == len(ids)


# --- ordering ----------------------------------------------------------------

def test_seq_and_clock_are_monotonic(match42):
    events = match42.events
    assert [e.seq for e in events] == list(range(len(events)))
    for prev, cur in pairwise(events):
        assert cur.period >= prev.period
        if cur.period == prev.period:
            assert cur.clock_s >= prev.clock_s


def test_phase_structure(match42):
    events = match42.events
    assert events[0].type == "phase" and events[0].phase == "kickoff"
    assert events[-1].type == "phase" and events[-1].phase == "full_time"
    phases = [(e.period, e.phase) for e in events if e.type == "phase"]
    assert phases.count((1, "half_time")) == 1
    assert phases.count((2, "full_time")) == 1
    half_time = next(
        i for i, e in enumerate(events) if e.type == "phase" and e.phase == "half_time"
    )
    assert all(e.period == 1 for e in events[: half_time + 1])
    assert all(e.period == 2 for e in events[half_time + 1 :])
    assert events[half_time + 1].type == "phase" and events[half_time + 1].phase == "kickoff"
    goals = sum(1 for e in events if e.type == "shot" and e.outcome == "goal")
    assert sum(1 for _, phase in phases if phase == "kickoff") == 2 + goals


# --- referential integrity ---------------------------------------------------

def test_player_and_team_references(match42):
    meta = match42.metadata
    roster = {t.team_id: {p.player_id for p in t.players} for t in (meta.home, meta.away)}
    for e in match42.events:
        own = roster[e.team_id]
        (other_id,) = set(roster) - {e.team_id}
        other = roster[other_id]
        if e.type == "phase":
            assert e.player_id is None
            continue
        assert e.player_id in own
        if e.type == "pass" and e.recipient_id is not None:
            assert e.recipient_id in own and e.recipient_id != e.player_id
        elif e.type == "tackle":
            assert e.opponent_id in other
        elif e.type == "pressure":
            assert e.target_player_id in other
        elif e.type == "possession_change":
            assert e.from_team_id == other_id


# --- realism -----------------------------------------------------------------

@pytest.mark.parametrize("metric", sorted(TARGETS))
def test_realism_target_over_calibration_seeds(metric, calibration_summaries):
    mean = fmean(s[metric] for s in calibration_summaries)
    lo, hi = TARGETS[metric]
    assert lo <= mean <= hi, f"{metric} mean {mean:.3f} outside [{lo}, {hi}]"


# --- CLI ---------------------------------------------------------------------

def test_cli_writes_readable_match(tmp_path, capsys):
    out = tmp_path / "nested" / "match_3.jsonl"
    assert main(["--seed", "3", "--out", str(out)]) == 0
    assert read_jsonl(out).metadata.seed == 3
    assert str(out) in capsys.readouterr().out


def test_cli_rejects_negative_seed():
    with pytest.raises(SystemExit):
        main(["--seed", "-1"])
