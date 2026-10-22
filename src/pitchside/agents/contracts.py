"""What flows between the agents of one turn, and what a turn produces."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from pitchside.metrics.contract import Fact, ToolResult

Persona = Literal["casual", "analyst"]
Language = Literal["en", "es"]
TurnKind = Literal["moment", "recap", "question"]
# "unverified" only occurs in the single-agent ablation baseline without a verifier.
Status = Literal["verified", "verified_after_retry", "evidence_only", "unverified"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TurnRequest(_Strict):
    """One request to the desk: explain the match as of `as_of_seq`."""

    as_of_seq: Annotated[int, Field(ge=0)]
    kind: TurnKind
    persona: Persona
    language: Language
    question: str | None = None  # for kind == "question"


# --- narrator output (structured) ----------------------------------------------

class Sentence(_Strict):
    text: str
    evidence_ids: tuple[str, ...] = Field(
        default=(),
        description="ids of the facts this sentence uses; every number must come from them",
    )


class Narrative(_Strict):
    sentences: tuple[Sentence, ...]


# --- verifier output -----------------------------------------------------------

class SentenceCheck(_Strict):
    text: str
    evidence_ids: tuple[str, ...]
    kind: Literal["claim", "interpretation"]  # interpretation: no numbers, no citations
    ok: bool
    problems: tuple[str, ...] = ()


class Verdict(_Strict):
    ok: bool
    checks: tuple[SentenceCheck, ...]
    feedback: tuple[str, ...] = ()


# --- turn output ---------------------------------------------------------------

class Insight(_Strict):
    """What the desk publishes for one turn.

    `sentences` is empty when status is `evidence_only`: the narrative failed
    verification twice (or no model was reachable), so only evidence is shown.
    """

    request: TurnRequest
    status: Status
    sentences: tuple[SentenceCheck, ...]
    evidence: tuple[Fact, ...]  # facts cited by published sentences, or the fallback evidence
    results: tuple[ToolResult, ...]  # every tool result of the turn (for the evidence panel)
    attempts: int
    model: str | None = None  # which deployment wrote the narrative, if any
    failure: str | None = None  # why the turn fell back to evidence only
    notes: tuple[str, ...] = ()  # recoveries on the way (fallback model, default evidence)
    tokens: int = 0  # model tokens spent on the turn, all agents and attempts
