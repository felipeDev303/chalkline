"""Grounding validator: every number in a narrative must be a fact's display value.

Rules (docs/METHODS.md, "Grounding"):
- Facts come only from the ToolResults of the same agent turn (one as_of_seq).
- Digits are read by locale: en "1,029.5", es "1.029,5". A number written in the
  other locale's style does not parse cleanly and is rejected.
- Minute marks (63', 45+2') and hyphenated digit groups are single tokens: a
  formation (4-3-3) must match in order; a scoreline matches as an unordered pair
  (1-2 matches a 2-1 fact). Who won is not checked here (verifier's job).
- Number words 0-20 count as numbers, except inside the tested idioms below.
- A number passes only if it equals a fact display after normalisation (83.6 ==
  83.60, % and units ignored); 84 does not match a fact shown as 83.6%.
It checks that each number exists among the facts, not that it is attributed to
the right subject; claim-level checks belong to the verifier agent.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pitchside.metrics.contract import Fact, ToolResult

Locale = Literal["en", "es"]

NUMBER_WORDS: dict[str, dict[str, int]] = {
    "en": {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20,
    },
    # "un"/"una" are left out: they are mostly the indefinite article ("un pase").
    "es": {
        "cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
        "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
        "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
        "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    },
}

# Idioms whose number word is not a quantity claim. Each one is covered by a test.
IDIOM_EXEMPTIONS: dict[str, tuple[str, ...]] = {
    "en": ("one of", "one-two", "one-on-one", "one on one", "one-touch", "no one",
           "this one", "that one", "1st half", "2nd half"),
    "es": ("uno de", "una de", "los dos", "las dos", "uno a uno", "uno contra uno",
           "1er tiempo", "1.er tiempo", "2º tiempo", "2.º tiempo"),
}

_LEFT = r"(?<![\w.,])"  # not glued to a word or to another number
_RIGHT = r"(?![\w]|[.,]\d)"
# A minus sign only after whitespace or an opening bracket: in "55'-60'" the dash is
# a range, and 60' is read as a minute mark, not as -60.
_SIGN = r"(?:(?<![^\s(\[])-)?"
# 63' needs the mark; 45+2 is a minute with or without it.
_MINUTE = (
    rf"{_LEFT}(?P<min>\d{{1,3}}\s?\+\s?\d{{1,2}}(?!\d)|\d{{1,3}}(?=\s?['’′]))\s?['’′]?"
)
_GROUP = rf"{_LEFT}(?P<grp>\d{{1,3}}(?:\s?[-–—]\s?\d{{1,3}})+){_RIGHT}"
_DIGITS = {  # thousands groups or plain digits, then decimals; ordinal suffixes
    "en": (r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", r"(?:st|nd|rd|th)?"),
    "es": (r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", r"(?:\.?[ºª]|er)?"),
}
_NUMBER = {
    locale: rf"{_LEFT}(?P<num>{_SIGN}{digits}){ordinal}{_RIGHT}"
    for locale, (digits, ordinal) in _DIGITS.items()
}
# Digits no valid pattern accepted (e.g. "83,6" in en): always unmatched. Digits
# glued to letters (ids like T06) are not numbers and are skipped.
_MALFORMED = r"(?<!\w)(?P<bad>\d[\d.,]*\d|\d)"
_DISPLAY_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _token_re(locale: Locale) -> re.Pattern[str]:
    words = "|".join(sorted(NUMBER_WORDS[locale], key=len, reverse=True))
    return re.compile(
        rf"{_MINUTE}|{_GROUP}|{_NUMBER[locale]}|(?P<word>\b(?:{words})\b)|{_MALFORMED}",
        re.IGNORECASE,
    )


_TOKEN_RE = {locale: _token_re(locale) for locale in ("en", "es")}
_EXEMPTION_RE = {
    locale: re.compile(
        r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b", re.IGNORECASE
    )
    for locale, phrases in IDIOM_EXEMPTIONS.items()
}


@dataclass(frozen=True)
class NumberToken:
    raw: str
    kind: Literal["number", "word", "group", "minute", "malformed"]
    value: Decimal | None = None  # numbers and words
    key: str | None = None  # groups and minutes, canonical form


class GroundingReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    unmatched_numbers: tuple[str, ...]
    matched_ids: tuple[str, ...]
    checked: int


def _fold_char(c: str) -> str:
    base = "".join(d for d in unicodedata.normalize("NFD", c) if not unicodedata.combining(d))
    folded = base.lower()
    return folded if len(folded) == 1 else c


def _fold(text: str) -> str:
    """Lowercase and strip accents, one character for one, so offsets map to `text`."""
    return "".join(_fold_char(c) for c in text)


def _canonical_group(raw: str) -> str:
    return re.sub(r"\s?[-–—]\s?", "-", raw)


def _canonical_minute(raw: str) -> str:
    return re.sub(r"\s", "", raw) + "'"


def _parse_number(raw: str, locale: Locale) -> Decimal:
    if locale == "en":
        return Decimal(raw.replace(",", ""))
    return Decimal(raw.replace(".", "").replace(",", "."))


def extract_numbers(text: str, locale: Locale) -> tuple[NumberToken, ...]:
    """Every number-like token in `text`, in order."""
    folded = _EXEMPTION_RE[locale].sub(lambda m: " " * len(m.group()), _fold(text))
    words = NUMBER_WORDS[locale]
    tokens = []
    for m in _TOKEN_RE[locale].finditer(folded):
        raw = text[m.start():m.end()]
        if m.group("min") is not None:
            tokens.append(NumberToken(raw, "minute", key=_canonical_minute(m.group("min"))))
        elif m.group("grp") is not None:
            tokens.append(NumberToken(raw, "group", key=_canonical_group(m.group("grp"))))
        elif m.group("num") is not None:
            try:
                value = _parse_number(m.group("num"), locale)
            except InvalidOperation:
                tokens.append(NumberToken(raw, "malformed"))
            else:
                tokens.append(NumberToken(raw, "number", value=value))
        elif m.group("word") is not None:
            tokens.append(NumberToken(raw, "word", value=Decimal(words[m.group("word")])))
        else:
            tokens.append(NumberToken(raw, "malformed"))
    return tuple(tokens)


@dataclass(frozen=True)
class _FactIndex:
    numbers: dict[Decimal, list[str]]
    keys: dict[str, list[str]]  # minute marks and formations, by display string
    pairs: dict[tuple[int, int], list[str]]  # scorelines, as a sorted pair


def _pair(group: str) -> tuple[int, int] | None:
    parts = group.split("-")
    if len(parts) != 2:
        return None
    a, b = sorted(int(p) for p in parts)
    return (a, b)


def _index(facts: Sequence[Fact]) -> _FactIndex:
    numbers: dict[Decimal, list[str]] = {}
    keys: dict[str, list[str]] = {}
    pairs: dict[tuple[int, int], list[str]] = {}
    for f in facts:
        display = f.display.strip()
        if f.unit == "minute":
            keys.setdefault(display, []).append(f.evidence_id)
            if "+" not in display:  # "the 63rd minute" quotes 63' as a plain number
                numbers.setdefault(Decimal(display[:-1]), []).append(f.evidence_id)
        elif f.unit == "formation":
            keys.setdefault(display, []).append(f.evidence_id)
        elif f.unit == "scoreline":
            pair = _pair(display)
            assert pair is not None
            pairs.setdefault(pair, []).append(f.evidence_id)
        elif f.unit == "label":
            continue  # words only, nothing to quote as a number
        else:
            m = _DISPLAY_NUMBER.match(display)
            if m:
                numbers.setdefault(Decimal(m.group()), []).append(f.evidence_id)
    return _FactIndex(numbers, keys, pairs)


def validate(text: str, results: Sequence[ToolResult], locale: Locale) -> GroundingReport:
    """Check `text` against the facts of the ToolResults from one agent turn."""
    as_of = {r.as_of_seq for r in results}
    if len(as_of) > 1:
        raise ValueError(
            f"grounding uses facts from a single agent turn; got as_of_seq {sorted(as_of)}"
        )
    return validate_facts(text, [f for r in results for f in r.facts], locale)


def match_numbers(text: str, facts: Sequence[Fact],
                  locale: Locale) -> list[tuple[NumberToken, list[str]]]:
    """Every number in `text`, with the ids of the facts whose display it matches."""
    index = _index(facts)
    out = []
    for token in extract_numbers(text, locale):
        if token.kind == "group":
            assert token.key is not None
            pair = _pair(token.key)
            ids = index.keys.get(token.key, []) + (index.pairs.get(pair, []) if pair else [])
        elif token.key is not None:
            ids = index.keys.get(token.key, [])
        elif token.value is not None:
            ids = index.numbers.get(token.value, [])
        else:
            ids = []
        out.append((token, ids))
    return out


def validate_facts(text: str, facts: Sequence[Fact], locale: Locale) -> GroundingReport:
    """Check `text` against exactly these facts (e.g. the ones a sentence cites).

    The caller is responsible for the facts coming from a single agent turn.
    """
    pairs = match_numbers(text, facts, locale)
    return GroundingReport(
        ok=all(ids for _, ids in pairs),
        unmatched_numbers=tuple(t.raw for t, ids in pairs if not ids),
        matched_ids=tuple(dict.fromkeys(i for _, ids in pairs for i in ids)),
        checked=len(pairs),
    )
