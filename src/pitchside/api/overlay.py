"""The timed overlay: everything the screen shows next to the match at one moment.

`GET /api/matches/{id}/overlay?as_of_seq=N` returns an `Overlay`, built only from
events up to N and the producer's air schedule up to N. It is deterministic and
needs no model: headlines come from templates, the verified narrative is a separate,
asynchronous call (`POST /api/matches/{id}/insights`). The JSON Schema is served at
`/api/overlay/schema` and documented in docs/API.md; bump OVERLAY_VERSION on change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pitchside.agents.contracts import Language, Persona, TurnRequest
from pitchside.api.producer import Story, on_air
from pitchside.api.templates import headline
from pitchside.events.match import Match
from pitchside.events.schema import MatchEvent
from pitchside.metrics._timeline import match_minute, possessor_after, view
from pitchside.metrics.contract import Fact, minute_display
from pitchside.metrics.off_ball import pass_credits
from pitchside.metrics.win_probability import timeline

OVERLAY_VERSION = "1.1.0"  # 1.1.0: win_probability


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class XYOut(_Strict):
    x: float
    y: float


class PlayerDot(_Strict):
    player_id: str
    team_id: str
    shirt_number: int
    x: float
    y: float


class Ghost(_Strict):
    """The run that made a pass: where the runner was, and would have been without it."""

    player_id: str
    recipient_id: str
    with_xy: XYOut  # where the runner was when the pass was played
    without_xy: XYOut  # where they would have been, moving only with their team
    pass_from: XYOut
    pass_to: XYOut
    frame: tuple[PlayerDot, ...]  # everyone at the moment of the pass


class StoryOut(_Strict):
    story_id: str
    kind: str
    seq: int  # event the story is about
    aired_at_seq: int  # when the producer put it on air
    importance: float
    team_id: str | None
    player_id: str | None
    headline: dict[Literal["en", "es"], str]
    facts: tuple[Fact, ...]  # every number in the headline is one of these
    ghost: Ghost | None = None


class LastEvent(_Strict):
    seq: int
    type: str
    team_id: str
    player_id: str | None
    location: XYOut
    end_location: XYOut | None = None  # passes
    outcome: str | None = None


class WinProbability(_Strict):
    """Chance of each final result from here (metrics/win_probability.py)."""

    home: float
    draw: float
    away: float


class Overlay(_Strict):
    overlay_version: Literal["1.1.0"] = OVERLAY_VERSION
    match_id: str
    as_of_seq: int
    period: int
    clock_s: float
    minute: str
    score: dict[str, int]  # team_id -> goals
    win_probability: WinProbability
    possession_team_id: str | None
    last_event: LastEvent
    players: tuple[PlayerDot, ...]  # latest known positions; empty without tracking
    stories: tuple[StoryOut, ...]  # on air by as_of_seq, newest first


def _xy(x: float, y: float) -> XYOut:
    return XYOut(x=round(x, 2), y=round(y, 2))


def _dots(e: MatchEvent, shirts: dict[str, tuple[str, int]]) -> tuple[PlayerDot, ...]:
    if e.frame is None:
        return ()
    return tuple(PlayerDot(player_id=p.player_id, team_id=shirts[p.player_id][0],
                           shirt_number=shirts[p.player_id][1], x=round(p.x, 2),
                           y=round(p.y, 2)) for p in e.frame.players)


def shirts(match: Match) -> dict[str, tuple[str, int]]:
    """player_id -> (team_id, shirt number)."""
    return {p.player_id: (t.team_id, p.shirt_number)
            for t in (match.metadata.home, match.metadata.away) for p in t.players}


def ghost(match: Match, story: Story) -> Ghost | None:
    """Recompute the credited run of a decisive_run story, for drawing."""
    m = story.moment
    if m.kind != "decisive_run":
        return None
    index = next(i for i, e in enumerate(match.events) if e.seq == m.seq)
    p = match.events[index]
    runner = next((c for c in pass_credits(match.events, index, match.metadata)
                   if c.player_id == m.player_id), None)
    if runner is None or p.type != "pass":
        return None
    return Ghost(player_id=runner.player_id, recipient_id=p.recipient_id or "",
                 with_xy=_xy(*runner.now_xy), without_xy=_xy(*runner.without_xy),
                 pass_from=_xy(p.location.x, p.location.y),
                 pass_to=_xy(p.end_location.x, p.end_location.y),
                 frame=_dots(p, shirts(match)))


def story_out(match: Match, story: Story) -> StoryOut:
    m = story.moment
    return StoryOut(
        story_id=story.story_id, kind=m.kind, seq=m.seq, aired_at_seq=story.aired_at_seq,
        importance=m.importance, team_id=m.team_id, player_id=m.player_id,
        headline={lang: headline(m, match.metadata, lang) for lang in ("en", "es")},
        facts=m.facts, ghost=ghost(match, story))


def story_turn(story: StoryOut, persona: Persona, language: Language) -> TurnRequest:
    """The desk request that explains one story, as the producer knew it when it aired."""
    return TurnRequest(as_of_seq=story.aired_at_seq, kind="question", persona=persona,
                       language=language,
                       question=f"Explain why this moment matters: {story.headline['en']}")


def overlay(match: Match, schedule: list[Story], as_of_seq: int,
            stories: dict[str, StoryOut] | None = None) -> Overlay:
    """The overlay at `as_of_seq`. Pass `stories` (by story_id) to reuse built stories."""
    v = view(match, as_of_seq)
    events = v.events
    last = events[-1]
    score = {t.team_id: 0 for t in v.teams}
    for e in events:
        if e.type == "shot" and e.outcome == "goal":
            score[e.team_id] += 1
    framed = next((e for e in reversed(events) if e.frame is not None), None)
    minute, added = match_minute(last.period, last.clock_s)
    built = stories if stories is not None else {}
    aired = tuple(built.get(s.story_id) or story_out(match, s)
                  for s in on_air(schedule, v.as_of_seq))
    now = timeline(events, match.metadata).now
    return Overlay(
        match_id=match.metadata.match_id, as_of_seq=v.as_of_seq, period=last.period,
        clock_s=last.clock_s, minute=minute_display(minute, added), score=score,
        win_probability=WinProbability(home=round(now.home, 3), draw=round(now.draw, 3),
                                       away=round(now.away, 3)),
        possession_team_id=possessor_after(events)[-1],
        last_event=LastEvent(
            seq=last.seq, type=last.type, team_id=last.team_id, player_id=last.player_id,
            location=_xy(last.location.x, last.location.y),
            end_location=(_xy(last.end_location.x, last.end_location.y)
                          if last.type == "pass" else None),
            outcome=getattr(last, "outcome", None)),
        players=_dots(framed, shirts(match)) if framed is not None else (),
        stories=aired,
    )
