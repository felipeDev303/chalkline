"""Instructions and per-turn prompts for the analyst and the narrator."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pitchside.agents.contracts import TurnRequest
from pitchside.events.schema import MatchMetadata
from pitchside.metrics.contract import ToolResult

MAX_FACTS_FOR_NARRATOR = 150

ANALYST_INSTRUCTIONS = """\
You are the analyst on a football broadcast desk. You never compute numbers yourself:
deterministic statistics tools do. For each request, call the 2-4 tools that best
explain it, always with the as_of_seq you are given, and prefer scope "latest" for
live moments. If a tool returns an error, fix the call (an id or a parameter) once.
When you have the results, reply with the single word: done."""

NARRATOR_INSTRUCTIONS = """\
You are the narrator on a football broadcast desk. You turn statistics facts into a
short, vivid explanation of why the moment matters, for one audience and language.
Rules you must follow:
- Use only the facts provided. Every number you write must be one fact's display
  value, written with digits (never as words), in the requested language's format.
- For every sentence, list in evidence_ids the ids of ALL the facts it uses,
  including the minute and the scoreline. A number must come from a fact the same
  sentence cites. Use at most 2 numbers per sentence.
- Never count or compute anything yourself ("two chances", "both goals", a
  difference or a total): if no fact gives the number, leave it out.
- Copy team and player names exactly as given.
- Do not mention method details (window lengths, thresholds, formulas); they are
  not facts. Write a span of minutes as "between 55' and 60'".
- Do not claim anything listed under "cannot tell". In particular, a missing
  detection is not evidence that nothing changed.
- No percentages or rates the facts do not give; no player names with numbers.
Return JSON matching the schema: {"sentences": [{"text": ..., "evidence_ids": [...]}]}."""

PERSONA_GUIDE = {
    "casual": "Audience: casual fan. 2-4 short sentences, plain words, no jargon; "
              "explain at most one statistic and why it matters.",
    "analyst": "Audience: analyst. 3-6 precise sentences; name the metric, its value and "
               "its caveat when relevant; tactical vocabulary is welcome.",
}
LANGUAGE_GUIDE = {
    "en": "Write in English. Copy numbers exactly as displayed (83.6%, 1029, 63').",
    "es": "Escribe en español. Copia los números del display cambiando el punto decimal "
          "por coma: 83.6% -> 83,6 %, 22.8 m -> 22,8 m; enteros y minutos iguales "
          "(1029, 63').",
}
KIND_GUIDE = {
    "moment": "Explain what is happening right now and why it matters.",
    "recap": "Recap the match so far: score, the key moments, and what decided them. "
             "Use match_summary and key_moments.",
    "question": "Answer the viewer's question.",
}


def roster(metadata: MatchMetadata) -> str:
    lines = []
    for side, team in (("home", metadata.home), ("away", metadata.away)):
        players = ", ".join(f"{p.player_id} {p.name} (#{p.shirt_number}, {p.position})"
                            for p in team.players)
        lines.append(f"{side}: {team.team_id} {team.name} [{team.short_name}] - {players}")
    return "\n".join(lines)


def analyst_prompt(request: TurnRequest, metadata: MatchMetadata) -> str:
    parts = [
        f"Request: {request.kind}. {KIND_GUIDE[request.kind]}",
        f"as_of_seq: {request.as_of_seq} (use exactly this value in every tool call)",
        f"Audience: {request.persona}. Teams and players:\n{roster(metadata)}",
    ]
    if request.question:
        parts.append(f"Viewer question: {request.question}")
    return "\n\n".join(parts)


def _facts_block(results: Sequence[ToolResult]) -> str:
    lines, count = [], 0
    for r in results:
        lines.append(f"## {r.tool_name} {json.dumps(r.params)}")
        lines.append(f"method: {r.method}")
        for c in r.caveats:
            lines.append(f"caveat: {c}")
        for c in r.cannot_tell:
            lines.append(f"cannot tell: {c}")
        for f in r.facts:
            if count >= MAX_FACTS_FOR_NARRATOR:
                break
            lines.append(json.dumps({"id": f.evidence_id, "label": f.label,
                                     "display": f.display}, ensure_ascii=False))
            count += 1
    return "\n".join(lines)


def narrator_prompt(request: TurnRequest, metadata: MatchMetadata,
                    results: Sequence[ToolResult], feedback: Sequence[str] = ()) -> str:
    parts = [
        f"{KIND_GUIDE[request.kind]} {PERSONA_GUIDE[request.persona]}",
        LANGUAGE_GUIDE[request.language],
        f"Match: {metadata.home.name} (home) vs {metadata.away.name} (away).",
    ]
    if request.question:
        parts.append(f"Viewer question: {request.question}")
    parts.append("Facts (quote only these):\n" + _facts_block(results))
    if feedback:
        parts.append("Your previous narrative failed verification. Fix exactly these "
                     "problems and keep everything else grounded:\n- " + "\n- ".join(feedback))
    return "\n\n".join(parts)
