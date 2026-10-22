"""Fill the insight cache for every aired story of the demo matches, before judging.

Each story x persona x language runs once through the agent desk on Microsoft Foundry
and is stored where the app reads it (api/cache.py: PITCHSIDE_CACHE_BLOB_URL, or
PITCHSIDE_CACHE_DIR). Resumable: entries already in the store are skipped. Turns whose
narrator was unavailable are not stored, so a rerun retries them.

    uv run python scripts/precompute_insights.py --seeds 42,7,3
    uv run python scripts/precompute_insights.py --dry-run   # count, no model calls
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import AsyncExitStack

from azure.identity.aio import DefaultAzureCredential

from pitchside.agents.clients import foundry_chain
from pitchside.agents.desk import Desk
from pitchside.api.app import Game, demo_seeds
from pitchside.api.cache import InsightCache, cacheable, open_store
from pitchside.api.overlay import story_turn
from pitchside.simulator import simulate_match

PERSONAS = ("casual", "analyst")
LANGUAGES = ("en", "es")


async def run(seeds: list[int], dry_run: bool) -> None:
    async with AsyncExitStack() as stack:
        store = await open_store(stack)
        if store is None:
            raise SystemExit("set PITCHSIDE_CACHE_BLOB_URL or PITCHSIDE_CACHE_DIR")
        cache = InsightCache(store)
        models = [] if dry_run else foundry_chain(
            await stack.enter_async_context(DefaultAzureCredential()))
        tally: Counter[str] = Counter()
        tokens = 0
        for seed in seeds:
            game = Game.build(simulate_match(seed))
            match_id = game.match.metadata.match_id
            desk = Desk(game.match, models)
            for story in game.stories.values():
                for persona in PERSONAS:
                    for language in LANGUAGES:
                        turn = story_turn(story, persona, language)
                        key = InsightCache.key(match_id, turn)
                        if await cache.get(key) is not None:
                            tally["already cached"] += 1
                            continue
                        if dry_run:
                            tally["to compute"] += 1
                            continue
                        insight = await desk.run(turn)
                        tokens += insight.tokens
                        tally[insight.status] += 1
                        if cacheable(insight):
                            await cache.put(key, insight)
                        print(f"{match_id} {story.story_id} {persona}/{language}: "
                              f"{insight.status} ({insight.tokens} tokens)", flush=True)
        print(dict(tally), f"tokens={tokens}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default=",".join(map(str, demo_seeds())))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run([int(s) for s in args.seeds.split(",") if s], args.dry_run))


if __name__ == "__main__":
    main()
