"""Single-agent baseline for the ablation: one agent calls the tools and writes.

Same tools, model, prompts and structured output as the desk; the difference is
that one agent does both jobs in one conversation. `verify_and_retry=False` is a
plain tool-using assistant (whatever it writes would air); `True` adds the same
deterministic verifier and one retry in the same conversation, which isolates
what the role split itself adds.
"""

from __future__ import annotations

import agent_framework as af

from pitchside.agents.clients import ModelChain
from pitchside.agents.contracts import Insight, Narrative, TurnRequest
from pitchside.agents.desk import ModelChainExhausted, cut, tokens_used
from pitchside.agents.prompts import (
    ANALYST_INSTRUCTIONS,
    LANGUAGE_GUIDE,
    NARRATOR_INSTRUCTIONS,
    PERSONA_GUIDE,
    analyst_prompt,
)
from pitchside.agents.tools import extract_tool_results, local_tools
from pitchside.agents.verifier import verify
from pitchside.events.match import Match
from pitchside.metrics.contract import ToolResult

SOLO_INSTRUCTIONS = (
    ANALYST_INSTRUCTIONS.replace("reply with the single word: done",
                                 "write the narrative as instructed below")
    + "\n\n" + NARRATOR_INSTRUCTIONS.replace("Use only the facts provided",
                                             "Use only the facts returned by your tools")
)


def _results(responses: list[af.AgentResponse], as_of_seq: int) -> tuple[ToolResult, ...]:
    found = [r for resp in responses for r in extract_tool_results(resp.messages)
             if r.as_of_seq == as_of_seq]
    return tuple({r.model_dump_json(): r for r in found}.values())


async def run_solo(match: Match, models: ModelChain, request: TurnRequest,
                   *, verify_and_retry: bool) -> Insight:
    tools = local_tools(cut(match, request.as_of_seq))
    prompt = "\n\n".join([analyst_prompt(request, match.metadata),
                          PERSONA_GUIDE[request.persona], LANGUAGE_GUIDE[request.language]])
    responses: list[af.AgentResponse] = []
    used_model = None
    for label, client in models:
        agent = af.Agent(client, SOLO_INSTRUCTIONS, name="solo", tools=tools)
        session = agent.create_session()
        try:
            responses.append(await agent.run(prompt, session=session,
                                             options={"response_format": Narrative}))
            used_model = label
            break
        except Exception:  # noqa: BLE001 - next model in the chain
            continue
    else:
        raise ModelChainExhausted("no model answered")

    def narrative_of(response: af.AgentResponse) -> Narrative:
        value = response.value
        return value if isinstance(value, Narrative) else Narrative.model_validate_json(
            response.text)

    attempts, notes = 1, []
    try:
        narrative = narrative_of(responses[-1])
    except Exception as err:  # noqa: BLE001 - unparseable output counts as a failure
        narrative, notes = Narrative(sentences=()), [f"unparseable output: {err}"]
    verdict = verify(narrative, _results(responses, request.as_of_seq), request.language,
                     match.metadata)
    if not verdict.ok and verify_and_retry:
        attempts = 2
        notes.append("verifier rejected attempt 1: " + " | ".join(verdict.feedback))
        feedback = ("Your narrative failed verification. Fix exactly these problems and "
                    "return the corrected JSON:\n- " + "\n- ".join(verdict.feedback))
        try:
            responses.append(await agent.run(feedback, session=session,
                                             options={"response_format": Narrative}))
            narrative = narrative_of(responses[-1])
        except Exception as err:  # noqa: BLE001
            narrative = Narrative(sentences=())
            notes.append(f"retry failed: {err}")
        verdict = verify(narrative, _results(responses, request.as_of_seq),
                         request.language, match.metadata)

    results = _results(responses, request.as_of_seq)
    facts = {f.evidence_id: f for r in results for f in r.facts}
    published = verdict.ok or not verify_and_retry  # without a verifier, everything airs
    status = ("verified" if verdict.ok and attempts == 1
              else "verified_after_retry" if verdict.ok else
              "evidence_only" if verify_and_retry else "unverified")
    cited = dict.fromkeys(eid for c in verdict.checks for eid in c.evidence_ids if eid in facts)
    return Insight(
        request=request, status=status,
        sentences=verdict.checks if published else (),
        evidence=tuple(facts[eid] for eid in cited),
        results=results, attempts=attempts, model=used_model,
        failure=None if verdict.ok else " | ".join(verdict.feedback) or "no narrative",
        notes=tuple(notes), tokens=sum(tokens_used(r) for r in responses),
    )
