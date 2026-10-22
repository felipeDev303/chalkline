"""All metric tools, by name, plus strict JSON schemas for function calling."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import ValidationError

from pitchside.events.match import Match
from pitchside.metrics import (
    control_vs_chaos,
    expected_threat,
    key_moments,
    match_summary,
    off_ball,
    pass_profile,
    player_focus,
    pressure_shift,
    shot_profile,
)
from pitchside.metrics.contract import ToolError, ToolResult, ToolSpec

MODULES = (match_summary, pass_profile, shot_profile, expected_threat, off_ball,
           control_vs_chaos, pressure_shift, key_moments, player_focus)
TOOLS: dict[str, ToolSpec] = {
    m.TOOL_NAME: ToolSpec(name=m.TOOL_NAME, description=m.DESCRIPTION, params=m.Params,
                          run=m.run)
    for m in MODULES
}


def _strict(node: Any) -> Any:
    """Strict mode: every object closed and every property required."""
    if isinstance(node, dict):
        node = {k: _strict(v) for k, v in node.items() if k != "title"}
        if node.get("type") == "object":
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}))
        return node
    if isinstance(node, list):
        return [_strict(v) for v in node]
    return node


def json_schema(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.description,
        "parameters": _strict(copy.deepcopy(spec.params.model_json_schema())),
        "strict": True,
    }


def json_schemas() -> list[dict[str, Any]]:
    return [json_schema(spec) for spec in TOOLS.values()]


def call(name: str, match: Match, arguments: dict[str, Any]) -> ToolResult:
    """Run a tool from a model's function call; bad calls raise ToolError."""
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError("invalid_params", f"no tool {name!r}; tools: {', '.join(TOOLS)}")
    try:
        params = spec.params.model_validate(arguments)
    except ValidationError as err:
        raise ToolError("invalid_params", str(err)) from err
    return spec.run(match, params)
