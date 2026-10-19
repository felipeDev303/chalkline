import pytest
from pydantic import ValidationError

from pitchside.events.schema import MatchEventAdapter, Pass, Point


def _base(**kw):
    return {
        "event_id": "e1", "match_id": "m1", "seq": 0, "period": 1, "clock_s": 12.5,
        "team_id": "T1", "player_id": "P1", "location": {"x": 50, "y": 34},
    } | kw


def test_pass_roundtrip_json():
    raw = _base(type="pass", end_location={"x": 70, "y": 20}, recipient_id="P2",
                duration_s=1.2, outcome="complete", height="ground", under_pressure=False)
    ev = MatchEventAdapter.validate_python(raw)
    assert isinstance(ev, Pass)
    assert MatchEventAdapter.validate_json(MatchEventAdapter.dump_json(ev)) == ev


def test_rejects_off_pitch_point():
    with pytest.raises(ValidationError):
        Point(x=120, y=10)


def test_rejects_unknown_fields():
    raw = _base(type="tackle", opponent_id="P9", won=True, xg=0.3)
    with pytest.raises(ValidationError):
        MatchEventAdapter.validate_python(raw)
