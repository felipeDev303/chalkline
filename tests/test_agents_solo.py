"""The single-agent ablation baseline, offline."""

import anyio
from mini_match import build_mini_match
from test_agents_desk import GOOD, MISATTRIBUTED, request, summary_at

from pitchside.agents.clients import ScriptedChatClient, json_reply
from pitchside.agents.solo import run_solo


def _run(replies, retry):
    model = ScriptedChatClient(replies)
    return anyio.run(lambda: run_solo(build_mini_match(), [("primary", model)], request(),
                                      verify_and_retry=retry))


def test_solo_without_verifier_airs_a_bad_narrative():
    insight = _run([summary_at(19), json_reply(MISATTRIBUTED)], retry=False)
    assert insight.status == "unverified"
    assert insight.sentences and not insight.sentences[0].ok  # it would air anyway


def test_solo_with_verifier_retries_in_the_same_conversation():
    insight = _run([summary_at(19), json_reply(MISATTRIBUTED), json_reply(GOOD)], retry=True)
    assert insight.status == "verified_after_retry" and insight.attempts == 2


def test_solo_with_verifier_hides_a_narrative_that_fails_twice():
    insight = _run([summary_at(19), json_reply(MISATTRIBUTED), json_reply(MISATTRIBUTED)],
                   retry=True)
    assert insight.status == "evidence_only" and insight.sentences == ()


def test_solo_verified_first_time():
    insight = _run([summary_at(19), json_reply(GOOD)], retry=True)
    assert insight.status == "verified" and insight.attempts == 1
