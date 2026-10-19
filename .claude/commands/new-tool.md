Create a new deterministic metric tool for: $ARGUMENTS

1. Module in src/pitchside/metrics/ with TOOL_NAME, DESCRIPTION (what the model reads
   to choose it), a pydantic Params model (extra="forbid", Literal for choices),
   and run(events, params) -> ToolResult.
2. Return aggregates only: facts with stable evidence IDs (e.g. `pass.difficulty.p90`),
   sample size, method, caveats, and what the data can't tell.
3. Test in tests/ with a tiny hand-built event fixture and values computed by hand.
4. Run `uv run pytest -q` and `uv run ruff check .` and report.

Show me the plan and proposed evidence IDs before writing code.
