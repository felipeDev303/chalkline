"""HTTP API and static UI, in one process.

    GET  /api/health
    GET  /api/matches                          demo matches (simulated at startup)
    GET  /api/matches/{id}                     teams and players
    GET  /api/matches/{id}/overlay?as_of_seq=  timed overlay (deterministic, instant)
    GET  /api/matches/{id}/stories?as_of_seq=  every story aired so far (replay chapters)
    GET  /api/overlay/schema                   JSON Schema of the overlay
    GET  /api/tools                            tool schemas (same as the MCP server)
    POST /api/matches/{id}/tools/{name}        run one tool -> ToolResult
    POST /api/matches/{id}/insights            agent desk -> verified Insight (cached)
    POST /api/matches/{id}/stories/{sid}/insights   the same, for one aired story

The replay is client-driven: the UI advances as_of_seq and polls the overlay, so the
server keeps no session state. Insights are cached by request (memory, then Azure Blob
or a local folder: api/cache.py) and rate-limited per client; cached answers are free.
Without FOUNDRY_PROJECT_ENDPOINT there is no model and every insight is evidence
only, which is still a valid answer; it is neither cached nor rate-limited.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from pitchside.agents.clients import ModelChain, foundry_chain
from pitchside.agents.contracts import Insight, Language, Persona, TurnRequest
from pitchside.agents.desk import Desk
from pitchside.api.cache import DirStore, InsightCache, Store, cacheable, open_store
from pitchside.api.overlay import (
    OVERLAY_VERSION,
    Overlay,
    StoryOut,
    overlay,
    story_out,
    story_turn,
)
from pitchside.api.producer import Story, air_schedule
from pitchside.events.match import Match
from pitchside.events.schema import SCHEMA_VERSION
from pitchside.metrics.contract import ToolError, ToolResult
from pitchside.metrics.registry import call, json_schemas
from pitchside.simulator import simulate_match

STATIC_DIR = Path(__file__).parent / "static"
MAX_QUESTION_CHARS = 300


@dataclass
class Game:
    match: Match
    schedule: list[Story]
    stories: dict[str, StoryOut]

    @classmethod
    def build(cls, match: Match) -> Game:
        schedule = air_schedule(match)
        return cls(match, schedule, {s.story_id: story_out(match, s) for s in schedule})


@dataclass
class RateLimit:
    per_minute: int
    hits: dict[str, deque[float]] = field(default_factory=dict)

    def allow(self, client: str, now: float) -> bool:
        q = self.hits.setdefault(client, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def demo_seeds() -> list[int]:
    return [int(s) for s in os.environ.get("PITCHSIDE_DEMO_SEEDS", "42,7,3").split(",") if s]


async def foundry_models(stack: AsyncExitStack) -> ModelChain:
    """Foundry chain when FOUNDRY_PROJECT_ENDPOINT is set; otherwise no models."""
    if not os.environ.get("FOUNDRY_PROJECT_ENDPOINT"):
        return []
    from azure.identity.aio import DefaultAzureCredential

    credential = await stack.enter_async_context(DefaultAzureCredential())
    return foundry_chain(credential)


ModelsFactory = Callable[[AsyncExitStack], Awaitable[ModelChain]]
StoreFactory = Callable[[AsyncExitStack], Awaitable[Store | None]]


class Audience(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    persona: Persona
    language: Language


def create_app(seeds: list[int] | None = None, models: ModelsFactory = foundry_models,
               store: StoreFactory | None = None, cache_dir: Path | None = None,
               insights_per_minute: int | None = None, concurrent_desks: int = 2) -> FastAPI:
    """`store` defaults to Blob or a folder from the environment (see api/cache.py);
    `cache_dir` forces a folder (tests)."""
    seeds = seeds if seeds is not None else demo_seeds()
    per_minute = insights_per_minute or int(os.environ.get("PITCHSIDE_INSIGHTS_PER_MIN", "6"))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            app.state.models = await models(stack)
            if store is not None:
                cache.store = await store(stack)
            elif cache_dir is not None:
                cache.store = DirStore(cache_dir)
            else:
                cache.store = await open_store(stack)
            yield

    app = FastAPI(title="Pitchside", version=OVERLAY_VERSION, lifespan=lifespan,
                  description="Explainable match intelligence from synthetic football events.")
    games: dict[str, Game] = {}
    for seed in seeds:
        match = simulate_match(seed)
        games[match.metadata.match_id] = Game.build(match)
    cache = InsightCache()
    limit = RateLimit(per_minute)
    desks = asyncio.Semaphore(concurrent_desks)
    app.state.models = []

    def game(match_id: str) -> Game:
        if match_id not in games:
            raise HTTPException(404, f"unknown match {match_id!r}")
        return games[match_id]

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "schema_version": SCHEMA_VERSION,
                "overlay_version": OVERLAY_VERSION, "matches": len(games),
                "models": [label for label, _ in app.state.models]}

    @app.get("/api/matches")
    def matches() -> list[dict[str, Any]]:
        return [{"match_id": mid, "seed": g.match.metadata.seed,
                 "home": g.match.metadata.home.name, "away": g.match.metadata.away.name,
                 "competition": g.match.metadata.competition,
                 "first_seq": g.match.events[0].seq, "last_seq": g.match.events[-1].seq}
                for mid, g in games.items()]

    @app.get("/api/matches/{match_id}")
    def match_metadata(match_id: str) -> dict[str, Any]:
        g = game(match_id)
        return {**g.match.metadata.model_dump(mode="json"),
                "first_seq": g.match.events[0].seq, "last_seq": g.match.events[-1].seq}

    @app.get("/api/matches/{match_id}/overlay", response_model=Overlay)
    def get_overlay(match_id: str, as_of_seq: int = Query(ge=0)) -> Overlay:
        g = game(match_id)
        try:
            return overlay(g.match, g.schedule, as_of_seq, g.stories)
        except ToolError as err:
            raise HTTPException(422, str(err)) from err

    @app.get("/api/matches/{match_id}/stories", response_model=list[StoryOut])
    def stories(match_id: str, as_of_seq: int | None = Query(None, ge=0)) -> list[StoryOut]:
        """Everything aired by as_of_seq (default: the whole replay), in airing order."""
        g = game(match_id)
        upto = g.match.events[-1].seq if as_of_seq is None else as_of_seq
        return [g.stories[s.story_id] for s in g.schedule if s.aired_at_seq <= upto]

    @app.get("/api/overlay/schema")
    def overlay_schema() -> dict[str, Any]:
        return Overlay.model_json_schema()

    @app.get("/api/tools")
    def tools() -> list[dict[str, Any]]:
        return json_schemas()

    @app.post("/api/matches/{match_id}/tools/{name}", response_model=ToolResult)
    def run_tool(match_id: str, name: str,
                 arguments: dict[str, Any] = Body(...)) -> ToolResult:  # noqa: B008
        try:
            return call(name, game(match_id).match, arguments)
        except ToolError as err:
            raise HTTPException(422, str(err)) from err

    async def answer(match_id: str, turn: TurnRequest, request: Request) -> Insight:
        g = game(match_id)
        key = InsightCache.key(match_id, turn)
        cached = await cache.get(key)
        if cached is not None:
            return cached
        client = request.client.host if request.client else "unknown"
        # Without models the desk is deterministic and free: nothing to limit.
        if app.state.models and not limit.allow(client, time.monotonic()):
            raise HTTPException(429, "too many new insights; cached ones are still free")
        async with desks:
            insight = await Desk(g.match, app.state.models).run(turn)
        if cacheable(insight):
            await cache.put(key, insight)
        return insight

    @app.post("/api/matches/{match_id}/insights", response_model=Insight)
    async def insights(match_id: str, turn: TurnRequest, request: Request) -> Insight:
        if turn.question is not None and len(turn.question) > MAX_QUESTION_CHARS:
            raise HTTPException(422, f"question longer than {MAX_QUESTION_CHARS} characters")
        return await answer(match_id, turn, request)

    @app.post("/api/matches/{match_id}/stories/{story_id}/insights", response_model=Insight)
    async def story_insight(match_id: str, story_id: str, audience: Audience,
                            request: Request) -> Insight:
        story = game(match_id).stories.get(story_id)
        if story is None:
            raise HTTPException(404, f"unknown story {story_id!r}")
        turn = story_turn(story, audience.persona, audience.language)
        return await answer(match_id, turn, request)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return app
