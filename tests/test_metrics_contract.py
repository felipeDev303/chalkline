import pytest
from pydantic import ValidationError

from pitchside.metrics.contract import (
    MAX_TABLE_ROWS,
    Fact,
    Table,
    ToolError,
    ToolParams,
    ToolResult,
    fact,
    format_display,
    minute_display,
    minute_fact,
    round_value,
)


@pytest.mark.parametrize(
    ("value", "unit", "display"),
    [
        (83.6123, "pct", "83.6%"),
        (83.65, "pct", "83.7%"),  # half away from zero, not banker's rounding
        (45.3125, "share", "45%"),
        (54.5, "share", "55%"),
        (1029, "count", "1029"),
        (22.75, "m", "22.8 m"),
        (92.44, "km/h", "92.4 km/h"),
        (-4.25, "per_min", "-4.3/min"),
        (71.5, "score", "72"),
        (3.04, "seconds", "3.0 s"),
    ],
)
def test_format_display(value, unit, display):
    assert format_display(value, unit) == display


def test_fact_stores_the_rounded_value():
    f = fact("pass.team:T1.completion_pct", "Pass completion", 83.6123, "pct")
    assert (f.value, f.display) == (83.6, "83.6%")
    assert fact("summary.team:T1.passes", "Passes", 12.0, "count").value == 12
    assert round_value(2.5, "count") == 3


def test_fact_rejects_display_that_disagrees_with_value():
    with pytest.raises(ValidationError):
        Fact(evidence_id="pass.team:T1.completion_pct", label="x", value=83.6,
             unit="pct", display="84%")
    with pytest.raises(ValidationError):
        Fact(evidence_id="pass.team:T1.completion_pct", label="x", value=83.6123,
             unit="pct", display="83.6%")


def test_text_units():
    assert fact("summary.team:T1.formation", "Formation", "4-3-3", "formation").display == "4-3-3"
    assert fact("summary.scoreline", "Scoreline", "2-1", "scoreline").display == "2-1"
    assert fact("window.p1.w00.state", "State", "chaos", "label").display == "chaos"
    for value, unit in (("4-3", "formation"), ("2-1-0", "scoreline"), ("2-1", "label"),
                        ("top 3", "label")):
        with pytest.raises(ValidationError):
            fact("summary.x", "x", value, unit)


def test_minute_facts():
    assert minute_display(63) == "63'"
    assert minute_display(45, 2) == "45+2'"
    m = minute_fact("moment:goal@412", "Goal minute", 45, 2)
    assert (m.value, m.display) == (47, "45+2'")
    with pytest.raises(ValueError):
        fact("moment:goal@1", "Goal minute", 63, "minute")


def test_evidence_id_pattern():
    with pytest.raises(ValidationError):
        fact("Bad Id", "x", 1, "count")


def _result(*facts, **kw):
    return ToolResult(tool_name="t", params={"as_of_seq": 3}, as_of_seq=3, facts=facts,
                      sample_size=1, method="m", **kw)


def test_tool_result_rejects_duplicate_evidence_ids():
    f = fact("summary.team:T1.goals", "Goals", 1, "count")
    with pytest.raises(ValidationError, match="duplicate evidence ids"):
        _result(f, f)


def test_table_shape_and_size():
    Table(columns=("a", "b"), rows=((1, "x"),))
    with pytest.raises(ValidationError):
        Table(columns=("a", "b"), rows=((1,),))
    with pytest.raises(ValidationError):
        Table(columns=("a",), rows=tuple((i,) for i in range(MAX_TABLE_ROWS + 1)))


def test_params_forbid_extra_fields_and_negative_seq():
    with pytest.raises(ValidationError):
        ToolParams(as_of_seq=1, surprise=True)
    with pytest.raises(ValidationError):
        ToolParams(as_of_seq=-1)


def test_tool_error_carries_code():
    err = ToolError("unknown_team", "no team 'X'")
    assert err.code == "unknown_team"
    assert str(err) == "unknown_team: no team 'X'"
