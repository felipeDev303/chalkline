from decimal import Decimal

import pytest

from pitchside.metrics.contract import ToolResult, fact, minute_fact
from pitchside.metrics.grounding import (
    IDIOM_EXEMPTIONS,
    NUMBER_WORDS,
    extract_numbers,
    validate,
)


def _result(*facts, as_of_seq=500):
    return ToolResult(tool_name="test", params={"as_of_seq": as_of_seq}, as_of_seq=as_of_seq,
                      facts=facts, sample_size=1, method="hand-made facts")


FACTS = _result(
    fact("pass.team:T1.completion_pct", "Pass completion", 83.6, "pct"),
    fact("summary.team:T1.passes", "Passes", 1029, "count"),
    fact("summary.team:T1.formation", "Formation", "4-3-3", "formation"),
    fact("summary.scoreline", "Scoreline (home-away)", "2-1", "scoreline"),
    fact("window.p1.w03.state", "Window state", "control", "label"),
    minute_fact("moment:goal@412", "Goal minute", 63),
    minute_fact("moment:goal@700", "Goal minute", 45, 2),
    fact("player:T1-9.passes", "Passes", 50, "count"),
    fact("summary.team:T1.shots", "Shots", 3, "count"),
    fact("shot.team:T1.mean_speed_kmh", "Mean shot speed", 92.4, "km/h"),
)

EN_OK = (
    "Alder won 2-1 in a 4-3-3, completing 83.6% of 1,029 passes. The goals came at 63' "
    "and 45+2'; his 50th pass set up three shots at 92.4 km/h, one of them after a one-two."
)
ES_OK = (
    "Alder ganó 2-1 con un 4-3-3 y completó el 83,6 % de 1.029 pases. Los goles llegaron "
    "en el minuto 63 y en el 45+2'; su 50.º pase generó tres tiros a 92,4 km/h. Uno de los "
    "dos laterales empujó y ambos centrales salieron bien."
)


# --- extraction ------------------------------------------------------------------

def test_extract_en():
    tokens = extract_numbers("83.6% of 1,029 passes, 4-3-3, at 63' and 45+2', 50th, three", "en")
    assert [(t.kind, t.value, t.key) for t in tokens] == [
        ("number", Decimal("83.6"), None),
        ("number", Decimal("1029"), None),
        ("group", None, "4-3-3"),
        ("minute", None, "63'"),
        ("minute", None, "45+2'"),
        ("number", Decimal("50"), None),
        ("word", Decimal("3"), None),
    ]


def test_extract_es():
    tokens = extract_numbers("83,6 % de 1.029 pases, 4–3–3, al 63’, su 50.º pase, dieciséis", "es")
    assert [(t.kind, t.value, t.key) for t in tokens] == [
        ("number", Decimal("83.6"), None),
        ("number", Decimal("1029"), None),
        ("group", None, "4-3-3"),
        ("minute", None, "63'"),
        ("number", Decimal("50"), None),
        ("word", Decimal("16"), None),
    ]


@pytest.mark.parametrize(("text", "locale"), [("83,6%", "en"), ("83.6 %", "es"), ("2.5", "es")])
def test_other_locale_style_is_malformed(text, locale):
    (token,) = extract_numbers(text, locale)
    assert token.kind == "malformed"


def test_ids_glued_to_letters_are_not_numbers():
    assert extract_numbers("T06 beat T07 (match sim-x)", "en") == ()


def test_articles_un_una_are_not_numbers():
    assert extract_numbers("un pase y una jugada", "es") == ()


# --- validation ------------------------------------------------------------------

def test_accepts_correct_en_narrative():
    report = validate(EN_OK, [FACTS], "en")
    assert report.ok, report.unmatched_numbers
    quotable = {f.evidence_id for f in FACTS.facts if f.unit != "label"}
    assert set(report.matched_ids) == quotable


def test_accepts_correct_es_narrative():
    report = validate(ES_OK, [FACTS], "es")
    assert report.ok, report.unmatched_numbers


def test_rejects_invented_number():
    report = validate(EN_OK + " They also won 7 corners.", [FACTS], "en")
    assert not report.ok and report.unmatched_numbers == ("7",)


def test_rejects_number_rounded_differently_from_display():
    report = validate("Completion was 84%.", [FACTS], "en")
    assert report.unmatched_numbers == ("84",)
    assert validate("Completion was 83.60%.", [FACTS], "en").ok


def test_rejects_wrong_locale_formatting():
    assert validate("Completion was 83,6%.", [FACTS], "en").unmatched_numbers == ("83,6",)
    assert validate("Completó el 83.6 %.", [FACTS], "es").unmatched_numbers == ("83.6",)


def test_small_integers_need_a_fact_too():
    assert validate("2 shots", [FACTS], "en").unmatched_numbers == ("2",)
    assert validate("four shots", [FACTS], "en").unmatched_numbers == ("four",)
    assert validate("3 shots", [FACTS], "en").ok


def test_formation_matches_in_order():
    assert validate("a 4 - 3 - 3 shape", [FACTS], "en").ok
    assert validate("a 4-4-2 shape", [FACTS], "en").unmatched_numbers == ("4-4-2",)
    assert validate("a 3-3-4 shape", [FACTS], "en").unmatched_numbers == ("3-3-4",)


def test_scoreline_matches_as_an_unordered_pair():
    assert validate("Birch lost 1-2", [FACTS], "en").ok
    assert validate("Alder won 2–1", [FACTS], "en").ok
    assert validate("a 3-1 win", [FACTS], "en").unmatched_numbers == ("3-1",)
    # a scoreline is not a formation and vice versa
    assert validate("a 2-1 shape", [_result(FACTS.facts[2])], "en").unmatched_numbers == ("2-1",)


def test_minute_ranges_are_two_minutes_not_a_negative_number():
    tokens = extract_numbers("between 55'-60' and 60' - 65'", "en")
    assert [(t.kind, t.key) for t in tokens] == [
        ("minute", "55'"), ("minute", "60'"), ("minute", "60'"), ("minute", "65'")]
    assert extract_numbers("a drop of -4.2/min", "en")[0].value == Decimal("-4.2")
    assert extract_numbers("(-3)", "en")[0].value == Decimal("-3")


def test_minute_marks():
    assert validate("at 63’ and in the 63rd minute", [FACTS], "en").ok
    assert validate("in minute 45+2 and at 45 + 2'", [FACTS], "en").ok
    assert validate("at 64'", [FACTS], "en").unmatched_numbers == ("64'",)
    assert validate("at 47'", [FACTS], "en").unmatched_numbers == ("47'",)


def test_no_facts_means_no_numbers():
    assert validate("Nothing to quote here.", [], "en").ok
    assert not validate("A 1-0 lead.", [], "en").ok


def test_facts_from_one_agent_turn_only():
    earlier = _result(fact("summary.team:T1.shots", "Shots", 2, "count"), as_of_seq=400)
    with pytest.raises(ValueError, match="single agent turn"):
        validate("3 shots", [FACTS, earlier], "en")


# --- idioms ----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("locale", "phrase"),
    [(locale, phrase) for locale, phrases in IDIOM_EXEMPTIONS.items() for phrase in phrases],
)
def test_idiom_exemption(locale, phrase):
    assert validate(f"It was {phrase} the moments.", [], locale).ok


@pytest.mark.parametrize(("locale", "word"), [("en", "one"), ("en", "two"), ("es", "dos")])
def test_number_word_outside_an_idiom_is_checked(locale, word):
    assert not validate(f"There were {word} chances.", [], locale).ok


def test_ambos_is_not_a_number_word():
    assert "ambos" not in NUMBER_WORDS["es"]
    assert validate("ambos equipos", [], "es").ok
