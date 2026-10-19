"""CLI: uv run python -m pitchside.simulator --seed 42 --out data/match_42.jsonl"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from pitchside.events.match import write_jsonl
from pitchside.simulator import simulate_match


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pitchside.simulator",
        description="Generate one synthetic match as JSONL (line 1 metadata, then events).",
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, help="default: data/match_<seed>.jsonl")
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be >= 0")
    out: Path = args.out or Path("data") / f"match_{args.seed}.jsonl"
    match = simulate_match(args.seed)
    write_jsonl(match, out)
    print(f"wrote {len(match.events)} events to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
