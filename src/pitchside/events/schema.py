"""Synthetic match event schema.

Coordinates are metres on a 105x68 pitch, origin at bottom-left. Which goal each
team attacks is declared in `MatchMetadata.home_attacks_high_x_in_period_1`; the
teams swap ends at half time.
Derived quantities (pass distance, ball speed, difficulty) are NOT stored here;
they are computed deterministically in `pitchside.metrics`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = "0.3.0"
PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Point(Strict):
    x: Annotated[float, Field(ge=0, le=PITCH_LENGTH_M)]
    y: Annotated[float, Field(ge=0, le=PITCH_WIDTH_M)]


# --- match metadata -------------------------------------------------------

class Player(Strict):
    player_id: str
    name: str
    shirt_number: Annotated[int, Field(ge=1, le=99)]
    position: Literal["GK", "DF", "MF", "FW"]


class Team(Strict):
    team_id: str
    name: str
    short_name: Annotated[str, Field(max_length=4)]
    players: tuple[Player, ...]


class MatchMetadata(Strict):
    schema_version: Literal["0.3.0"] = SCHEMA_VERSION
    match_id: str
    seed: int
    home: Team
    away: Team
    competition: str
    venue: str
    kickoff_utc: datetime
    # True: home attacks towards x = 105 in period 1 (and towards x = 0 in period 2).
    home_attacks_high_x_in_period_1: bool
    synthetic: Literal[True] = True


# --- positions --------------------------------------------------------------

class PlayerXY(Strict):
    player_id: str
    x: Annotated[float, Field(ge=0, le=PITCH_LENGTH_M)]
    y: Annotated[float, Field(ge=0, le=PITCH_WIDTH_M)]


class Frame(Strict):
    """Where every player on the pitch stood when the event happened (absolute metres)."""

    players: tuple[PlayerXY, ...]


# --- events ---------------------------------------------------------------

class EventBase(Strict):
    schema_version: Literal["0.3.0"] = SCHEMA_VERSION
    event_id: str
    match_id: str
    seq: Annotated[int, Field(ge=0)]           # monotonic per match
    period: Literal[1, 2]
    clock_s: Annotated[float, Field(ge=0)]     # seconds since period start
    team_id: str
    player_id: str | None
    location: Point
    # Positions of all players at the event; None when the feed has no tracking.
    frame: Frame | None = None


class Pass(EventBase):
    type: Literal["pass"] = "pass"
    end_location: Point
    recipient_id: str | None
    duration_s: Annotated[float, Field(gt=0)]
    outcome: Literal["complete", "incomplete", "out", "offside"]
    height: Literal["ground", "low", "high"]
    under_pressure: bool


class Shot(EventBase):
    type: Literal["shot"] = "shot"
    outcome: Literal["goal", "saved", "off_target", "blocked", "post"]
    body_part: Literal["right_foot", "left_foot", "head", "other"]
    speed_kmh: Annotated[float, Field(gt=0, le=200)]
    under_pressure: bool


class Tackle(EventBase):
    type: Literal["tackle"] = "tackle"
    opponent_id: str
    won: bool


class Pressure(EventBase):
    """A defender closing down the ball carrier.

    `team_id` / `player_id` are the pressing team and player;
    `target_player_id` is the pressed ball carrier (an opponent).
    `location` is the ball position at pressure time (schema 0.x); it will become the
    presser's own position once player tracking lands.
    """

    type: Literal["pressure"] = "pressure"
    target_player_id: str
    duration_s: Annotated[float, Field(gt=0)]


class PossessionChange(EventBase):
    """The ball changes team.

    `team_id` / `player_id` are the team and player gaining possession;
    `from_team_id` is the team losing it.
    """

    type: Literal["possession_change"] = "possession_change"
    from_team_id: str
    cause: Literal["tackle", "interception", "shot_end", "out_of_play", "foul", "other"]


class Phase(EventBase):
    type: Literal["phase"] = "phase"
    phase: Literal["kickoff", "half_time", "full_time"]


MatchEvent = Annotated[
    Pass | Shot | Tackle | Pressure | PossessionChange | Phase,
    Field(discriminator="type"),
]
MatchEventAdapter: TypeAdapter[MatchEvent] = TypeAdapter(MatchEvent)
