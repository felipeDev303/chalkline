"""Contract checks over every registered tool on a full simulated match."""

import itertools
import random
import re
import statistics
import time
import typing
from pathlib import Path

import pytest

from pitchside.events.match import Match
from pitchside.metrics.contract import ToolError, ToolResult
from pitchside.metrics.registry import MODULES, TOOLS, call, json_schemas
from pitchside.simulator import simulate_match

METHODS_MD = Path(__file__).resolve().parents[1] / "docs" / "METHODS.md"


@pytest.fixture(scope="module")
def match():
    return simulate_match(42)


def _ids(match: Match) -> dict[str, str]:
    home = match.metadata.home
    return {"team": home.team_id, "player": home.players[9].player_id}


def param_sets(name: str, match: Match, as_of_seq: int) -> list[dict]:
    """Every Literal combination of a tool's params, with ids filled from the match."""
    fields = TOOLS[name].params.model_fields
    choices = {k: typing.get_args(f.annotation) for k, f in fields.items()
               if typing.get_origin(f.annotation) is typing.Literal}
    ids = _ids(match)
    out = []
    for combo in itertools.product(*choices.values()):
        args = dict(zip(choices, combo, strict=True)) | {"as_of_seq": as_of_seq}
        if "subject_id" in fields:
            args["subject_id"] = ids[args["subject"]]
        if "team_id" in fields:
            args["team_id"] = ids["team"]
        if "player_id" in fields:
            args["player_id"] = ids["player"]
        out.append(args)
    return out


@pytest.mark.parametrize("name", list(TOOLS))
def test_every_combination_returns_a_valid_result(name, match):
    last = match.events[-1].seq
    for args in param_sets(name, match, last):
        result = call(name, match, args)
        assert isinstance(result, ToolResult)
        assert result.tool_name == name and result.as_of_seq == last
        assert result.method and result.sample_size >= 0
        assert result.params == TOOLS[name].params.model_validate(args).model_dump()


@pytest.mark.parametrize("name", list(TOOLS))
def test_runtime_under_50_ms(name, match):
    args = param_sets(name, match, match.events[-1].seq)[0]
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        call(name, match, args)
        times.append(time.perf_counter() - t0)
    assert statistics.median(times) < 0.050


@pytest.mark.parametrize("name", list(TOOLS))
def test_no_look_ahead(name, match):
    rng = random.Random(0)
    for n in sorted(rng.sample(range(1, len(match.events) + 1), 25)):
        cut = Match(metadata=match.metadata, events=match.events[:n])
        args = param_sets(name, match, n - 1)[0]
        assert call(name, cut, args) == call(name, match, args), n


@pytest.mark.parametrize("name", list(TOOLS))
def test_deterministic_json(name, match):
    args = param_sets(name, match, match.events[-1].seq)[0]
    assert call(name, match, args).model_dump_json() == call(name, match, args).model_dump_json()


def test_bad_calls_raise_tool_errors(match):
    last = match.events[-1].seq
    with pytest.raises(ToolError) as err:
        call("nope", match, {"as_of_seq": last})
    assert err.value.code == "invalid_params"
    with pytest.raises(ToolError) as err:
        call("pass_profile", match, {"as_of_seq": last, "subject": "squad", "subject_id": "x"})
    assert err.value.code == "invalid_params"
    with pytest.raises(ToolError) as err:
        call("match_summary", match, {"as_of_seq": last + 1})
    assert err.value.code == "as_of_out_of_range"
    with pytest.raises(ToolError) as err:
        call("pressure_shift", match, {"as_of_seq": last, "team_id": "T99"})
    assert err.value.code == "unknown_team"


def test_schemas_are_strict():
    schemas = json_schemas()
    assert [s["name"] for s in schemas] == list(TOOLS)
    for s in schemas:
        params = s["parameters"]
        assert s["strict"] is True and s["description"]
        assert params["type"] == "object" and params["additionalProperties"] is False
        assert params["required"] == list(params["properties"])
        assert "as_of_seq" in params["properties"]
    by_name = {s["name"]: s["parameters"]["properties"] for s in schemas}
    assert by_name["pass_profile"]["subject"]["enum"] == ["team", "player"]
    assert by_name["key_moments"]["limit"]["enum"] == [5, 10, 20]


def _section(text: str, tool: str) -> str:
    m = re.search(rf"^### `{tool}`$(.*?)(?=^### |\Z)", text, re.M | re.S)
    assert m, f"METHODS.md has no section for {tool}"
    return m.group(1)


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.TOOL_NAME)
def test_methods_doc_lists_every_threshold(module):
    section = _section(METHODS_MD.read_text(encoding="utf-8"), module.TOOL_NAME)
    for key, value in module.THRESHOLDS.items():
        m = re.search(rf"`{key}` = ([-\d.]+)", section)
        assert m, f"{module.TOOL_NAME}: `{key}` not documented"
        assert float(m.group(1)) == value, f"{module.TOOL_NAME}: `{key}` is {value} in code"
