"""A match as one unit (metadata + ordered events) and its JSONL persistence.

JSONL layout: line 1 is `MatchMetadata`, every further line one `MatchEvent`.
Files are raw bytes with `\\n` line endings, so the same match gives the same bytes
on every OS.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pitchside.events.schema import MatchEvent, MatchEventAdapter, MatchMetadata


class Match(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: MatchMetadata
    events: tuple[MatchEvent, ...]


def attacks_high_x(metadata: MatchMetadata, team_id: str, period: int) -> bool:
    """Whether `team_id` attacks towards x = 105 in `period`."""
    if team_id == metadata.home.team_id:
        is_home = True
    elif team_id == metadata.away.team_id:
        is_home = False
    else:
        raise ValueError(f"unknown team_id {team_id!r}")
    home_high = metadata.home_attacks_high_x_in_period_1 == (period == 1)
    return home_high == is_home


def to_jsonl_bytes(match: Match) -> bytes:
    lines = [match.metadata.model_dump_json().encode()]
    lines.extend(MatchEventAdapter.dump_json(ev) for ev in match.events)
    return b"\n".join(lines) + b"\n"


def write_jsonl(match: Match, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_jsonl_bytes(match))


def read_jsonl(path: Path) -> Match:
    lines = path.read_bytes().splitlines()
    return Match(
        metadata=MatchMetadata.model_validate_json(lines[0]),
        events=tuple(MatchEventAdapter.validate_json(line) for line in lines[1:]),
    )
