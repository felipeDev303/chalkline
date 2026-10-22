"""The desk workflow, offline: scripted models against the hand-built mini match.

At as_of_seq 19 match_summary gives, among others: summary.scoreline "0-1",
summary.team:T1.passes "5", summary.team:T1.shots "0", summary.team:T2.passes "3".
"""

import anyio
import pytest
from mini_match import build_mini_match

from pitchside.agents.clients import ScriptedChatClient, json_reply, text_reply, tool_calls_reply
from pitchside.agents.contracts import Narrative, Sentence, TurnRequest
from pitchside.agents.desk import Desk
from pitchside.agents.verifier import verify
from pitchside.metrics.registry import call

T1_PASSES = "summary.team:T1.passes"
T1_SHOTS = "summary.team:T1.shots"
SCORE = "summary.scoreline"

GOOD = Narrative(sentences=(
    Sentence(text="Birch Rovers lead 0-1.", evidence_ids=(SCORE,)),
    Sentence(text="Alder Town have tried 5 passes but have 0 shots.",
             evidence_ids=(T1_PASSES, T1_SHOTS)),
    Sentence(text="It has been a cagey game."),
))
# 3 is a real number in this turn (T2's passes) but not the fact this sentence cites.
MISATTRIBUTED = Narrative(sentences=(
    Sentence(text="Alder Town have made 3 passes.", evidence_ids=(T1_PASSES,)),
))
GOOD_ES = Narrative(sentences=(
    Sentence(text="Birch Rovers gana 0-1 y Alder Town lleva 5 pases.",
             evidence_ids=(SCORE, T1_PASSES)),
))


def summary_at(seq):
    return tool_calls_reply(("match_summary", {"as_of_seq": seq}))


def request(seq=19, language="en", kind="moment"):
    return TurnRequest(as_of_seq=seq, kind=kind, persona="casual", language=language)


def run(desk, req):
    return anyio.run(desk.run, req)


@pytest.fixture
def mini():
    return build_mini_match()


# --- verifier --------------------------------------------------------------------

def test_verifier_checks_attribution_not_just_existence(mini):
    results = [call("match_summary", mini, {"as_of_seq": 19})]
    assert verify(GOOD, results, "en").ok
    verdict = verify(MISATTRIBUTED, results, "en")
    assert not verdict.ok
    assert "do not match" in verdict.feedback[0]
    # A plain 3 also matches T2's passes, but suggesting that id would reward a
    # coincidental citation: no hint, only the rule.
    assert "cite them" not in verdict.feedback[0]
    assert "never count or compute" in verdict.feedback[0]


def test_verifier_hints_unambiguous_citations(mini):
    results = [call("match_summary", mini, {"as_of_seq": 19})]
    narrative = Narrative(sentences=(Sentence(text="At 46', Birch Rovers lead 0-1.",
                                              evidence_ids=(SCORE,)),))
    feedback = verify(narrative, results, "en").feedback[0]
    assert "cite them: ['summary.minute']" in feedback


def test_verifier_rejects_unknown_ids_and_uncited_numbers(mini):
    results = [call("match_summary", mini, {"as_of_seq": 19})]
    unknown = Narrative(sentences=(Sentence(text="Fine.", evidence_ids=("made.up",)),))
    uncited = Narrative(sentences=(Sentence(text="Alder Town have tried 5 passes."),))
    only_words = Narrative(sentences=(Sentence(text="A cagey game."),))
    assert "not in this turn" in verify(unknown, results, "en").feedback[0]
    assert not verify(uncited, results, "en").ok
    assert "No sentence cites evidence" in verify(only_words, results, "en").feedback[0]


def test_verifier_catches_misspelled_names(mini):
    results = [call("match_summary", mini, {"as_of_seq": 19})]
    typo = Narrative(sentences=(Sentence(text="Birch Rover lead 0-1.", evidence_ids=(SCORE,)),))
    verdict = verify(typo, results, "en", mini.metadata)
    assert not verdict.ok and "'Rover' (did you mean 'Rovers'?)" in verdict.feedback[0]
    # exact names, also after a capitalised sentence opener, are fine
    fine = Narrative(sentences=(Sentence(text="Ahora Birch Rovers gana 0-1.",
                                         evidence_ids=(SCORE,)),))
    assert verify(fine, results, "es", mini.metadata).ok


def test_misspelled_names_on_a_real_roster():
    from pitchside.agents.verifier import known_names, misspelled_names
    from pitchside.simulator import simulate_match

    names = known_names(simulate_match(42).metadata)
    assert misspelled_names("Davenport Athletic lead.", names)  # Dravenport Athletic
    assert misspelled_names("Drapenport's 55% possession.", names)  # seen from gpt-4.1-mini
    assert not misspelled_names("Dravenport Athletic lead Fernhallow Albion.", names)
    assert not misspelled_names("Dravenport's lead and Fernhallow's shots.", names)
    assert not misspelled_names("Ahora mismo el juego está disputado.", names)


# --- desk ------------------------------------------------------------------------

def test_verified_first_time(mini):
    model = ScriptedChatClient([summary_at(19), text_reply("done"), json_reply(GOOD)])
    insight = run(Desk(mini, [("primary", model)]), request())
    assert insight.status == "verified" and insight.attempts == 1
    assert [c.kind for c in insight.sentences] == ["claim", "claim", "interpretation"]
    assert {f.evidence_id for f in insight.evidence} == {SCORE, T1_PASSES, T1_SHOTS}
    assert insight.model == "primary" and insight.notes == ()
    assert [r.tool_name for r in insight.results] == ["match_summary"]


def test_retry_with_feedback_then_verified(mini):
    model = ScriptedChatClient([summary_at(19), text_reply("done"),
                                json_reply(MISATTRIBUTED), json_reply(GOOD)])
    insight = run(Desk(mini, [("primary", model)]), request())
    assert insight.status == "verified_after_retry" and insight.attempts == 2
    retry_prompt = model.calls[-1][-1].text
    assert "failed verification" in retry_prompt and "do not match" in retry_prompt
    # the narrator sees its own draft and fixes only what failed
    assert "Your previous narrative" in retry_prompt
    assert "Alder Town have made 3 passes" in retry_prompt
    assert any(n.startswith("verifier rejected attempt 1") for n in insight.notes)


def test_two_failures_hide_the_narrative(mini):
    model = ScriptedChatClient([summary_at(19), text_reply("done"),
                                json_reply(MISATTRIBUTED), json_reply(MISATTRIBUTED)])
    insight = run(Desk(mini, [("primary", model)]), request())
    assert insight.status == "evidence_only" and insight.sentences == ()
    assert insight.evidence and "failed verification twice" in insight.failure


def test_fallback_model_takes_over(mini):
    primary = ScriptedChatClient([TimeoutError("primary timed out")])
    fallback = ScriptedChatClient([summary_at(19), text_reply("done"), json_reply(GOOD)])
    insight = run(Desk(mini, [("primary", primary), ("fallback", fallback)]), request())
    assert insight.status == "verified" and insight.model == "fallback"
    assert any("fallback" in n for n in insight.notes)


def test_no_model_at_all_gives_default_evidence(mini):
    insight = run(Desk(mini, [("primary", ScriptedChatClient([]))]), request())
    assert insight.status == "evidence_only"
    assert [r.tool_name for r in insight.results] == ["match_summary", "key_moments"]
    assert any("default evidence" in n for n in insight.notes)
    assert "narrator unavailable" in insight.failure


def test_analyst_cannot_look_ahead(mini):
    # Asked at seq 7, the analyst tries seq 19: the tools only hold events up to 7.
    model = ScriptedChatClient([summary_at(19), summary_at(7), text_reply("done"),
                                json_reply(Narrative(sentences=(
                                    Sentence(text="Birch Rovers lead 0-1.",
                                             evidence_ids=(SCORE,)),)))])
    insight = run(Desk(mini, [("primary", model)]), request(seq=7))
    assert insight.status == "verified"
    assert [r.as_of_seq for r in insight.results] == [7]
    second_call = " ".join(str(c.result) for m in model.calls[1] for c in m.contents
                           if c.type == "function_result")
    assert "as_of_out_of_range" in second_call


def test_analyst_fixes_a_bad_call(mini):
    model = ScriptedChatClient([
        tool_calls_reply(("pressure_shift", {"as_of_seq": 19, "team_id": "T9", "scope": "all"})),
        summary_at(19), text_reply("done"), json_reply(GOOD),
    ])
    insight = run(Desk(mini, [("primary", model)]), request())
    assert insight.status == "verified"
    assert [r.tool_name for r in insight.results] == ["match_summary"]


def test_spanish_narrative_is_verified_in_spanish(mini):
    model = ScriptedChatClient([summary_at(19), text_reply("done"), json_reply(GOOD_ES)])
    insight = run(Desk(mini, [("primary", model)]), request(language="es"))
    assert insight.status == "verified"
    assert "Escribe en español" in model.calls[-1][-1].text
