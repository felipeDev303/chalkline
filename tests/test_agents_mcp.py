"""The MCP server, end to end over stdio, against the hand-built mini match."""

import json
import sys

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mini_match import build_mini_match

from pitchside.events.match import write_jsonl
from pitchside.metrics.contract import ToolResult
from pitchside.metrics.registry import TOOLS, call


@pytest.fixture(scope="module")
def match_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("mcp") / "mini.jsonl"
    write_jsonl(build_mini_match(), path)
    return path


async def _session_run(match_file, fn):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pitchside.agents.mcp_server", "--match", str(match_file)],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await fn(session)


def test_lists_every_registered_tool_with_strict_schema(match_file):
    async def go(session):
        return (await session.list_tools()).tools
    tools = anyio.run(_session_run, match_file, go)
    assert [t.name for t in tools] == list(TOOLS)
    for t in tools:
        assert t.input_schema["additionalProperties"] is False
        assert "as_of_seq" in t.input_schema["required"]


def test_call_returns_the_same_tool_result_as_the_registry(match_file):
    async def go(session):
        return await session.call_tool("match_summary", {"as_of_seq": 19})
    result = anyio.run(_session_run, match_file, go)
    assert not result.is_error
    via_mcp = ToolResult.model_validate_json(result.content[0].text)
    assert via_mcp == call("match_summary", build_mini_match(), {"as_of_seq": 19})


def test_tool_errors_come_back_as_errors(match_file):
    async def go(session):
        return await session.call_tool("pressure_shift",
                                       {"as_of_seq": 19, "team_id": "T9", "scope": "all"})
    result = anyio.run(_session_run, match_file, go)
    assert result.is_error
    assert json.loads(result.content[0].text)["error"] == "unknown_team"
