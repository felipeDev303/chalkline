"""Fitted models (xG, xPass), shot quality and win probability, with hand-worked values."""

import math

import pytest
from mini_match import build_mini_match

from pitchside.metrics import shot_quality, win_probability
from pitchside.metrics._logistic import Logistic
from pitchside.metrics._models import GOALS_PER_TEAM_90, XG, XPASS
from pitchside.metrics.models import odds_one_in
from pitchside.metrics.win_probability import (
    outcome_probs,
    played_minutes,
    poisson,
    remaining_rate,
    timeline,
)


@pytest.fixture(scope="module")
def mini():
    return build_mini_match()


def displays(result) -> dict[str, str]:
    return {f.evidence_id: f.display for f in result.facts}


# --- logistic models ---------------------------------------------------------------

def test_effects_add_up_to_the_log_odds():
    m = Logistic(features=("a", "b"), intercept=-1.0, coefs=(0.5, -2.0), means=(2.0, 0.5),
                 n_train=10, positives=3)
    x = (4.0, 1.0)
    average = m.log_odds(m.means)  # -1 + 1 - 1 = -1
    assert m.effects(x) == {"a": 1.0, "b": -1.0}
    assert average + sum(m.effects(x).values()) == pytest.approx(m.log_odds(x))
    assert m.prob(x) == pytest.approx(1 / (1 + math.exp(1.0)))


def test_fitted_models_have_football_signs():
    """Further and headed shots go in less; long, high and pressed passes fail more."""
    xg = dict(zip(XG.features, XG.coefs, strict=True))
    assert xg["distance_m"] < 0 < xg["angle_rad"]
    assert xg["header"] < 0 and xg["under_pressure"] < 0
    xpass = dict(zip(XPASS.features, XPASS.coefs, strict=True))
    assert xpass["distance_m"] < 0 and xpass["high"] < 0 and xpass["under_pressure"] < 0
    assert 1.0 < GOALS_PER_TEAM_90 < 2.0


def test_odds_one_in():
    assert (odds_one_in(0.25), odds_one_in(0.07), odds_one_in(0.9), odds_one_in(0.0)) == (
        4, 14, 1, 0)


# --- win probability -----------------------------------------------------------------

def test_poisson_outcomes_by_hand():
    # Nothing left to play: the score decides.
    assert outcome_probs([1, 0], [0.0, 0.0]) == win_probability.Probs(1.0, 0.0, 0.0)
    assert outcome_probs([1, 1], [0.0, 0.0]).draw == 1.0
    # Only the home side may still score, at rate 1: a home win needs at least one goal,
    # 1 - e^-1; otherwise a draw; never an away win. (Sums stop at 10 goals: ~1e-7 off.)
    p = outcome_probs([0, 0], [1.0, 0.0])
    assert p.home == pytest.approx(1 - math.exp(-1), abs=1e-6)
    assert p.draw == pytest.approx(math.exp(-1), abs=1e-6) and p.away == pytest.approx(0)
    # Symmetric rates: symmetric result.
    q = outcome_probs([0, 0], [1.6, 1.6])
    assert q.home == pytest.approx(q.away) and q.home + q.draw + q.away == pytest.approx(1)
    assert poisson(2, 1.5) == pytest.approx(math.exp(-1.5) * 1.125)


def test_remaining_rate_shrinks_from_the_prior_to_the_match():
    assert remaining_rate(0.0, 0.0) == pytest.approx(GOALS_PER_TEAM_90)  # kickoff: prior
    assert remaining_rate(3.0, 90.0) == 0.0  # nothing left
    # Half time with 0.5 xG: rate 1.0 per 90; a = 0.5; 45 minutes left.
    assert remaining_rate(0.5, 45.0) == pytest.approx(0.5 * (0.5 * GOALS_PER_TEAM_90 + 0.5))
    assert played_minutes(2, 3000.0) == 90.0  # added time is no time left


def test_goal_swing_on_the_mini_match(mini):
    t = timeline(mini.events, mini.metadata)
    [goal] = t.shots
    assert goal.side == 1 and goal.shot.outcome == "goal"
    assert goal.win_if_scored > goal.win_before
    assert goal.leverage == pytest.approx(goal.xg * goal.swing)
    assert t.goals == (0, 1)


def test_win_probability_tool(mini):
    result = win_probability.run(mini, win_probability.Params(as_of_seq=19, scope="goals"))
    d = displays(result)
    shares = [int(d[k].rstrip("%")) for k in ("wp.team:T1.win", "wp.draw", "wp.team:T2.win")]
    assert 99 <= sum(shares) <= 101
    assert shares[2] > shares[0]  # T2 leads 0-1
    assert d["wp.goal@7.team"] == "Birch Rovers" and d["wp.goal@7.minute"] == "1'"


# --- shot quality --------------------------------------------------------------------

def test_shot_quality(mini):
    result = shot_quality.run(mini, shot_quality.Params(as_of_seq=19, scope="best"))
    d = displays(result)
    p = float(d["xg.shot@7.xg"])
    assert d["xg.shot@7.odds_one_in"] == str(odds_one_in(p))
    assert d["xg.team:T2.goals"] == "1" and d["xg.team:T2.xg"] == d["xg.shot@7.xg"]
    assert d["xg.team:T1.xg"] == "0.00"
    # A close, central shot: distance pushes the odds up against an average shot.
    assert float(d["xg.shot@7.effect.distance_m"]) > 0
