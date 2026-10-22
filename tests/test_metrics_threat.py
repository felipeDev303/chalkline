"""Expected threat: zones, pass values and the tool, against the fitted grid."""

import pytest
from mini_match import build_mini_match

from pitchside.metrics import expected_threat as xt
from pitchside.metrics._xt_grid import XT


@pytest.fixture(scope="module")
def mini():
    return build_mini_match()


def test_grid_shape_and_direction():
    assert len(XT) == xt.GRID_X and all(len(col) == xt.GRID_Y for col in XT)
    assert all(0.0 <= v <= 1.0 for col in XT for v in col)
    # Attacking zones are worth more: the column in front of goal beats our own third.
    assert max(XT[-1]) > max(XT[0]) * 3


@pytest.mark.parametrize(("point", "zone"), [
    ((0.0, 0.0), 0), ((104.99, 67.99), 95), ((105.0, 68.0), 95), ((45.0, 34.0), 5 * 8 + 4),
])
def test_zone_of(point, zone):
    assert xt.zone_of(point) == zone


def test_pass_threat_by_hand(mini):
    meta = mini.metadata
    p2, p4 = mini.events[2], mini.events[4]
    # p2: (45, 34) -> (75, 50) for T1, which attacks x = 105: zones (5, 4) -> (8, 5)
    assert xt.pass_threat(meta, p2) == pytest.approx(XT[8][5] - XT[5][4])
    assert xt.pass_threat(meta, p4) is None  # incomplete passes are not credited


def test_threat_profile_tool(mini):
    result = xt.run(mini, xt.Params(as_of_seq=19, subject="team", subject_id="T1"))
    d = {f.evidence_id: f for f in result.facts}
    # T1 completed seqs 1, 2 and 10
    assert d["threat.team:T1.passes_valued"].value == 3
    expected = sum(xt.pass_threat(mini.metadata, mini.events[s]) for s in (1, 2, 10))
    assert d["threat.team:T1.added"].value == pytest.approx(round(expected, 2))
    assert d["threat.team:T1.top1.minute"].display == "1'"  # p2, the forward pass
