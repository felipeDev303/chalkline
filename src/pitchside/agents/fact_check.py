"""Fact-check a line of commentary written by anyone, against what is known at a moment.

The desk's verifier checks the narrator's own sentences against the facts they cite.
A commentator's line cites nothing, so here every number is looked up in the facts
of a broad, deterministic evidence set computed at `as_of_seq` (nothing later), and
attributed by proximity: the stat named nearest to the number ("52% possession")
must be one that number actually belongs to, for the team or player the line names.

Statuses per number:
- supported: a fact of the named stat (and team or player) has this display;
- wrong_stat: the number exists, but for a different stat or team;
- unsupported: no fact at this moment has this number;
- found: no stat is named nearby, and some fact has this number.
No model is involved: the result is deterministic and free.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pitchside.agents.contracts import Language
from pitchside.agents.verifier import known_names, misspelled_names
from pitchside.events.match import Match
from pitchside.metrics._timeline import view
from pitchside.metrics.contract import Fact, ToolError, ToolResult
from pitchside.metrics.grounding import match_numbers
from pitchside.metrics.registry import call

# Stat words in a line (English, Spanish) and the words of the fact labels they mean.
CONCEPTS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "possession": (("possession",), ("posesión", "posesion"), ("possession",)),
    "on_target": (("on target",), ("al arco", "a puerta", "al arco"), ("on target",)),
    "xg": (("xg", "expected goals"), ("xg", "goles esperados"), ("expected goals",)),
    "completion": (("completion", "accuracy", "pass completion"),
                   ("precisión", "precision", "acierto"), ("completion",)),
    "win": (("chance of winning", "win probability", "chance to win", "winning"),
            ("probabilidad de ganar", "probabilidad", "ganar"), ("winning",)),
    "shots": (("shots", "shot", "attempts"), ("remates", "remate", "tiros", "tiro"), ("shot",)),
    "goals": (("goals", "goal", "scored"), ("goles", "gol", "marcó", "anotó"), ("goal",)),
    "passes": (("passes", "pass"), ("pases", "pase"), ("pass",)),
    "pressing": (("pressing", "pressures", "press"), ("presiones", "presión", "presion"),
                 ("pressure",)),
    "control": (("control",), ("control",), ("control",)),
}
NEAR_CHARS = 30  # a stat word this close to a number names that number's stat

Status = Literal["supported", "wrong_stat", "unsupported", "found"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NumberCheck(_Strict):
    raw: str
    status: Status
    stat: str | None  # the stat named next to the number, if any
    matches: tuple[Fact, ...]  # facts with this number (the right ones first)
    data_says: tuple[Fact, ...] = ()  # the named stat's facts, when the number is off


class LineCheck(_Strict):
    text: str
    as_of_seq: int
    language: Language
    verdict: Literal["verified", "flagged", "nothing_to_check"]
    numbers: tuple[NumberCheck, ...]
    misspelled: tuple[str, ...]
    sample_size: int  # facts searched


def evidence(match: Match, as_of_seq: int, text: str) -> list[ToolResult]:
    """A broad evidence set at as_of_seq, plus the stats of any player the line names."""
    v = view(match, as_of_seq)
    seq = v.as_of_seq
    calls: list[tuple[str, dict]] = [
        ("match_summary", {}), ("key_moments", {"limit": 20}),
        ("win_probability", {"scope": "goals"}), ("shot_quality", {"scope": "best"}),
        ("off_ball_credit", {"scope": "all"}),
    ]
    for team in v.teams:
        for tool in ("shot_profile", "pass_profile"):
            calls.append((tool, {"subject": "team", "subject_id": team.team_id}))
    for team in v.teams:
        for p in team.players:
            if p.name in text:
                calls.append(("player_focus", {"player_id": p.player_id}))
    out = []
    for name, args in calls:
        try:
            out.append(call(name, match, {"as_of_seq": seq, **args}))
        except ToolError:
            continue  # e.g. a tool that needs more of the match: simply not evidence
    return out


def _stat_near(text: str, start: int, end: int, language: Language) -> str | None:
    """The stat named next to the number at text[start:end]: the closest word after it
    ("52% possession"), else the closest before it ("possession of 52%")."""
    lowered = text.lower()
    after: tuple[int, str] | None = None
    before: tuple[int, str] | None = None
    for concept, (en, es, _) in CONCEPTS.items():
        for word in en if language == "en" else es:
            for m in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", lowered):
                if m.start() >= end:
                    gap = m.start() - end
                    if gap <= NEAR_CHARS and (after is None or gap < after[0]):
                        after = (gap, concept)
                elif m.end() <= start:
                    gap = start - m.end()
                    if gap <= NEAR_CHARS and (before is None or gap < before[0]):
                        before = (gap, concept)
    best = after or before
    return best[1] if best else None


def _mentions(text: str, match: Match) -> list[tuple[int, str]]:
    """(position, id) of every player and team the line names."""
    meta = match.metadata
    found = []
    for t in (meta.home, meta.away):
        for p in t.players:
            found += [(m.start(), p.player_id) for m in re.finditer(re.escape(p.name), text)]
        for name in (t.name, t.short_name):
            found += [(m.start(), t.team_id)
                      for m in re.finditer(rf"\b{re.escape(name)}\b", text)]
    return sorted(found)


def _owners_at(mentions: list[tuple[int, str]], position: int) -> list[str]:
    """Who a number at `position` is about: the last name before it, else the first after."""
    before = [i for p, i in mentions if p < position]
    if before:
        return [before[-1]]
    after = [i for p, i in mentions if p > position]
    return after[:1]


def _unique(facts: list[Fact]) -> list[Fact]:
    """One fact per label and value (several tools report the same count)."""
    seen: dict[tuple[str, str], Fact] = {}
    for f in facts:
        seen.setdefault((f.label, f.display), f)
    return list(seen.values())


def _about(f: Fact, owners: list[str], match: Match) -> int:
    """2: about one of the owners; 1: about no team in particular; 0: about someone else."""
    meta = match.metadata
    names = {t.team_id: t.name for t in (meta.home, meta.away)}
    if any(o in f.evidence_id or (o in names and names[o] in f.label) for o in owners):
        return 2
    tagged = any(i in f.evidence_id or n in f.label for i, n in names.items())
    return 0 if tagged and owners else 1


def check_line(match: Match, text: str, as_of_seq: int, language: Language) -> LineCheck:
    results = evidence(match, as_of_seq, text)
    facts = list({f.evidence_id: f for r in results for f in r.facts}.values())
    by_id = {f.evidence_id: f for f in facts}
    mentions = _mentions(text, match)
    checks, cursor = [], 0
    for token, ids in match_numbers(text, facts, language):
        start = text.find(token.raw, cursor)
        start = start if start >= 0 else cursor
        end = start + len(token.raw)
        cursor = end
        owners = _owners_at(mentions, start)
        matches = _unique([by_id[i] for i in dict.fromkeys(ids)])
        if token.kind in ("minute", "group"):  # minute marks, scorelines: self-describing
            checks.append(NumberCheck(raw=token.raw, status="supported" if ids else "unsupported",
                                      stat=None, matches=tuple(matches[:3])))
            continue
        stat = _stat_near(text, start, end, language)
        if stat is None:
            checks.append(NumberCheck(raw=token.raw, status="found" if ids else "unsupported",
                                      stat=None, matches=tuple(matches[:3])))
            continue
        label_words = CONCEPTS[stat][2]

        def of_stat(f: Fact, words: tuple[str, ...] = label_words,
                    owners: list[str] = owners) -> bool:
            """A count or rate of the named stat (a minute mark never is one)."""
            return (f.unit != "minute" and any(w in f.label.lower() for w in words)
                    and _about(f, owners, match) > 0)

        def rank(f: Fact, owners: list[str] = owners) -> tuple[int, int]:
            return (-_about(f, owners, match), len(f.label))  # the owner's, plain stats first

        matches = [f for f in matches if f.unit != "minute"]
        right = sorted((f for f in matches if of_stat(f)), key=rank)
        data = () if right else tuple(
            _unique(sorted((f for f in facts if of_stat(f)), key=rank))[:1])
        status: Status = "supported" if right else "wrong_stat" if matches else "unsupported"
        shown = right or matches  # what backs it, else what the number really is
        checks.append(NumberCheck(raw=token.raw, status=status, stat=stat,
                                  matches=tuple(shown[:3]), data_says=data))
    misspelled = tuple(misspelled_names(text, known_names(match.metadata)))
    flagged = misspelled or any(c.status in ("wrong_stat", "unsupported") for c in checks)
    verdict = "flagged" if flagged else "verified" if checks else "nothing_to_check"
    return LineCheck(text=text, as_of_seq=view(match, as_of_seq).as_of_seq, language=language,
                     verdict=verdict, numbers=tuple(checks), misspelled=misspelled,
                     sample_size=len(facts))
