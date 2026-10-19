"""Seeded synthetic match simulator (events only, no player tracking)."""

from pitchside.simulator.engine import SimulatedMatch, simulate_match
from pitchside.simulator.io import read_jsonl, to_jsonl_bytes, write_jsonl
from pitchside.simulator.params import DEFAULT_PARAMS, SimParams

__all__ = [
    "DEFAULT_PARAMS",
    "SimParams",
    "SimulatedMatch",
    "read_jsonl",
    "simulate_match",
    "to_jsonl_bytes",
    "write_jsonl",
]
