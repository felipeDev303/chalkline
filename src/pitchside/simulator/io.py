"""JSONL persistence: line 1 is `MatchMetadata`, every further line one `MatchEvent`.

Files are written as raw bytes with `\\n` line endings so the same seed produces
byte-identical output on every OS.
"""

from __future__ import annotations

from pathlib import Path

from pitchside.events.schema import MatchEventAdapter, MatchMetadata
from pitchside.simulator.engine import SimulatedMatch


def to_jsonl_bytes(match: SimulatedMatch) -> bytes:
    lines = [match.metadata.model_dump_json().encode()]
    lines.extend(MatchEventAdapter.dump_json(ev) for ev in match.events)
    return b"\n".join(lines) + b"\n"


def write_jsonl(match: SimulatedMatch, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_jsonl_bytes(match))


def read_jsonl(path: Path) -> SimulatedMatch:
    lines = path.read_bytes().splitlines()
    return SimulatedMatch(
        metadata=MatchMetadata.model_validate_json(lines[0]),
        events=tuple(MatchEventAdapter.validate_json(line) for line in lines[1:]),
    )
