"""The metric tools as agent tools, and recovery of their results from a run.

Both transports return a `ToolResult` as JSON: in-process function tools (tests,
the API process) and the MCP server (`agents/mcp_server.py`). A `ToolError` comes
back as `{"error": code, "message": ...}` so the model can fix its call.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import agent_framework as af
from pydantic import ValidationError

from pitchside.events.match import Match
from pitchside.metrics.contract import ToolError, ToolResult
from pitchside.metrics.registry import TOOLS, call


def run_tool_json(name: str, match: Match, arguments: dict[str, Any]) -> str:
    """Run one metric tool; a ToolResult or a structured error, as JSON."""
    try:
        return call(name, match, arguments).model_dump_json()
    except ToolError as err:
        return json.dumps({"error": err.code, "message": err.message})


def local_tools(match: Match) -> list[af.FunctionTool]:
    """Every registered metric tool as an Agent Framework function tool."""
    tools = []
    for spec in TOOLS.values():
        def run(*, _name: str = spec.name, **kwargs: Any) -> str:
            return run_tool_json(_name, match, kwargs)
        tools.append(af.tool(run, name=spec.name, description=spec.description,
                             schema=spec.params))
    return tools


def _as_text(result: Any) -> str | None:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result)
    if isinstance(result, list):  # list of Content from MCP
        texts = [getattr(c, "text", None) for c in result]
        return next((t for t in texts if t), None)
    return getattr(result, "text", None)


def extract_tool_results(messages: Iterable[af.Message]) -> list[ToolResult]:
    """ToolResults returned to the model during a run, in call order (errors skipped)."""
    out = []
    for message in messages:
        for content in message.contents:
            if content.type != "function_result":
                continue
            text = _as_text(content.result)
            if text is None:
                continue
            try:
                out.append(ToolResult.model_validate_json(text))
            except ValidationError:
                continue  # a structured error the model was told about
    return out
