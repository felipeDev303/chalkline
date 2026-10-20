"""Run the desk on one moment of a match and print the insight.

    uv run python scripts/try_agents.py --match data/match_42.jsonl --minute 63 \
        --persona casual --lang es

Uses Microsoft Foundry when FOUNDRY_PROJECT_ENDPOINT and AI_MODEL_DEPLOYMENT are set
in the environment (keyless: `az login`); otherwise there is no model, and the desk
shows its evidence-only fallback.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from azure.identity.aio import DefaultAzureCredential

from pitchside.agents.clients import foundry_chain
from pitchside.agents.contracts import TurnRequest
from pitchside.agents.desk import Desk
from pitchside.events.match import read_jsonl


def seq_at_minute(match, minute: int) -> int:
    period, clock = (1, (minute - 1) * 60) if minute <= 45 else (2, (minute - 46) * 60)
    seen = [e.seq for e in match.events if (e.period, e.clock_s) <= (period, clock + 59)]
    return seen[-1] if seen else match.events[0].seq


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--match", type=Path, required=True)
    p.add_argument("--minute", type=int, default=90)
    p.add_argument("--kind", choices=("moment", "recap", "question"), default="moment")
    p.add_argument("--question")
    p.add_argument("--persona", choices=("casual", "analyst"), default="casual")
    p.add_argument("--lang", choices=("en", "es"), default="en")
    args = p.parse_args()

    match = read_jsonl(args.match)
    request = TurnRequest(as_of_seq=seq_at_minute(match, args.minute), kind=args.kind,
                          persona=args.persona, language=args.lang, question=args.question)
    if os.environ.get("FOUNDRY_PROJECT_ENDPOINT"):
        async with DefaultAzureCredential() as credential:
            insight = await Desk(match, foundry_chain(credential)).run(request)
    else:
        print("No FOUNDRY_PROJECT_ENDPOINT in the environment: running without a model.\n")
        insight = await Desk(match, []).run(request)

    print(f"status: {insight.status} (attempts {insight.attempts}, model {insight.model})")
    for note in insight.notes:
        print(f"note: {note}")
    if insight.failure:
        print(f"failure: {insight.failure}")
    for s in insight.sentences:
        print(f"- [{s.kind}] {s.text}  <- {', '.join(s.evidence_ids) or 'no citation'}")
    print("\nevidence:")
    for f in insight.evidence:
        print(f"  {f.evidence_id} = {f.display}  ({f.label})")


if __name__ == "__main__":
    asyncio.run(main())
