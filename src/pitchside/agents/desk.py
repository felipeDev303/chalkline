"""The broadcast desk: analyst -> narrator -> verifier, as an Agent Framework workflow.

    analyst ──> narrator ──> verifier ──> Insight
                   ^             │
                   └── retry ────┘  (once, with the verifier's feedback)

Failure recovery, in order:
- a model call fails -> the same step is retried on the next model of the chain;
- the analyst gets a tool error -> it sees the error and may fix its call;
- the analyst returns no usable results -> a deterministic default set of tools;
- the narrative fails verification twice, or no model answers -> evidence only:
  no narrative is published, the facts are (CLAUDE.md: one retry, then evidence).

Tools see a match cut at the request's as_of_seq, so look-ahead is impossible by
construction, whatever as_of_seq the model asks for.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import agent_framework as af

from pitchside.agents.clients import ModelChain
from pitchside.agents.contracts import Insight, Narrative, TurnRequest, Verdict
from pitchside.agents.prompts import (
    ANALYST_INSTRUCTIONS,
    NARRATOR_INSTRUCTIONS,
    analyst_prompt,
    narrator_prompt,
)
from pitchside.agents.tools import extract_tool_results, local_tools
from pitchside.agents.verifier import verify
from pitchside.events.match import Match
from pitchside.metrics.contract import Fact, ToolResult
from pitchside.metrics.registry import call

MAX_ATTEMPTS = 2  # the first narrative plus one retry
EVIDENCE_ONLY_FACTS = 12

ToolsFactory = Callable[[Match], Sequence[Any]]


class ModelChainExhausted(RuntimeError):
    pass


async def run_on_chain(models: ModelChain, build: Callable[[Any], af.Agent], prompt: str,
                       **run_kwargs: Any) -> tuple[str, af.AgentResponse]:
    """Run an agent on the first model of the chain that answers."""
    errors = []
    for label, client in models:
        try:
            return label, await build(client).run(prompt, **run_kwargs)
        except Exception as err:  # noqa: BLE001 - any model failure moves down the chain
            errors.append(f"{label}: {type(err).__name__}: {err}")
    raise ModelChainExhausted("; ".join(errors) or "no model configured")


def default_results(match: Match, as_of_seq: int) -> list[ToolResult]:
    """Deterministic evidence when the analyst produced none."""
    return [call("match_summary", match, {"as_of_seq": as_of_seq}),
            call("key_moments", match, {"as_of_seq": as_of_seq, "limit": 5})]


def cut(match: Match, as_of_seq: int) -> Match:
    return Match(metadata=match.metadata,
                 events=tuple(e for e in match.events if e.seq <= as_of_seq))


# --- messages between executors -------------------------------------------------

@dataclass(frozen=True)
class Analysis:
    request: TurnRequest
    results: tuple[ToolResult, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Draft:
    analysis: Analysis
    narrative: Narrative
    model: str
    attempt: int


@dataclass(frozen=True)
class Retry:
    draft: Draft
    verdict: Verdict


def evidence_only(analysis: Analysis, attempts: int, failure: str) -> Insight:
    facts: list[Fact] = [f for r in analysis.results for f in r.facts][:EVIDENCE_ONLY_FACTS]
    return Insight(request=analysis.request, status="evidence_only", sentences=(),
                   evidence=tuple(facts), results=analysis.results, attempts=attempts,
                   failure=failure, notes=analysis.notes)


# --- executors -------------------------------------------------------------------

class AnalystExecutor(af.Executor):
    def __init__(self, match: Match, models: ModelChain, tools: ToolsFactory) -> None:
        super().__init__(id="analyst")
        self.match, self.models, self.tools = match, models, tools

    @af.handler
    async def analyse(self, request: TurnRequest, ctx: af.WorkflowContext[Analysis]) -> None:
        visible = cut(self.match, request.as_of_seq)
        notes: list[str] = []
        results: list[ToolResult] = []
        try:
            label, response = await run_on_chain(
                self.models,
                lambda client: af.Agent(client, ANALYST_INSTRUCTIONS, name="analyst",
                                        tools=list(self.tools(visible))),
                analyst_prompt(request, self.match.metadata),
            )
            if label != self.models[0][0]:
                notes.append(f"analyst ran on fallback model '{label}'")
            results = [r for r in extract_tool_results(response.messages)
                       if r.as_of_seq == request.as_of_seq]
        except ModelChainExhausted as err:
            notes.append(f"analyst model unavailable: {err}")
        if not results:
            notes.append("analyst returned no usable results; using default evidence")
            results = default_results(visible, request.as_of_seq)
        unique = {r.model_dump_json(): r for r in results}  # drop identical repeat calls
        await ctx.send_message(Analysis(request, tuple(unique.values()), tuple(notes)))


class NarratorExecutor(af.Executor):
    def __init__(self, match: Match, models: ModelChain) -> None:
        super().__init__(id="narrator")
        self.match, self.models = match, models

    async def _write(self, analysis: Analysis, attempt: int, feedback: Sequence[str],
                     ctx: af.WorkflowContext[Draft, Insight]) -> None:
        prompt = narrator_prompt(analysis.request, self.match.metadata, analysis.results,
                                 feedback)
        try:
            label, response = await run_on_chain(
                self.models,
                lambda client: af.Agent(client, NARRATOR_INSTRUCTIONS, name="narrator"),
                prompt, options={"response_format": Narrative},
            )
            narrative = response.value
            if not isinstance(narrative, Narrative):
                narrative = Narrative.model_validate_json(response.text)
        except Exception as err:  # noqa: BLE001 - chain exhausted or unparseable output
            await ctx.yield_output(evidence_only(
                analysis, attempt, f"narrator unavailable: {type(err).__name__}: {err}"))
            return
        note = f"narrator ran on fallback model '{label}'"
        if label != self.models[0][0] and note not in analysis.notes:
            analysis = Analysis(analysis.request, analysis.results, (*analysis.notes, note))
        await ctx.send_message(Draft(analysis, narrative, label, attempt))

    @af.handler
    async def first(self, analysis: Analysis, ctx: af.WorkflowContext[Draft, Insight]) -> None:
        await self._write(analysis, 1, (), ctx)

    @af.handler
    async def again(self, retry: Retry, ctx: af.WorkflowContext[Draft, Insight]) -> None:
        analysis = retry.draft.analysis
        rejected = (f"verifier rejected attempt {retry.draft.attempt}: "
                    + " | ".join(retry.verdict.feedback))
        analysis = Analysis(analysis.request, analysis.results, (*analysis.notes, rejected))
        await self._write(analysis, retry.draft.attempt + 1, retry.verdict.feedback, ctx)


class VerifierExecutor(af.Executor):
    def __init__(self, match: Match) -> None:
        super().__init__(id="verifier")
        self.match = match

    @af.handler
    async def check(self, draft: Draft, ctx: af.WorkflowContext[Retry, Insight]) -> None:
        analysis = draft.analysis
        verdict = verify(draft.narrative, analysis.results, analysis.request.language,
                         self.match.metadata)
        if verdict.ok:
            facts = {f.evidence_id: f for r in analysis.results for f in r.facts}
            cited = dict.fromkeys(eid for c in verdict.checks for eid in c.evidence_ids)
            await ctx.yield_output(Insight(
                request=analysis.request,
                status="verified" if draft.attempt == 1 else "verified_after_retry",
                sentences=verdict.checks,
                evidence=tuple(facts[eid] for eid in cited),
                results=analysis.results,
                attempts=draft.attempt,
                model=draft.model,
                notes=analysis.notes,
            ))
        elif draft.attempt < MAX_ATTEMPTS:
            await ctx.send_message(Retry(draft, verdict), target_id="narrator")
        else:
            await ctx.yield_output(evidence_only(
                analysis, draft.attempt,
                "narrative failed verification twice: " + " | ".join(verdict.feedback)))


@dataclass
class Desk:
    """One match, one model chain; `await desk.run(request)` -> Insight."""

    match: Match
    models: ModelChain
    tools: ToolsFactory = field(default=local_tools)

    def workflow(self) -> af.Workflow:
        analyst = AnalystExecutor(self.match, self.models, self.tools)
        narrator = NarratorExecutor(self.match, self.models)
        verifier = VerifierExecutor(self.match)
        return (af.WorkflowBuilder(start_executor=analyst, name="pitchside-desk")
                .add_edge(analyst, narrator)
                .add_edge(narrator, verifier)
                .add_edge(verifier, narrator)
                .build())

    async def run(self, request: TurnRequest) -> Insight:
        outputs = (await self.workflow().run(request)).get_outputs()
        insights = [o for o in outputs if isinstance(o, Insight)]
        if len(insights) != 1:
            raise RuntimeError(f"desk produced {len(insights)} insights")
        return insights[0]
