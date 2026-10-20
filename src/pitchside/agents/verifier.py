"""Verifier: deterministic, sentence by sentence, with attribution.

A sentence passes only if every number in it matches the display of a fact that
the sentence itself cites, and every cited id exists in this turn. So "T06
completed 83.6%" fails when 83.6% is T07's fact, even though the number exists.
Names are checked too: a capitalised name close to a team or player name but not
equal to it ("Davenport Athletic" for "Dravenport Athletic") is a misspelling.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence

from pitchside.agents.contracts import Language, Narrative, SentenceCheck, Verdict
from pitchside.events.schema import MatchMetadata
from pitchside.metrics.contract import Fact, ToolResult
from pitchside.metrics.grounding import extract_numbers, validate_facts

_CAPITALISED_RUN = re.compile(r"\b[A-ZÁÉÍÓÚÑ][\w'’-]+(?:\s+[A-ZÁÉÍÓÚÑ][\w'’-]+)*")
NAME_SIMILARITY = 0.8


def known_names(metadata: MatchMetadata) -> list[str]:
    names = []
    for team in (metadata.home, metadata.away):
        names += [team.name, team.short_name] + [p.name for p in team.players]
        names += [w for w in team.name.split() if len(w) >= 4]  # "Dravenport" alone
        names += [p.name.split()[-1] for p in team.players]  # surnames on their own
    return names


def misspelled_names(text: str, names: Sequence[str]) -> list[str]:
    """Capitalised words that look like a known name without being one.

    Exact names are removed first, so "Ahora Fernhallow Albion" is not mistaken
    for a misspelling of "Fernhallow Albion"; what is left is compared as a whole
    run, then word by word.
    """
    known = sorted(set(names), key=len, reverse=True)
    remaining = text
    for name in known:
        remaining = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", remaining)
    found = []
    for run in _CAPITALISED_RUN.findall(remaining):
        run = re.sub(r"['’]s\b", "", run)  # possessive: "Drapenport's" -> "Drapenport"
        for candidate in [run, *run.split()] if " " in run else [run]:
            if len(candidate) < 4:
                continue
            close = difflib.get_close_matches(candidate, known, n=1, cutoff=NAME_SIMILARITY)
            if close:
                found.append(f"{candidate!r} (did you mean {close[0]!r}?)")
                break
    return found


def _citation_hints(text: str, unmatched: Sequence[str], cited: Sequence[str],
                    facts: dict[str, Fact], language: Language) -> list[str]:
    """Facts to cite for unmatched minute marks and scorelines / formations.

    Only these: their value identifies the fact. A plain number such as 2 matches
    unrelated facts by coincidence, and suggesting one would invite a citation that
    passes verification while meaning something else.
    """
    hints: list[str] = []
    for token in extract_numbers(text, language):
        if token.raw not in unmatched or token.kind not in ("minute", "group"):
            continue
        report = validate_facts(token.raw, list(facts.values()), language)
        hints += [i for i in report.matched_ids if i not in cited and i not in hints]
    return hints[:6]


def verify(narrative: Narrative, results: Sequence[ToolResult], language: Language,
           metadata: MatchMetadata | None = None) -> Verdict:
    if len({r.as_of_seq for r in results}) > 1:
        raise ValueError("a narrative is verified against one agent turn only")
    facts: dict[str, Fact] = {f.evidence_id: f for r in results for f in r.facts}
    names = known_names(metadata) if metadata is not None else []
    checks: list[SentenceCheck] = []
    feedback: list[str] = []
    for i, sentence in enumerate(narrative.sentences, start=1):
        problems: list[str] = []
        unknown = [eid for eid in sentence.evidence_ids if eid not in facts]
        if unknown:
            problems.append(f"cites ids that are not in this turn: {unknown}")
        cited = [facts[eid] for eid in sentence.evidence_ids if eid in facts]
        has_numbers = bool(extract_numbers(sentence.text, language))
        if has_numbers:
            report = validate_facts(sentence.text, cited, language)
            if not report.ok:
                problem = (f"numbers {list(report.unmatched_numbers)} do not match the "
                           f"display of any fact it cites {list(sentence.evidence_ids)}")
                hints = _citation_hints(sentence.text, report.unmatched_numbers,
                                        sentence.evidence_ids, facts, language)
                if hints:
                    problem += f"; if you meant these facts, cite them: {hints}"
                problem += ("; plain numbers must be copied from a cited fact - never count "
                            "or compute (no 'two chances', 'both goals')")
                problems.append(problem)
        wrong_names = misspelled_names(sentence.text, names)
        if wrong_names:
            problems.append(f"misspelled names {wrong_names}; copy names exactly")
        kind = "claim" if has_numbers or sentence.evidence_ids else "interpretation"
        checks.append(SentenceCheck(text=sentence.text, evidence_ids=sentence.evidence_ids,
                                    kind=kind, ok=not problems, problems=tuple(problems)))
        feedback += [f"Sentence {i} ({sentence.text!r}): {p}" for p in problems]
    if not narrative.sentences:
        feedback.append("The narrative has no sentences.")
    elif not any(c.kind == "claim" for c in checks):
        feedback.append("No sentence cites evidence; ground at least one sentence in a fact.")
    return Verdict(ok=not feedback, checks=tuple(checks), feedback=tuple(feedback))
