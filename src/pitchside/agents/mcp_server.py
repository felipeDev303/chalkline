"""MCP server exposing the deterministic metric tools for one match.

    uv run python -m pitchside.agents.mcp_server --match data/match_42.jsonl

Tools and their strict JSON schemas come from `metrics/registry.py`; results are
`ToolResult` JSON (also as structured content). The match file is read here, so
metrics/ itself never does I/O.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import anyio
import mcp.types as mt
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from pitchside.agents.tools import run_tool_json
from pitchside.events.match import Match, read_jsonl
from pitchside.metrics.registry import json_schemas

SERVER_NAME = "pitchside-stats"


def build_server(match: Match) -> Server:
    schemas = json_schemas()

    async def list_tools(_ctx: Any, _params: Any) -> mt.ListToolsResult:
        return mt.ListToolsResult(tools=[
            mt.Tool(name=s["name"], description=s["description"], input_schema=s["parameters"])
            for s in schemas
        ])

    async def call_tool(_ctx: Any, params: mt.CallToolRequestParams) -> mt.CallToolResult:
        text = run_tool_json(params.name, match, dict(params.arguments or {}))
        payload = json.loads(text)
        return mt.CallToolResult(
            content=[mt.TextContent(type="text", text=text)],
            structured_content=payload,
            is_error="error" in payload,
        )

    meta = match.metadata
    return Server(
        SERVER_NAME,
        version="1",
        instructions=(
            f"Deterministic football statistics for synthetic match {meta.match_id}: "
            f"{meta.home.name} ({meta.home.team_id}) vs {meta.away.name} ({meta.away.team_id}). "
            "Every tool takes as_of_seq and never sees later events."
        ),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def serve_stdio(match: Match) -> None:
    server = build_server(match)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pitchside.agents.mcp_server")
    parser.add_argument("--match", type=Path, required=True, help="match JSONL file")
    args = parser.parse_args(argv)
    anyio.run(serve_stdio, read_jsonl(args.match))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
