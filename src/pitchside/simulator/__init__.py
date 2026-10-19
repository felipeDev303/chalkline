"""Seeded synthetic match simulator (events only, no player tracking).

Returns `pitchside.events.match.Match`; persistence lives in that module too.
"""

from pitchside.simulator.engine import simulate_match
from pitchside.simulator.params import DEFAULT_PARAMS, SimParams

__all__ = ["DEFAULT_PARAMS", "SimParams", "simulate_match"]
