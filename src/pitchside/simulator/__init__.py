"""Seeded synthetic match simulator (events only, no player tracking).

Returns `pitchside.events.match.Match`; persistence lives in that module too.
"""

from pitchside.simulator.engine import simulate_match, simulate_match_with_truth
from pitchside.simulator.params import DEFAULT_PARAMS, SimParams
from pitchside.simulator.regimes import MatchTruth

__all__ = ["DEFAULT_PARAMS", "MatchTruth", "SimParams", "simulate_match",
           "simulate_match_with_truth"]
