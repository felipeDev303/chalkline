"""Fact-checking anyone's commentary line, on simulated match 7 at seq 480 (30').

At that point (match_summary): Halvesham Town (T03) 0-1 Westerlake City (T05);
shots 2 and 7; possession share 48% and 52%. Cyril Ulkov (T03-07) has 9 passes.
"""

import pytest
from fastapi.testclient import TestClient

from pitchside.agents.fact_check import check_line
from pitchside.api.app import create_app
from pitchside.simulator import simulate_match

SEQ = 480


@pytest.fixture(scope="module")
def match():
    return simulate_match(7)


def statuses(match, text, language="en"):
    r = check_line(match, text, SEQ, language)
    return r.verdict, [(n.raw, n.status) for n in r.numbers]


def test_true_lines_verify(match):
    assert statuses(match, "Westerlake City lead 0-1 at 30'.") == (
        "verified", [("0-1", "supported"), ("30'", "supported")])
    assert statuses(match, "Possession for Westerlake City is 52%.") == (
        "verified", [("52", "supported")])
    assert statuses(match, "Cyril Ulkov has made 9 passes.") == ("verified", [("9", "supported")])


def test_a_number_that_exists_nowhere_is_unsupported_with_the_real_value(match):
    r = check_line(match, "Westerlake City have had 85% possession.", SEQ, "en")
    [n] = r.numbers
    assert (r.verdict, n.status, n.stat) == ("flagged", "unsupported", "possession")
    assert [f.display for f in n.data_says][:1] == ["52%"]


def test_a_real_number_on_the_wrong_stat_or_team_is_flagged(match):
    # 52 is Westerlake's possession, not Halvesham's shots.
    r = check_line(match, "Halvesham Town have taken 52 shots.", SEQ, "en")
    assert [(n.status, n.matches[0].label) for n in r.numbers] == [
        ("wrong_stat", "Possession share")]
    assert r.numbers[0].data_says[0].evidence_id == "summary.team:T03.shots"
    # 7 is a real shot count, but Westerlake's.
    assert statuses(match, "Halvesham Town have 7 shots.")[1] == [("7", "wrong_stat")]


def test_each_number_goes_with_the_nearest_name_and_stat_in_spanish(match):
    verdict, checks = statuses(
        match, "Westerlake City tiene 7 remates y 52% de posesión.", "es")
    assert (verdict, checks) == ("verified", [("7", "supported"), ("52", "supported")])
    # The 3 is about Westerlake City (named just before), not Cyril Ulkov.
    r = check_line(match, "Cyril Ulkov hizo 25 pases y Westerlake City tiene 3 remates.",
                   SEQ, "es")
    assert [n.status for n in r.numbers] == ["unsupported", "wrong_stat"]
    assert r.numbers[1].data_says[0].evidence_id == "summary.team:T05.shots"


def test_names_and_lines_without_numbers(match):
    r = check_line(match, "Westerlak City are flying.", SEQ, "en")
    assert r.verdict == "flagged" and "Westerlake" in r.misspelled[0]
    assert check_line(match, "A cagey game.", SEQ, "en").verdict == "nothing_to_check"


def test_no_look_ahead(match):
    """The goal at 27' is not known at 20': the scoreline is unsupported then."""
    early = next(e.seq for e in match.events if e.period == 1 and e.clock_s >= 20 * 60)
    r = check_line(match, "Westerlake City lead 0-1.", early, "en")
    assert [n.status for n in r.numbers] == ["unsupported"]


def test_check_endpoint(tmp_path):
    async def no_models(stack):
        return []

    with TestClient(create_app(seeds=[7], models=no_models, cache_dir=tmp_path)) as c:
        url = "/api/matches/sim-7/check"
        r = c.post(url, json={"text": "Westerlake City lead 0-1.", "as_of_seq": SEQ,
                              "language": "en"})
        assert r.status_code == 200 and r.json()["verdict"] == "verified"
        too_long = {"text": "x" * 301, "as_of_seq": SEQ, "language": "en"}
        assert c.post(url, json=too_long).status_code == 422


def test_check_endpoint_is_rate_limited(tmp_path):
    async def no_models(stack):
        return []

    app = create_app(seeds=[7], models=no_models, cache_dir=tmp_path, checks_per_minute=2)
    line = {"text": "Westerlake City lead 0-1.", "as_of_seq": SEQ, "language": "en"}
    with TestClient(app) as c:
        codes = [c.post("/api/matches/sim-7/check", json=line).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
