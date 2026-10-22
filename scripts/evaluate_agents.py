"""Ablation: agent desk vs single agent, on held-out moments, against Microsoft Foundry.

    uv run python scripts/evaluate_agents.py [--n 40]

Configurations (same tools, model and prompts):
- solo           one agent calls tools and writes; no verifier, so what it writes airs
- solo+verifier  the same agent, checked by the deterministic verifier, one retry
- desk           analyst -> narrator -> verifier workflow, one retry

Moments come from test seeds 200+ (never used to write prompts or tune anything):
one per match, at a seeded minute, rotating persona (casual / analyst), language
(en / es) and kind (every fourth is a full-time recap). Raw runs go to
data/ablation_runs.jsonl; the summary to docs/EVALUATION.md (no timestamp).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import time
from pathlib import Path

from azure.identity.aio import DefaultAzureCredential

from pitchside.agents.clients import foundry_chain
from pitchside.agents.contracts import Insight, TurnRequest
from pitchside.agents.desk import Desk
from pitchside.agents.solo import run_solo
from pitchside.events.match import Match
from pitchside.simulator import simulate_match

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ("solo", "solo+verifier", "desk")
# Each round uses fresh seeds, so a change made after reading one round's results is
# measured on moments it was not designed against.
ROUNDS = {"v1": 200, "v2": 240}
ROUND = "v1"  # set from --round in main()
FIRST_SEED = ROUNDS[ROUND]


def runs_path() -> Path:
    return ROOT / "data" / f"ablation_runs_{ROUND}.jsonl"


def report_path() -> Path:
    return ROOT / "docs" / "evaluation" / f"ablation-{ROUND}.md"


def moments(n: int) -> list[tuple[int, TurnRequest]]:
    out = []
    for i, seed in enumerate(range(FIRST_SEED, FIRST_SEED + n)):
        match = simulate_match(seed)
        kind = "recap" if i % 4 == 3 else "moment"
        rng = random.Random(seed)
        seq = (match.events[-1].seq if kind == "recap"
               else rng.randrange(len(match.events) // 6, len(match.events) - 1))
        out.append((seed, TurnRequest(as_of_seq=seq, kind=kind,
                                      persona=("casual", "analyst")[i % 2],
                                      language=("en", "es")[(i // 2) % 2])))
    return out


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def record(config: str, seed: int, insight: Insight | None, seconds: float,
           error: str | None) -> dict:
    bad = [] if insight is None else [c for c in insight.sentences if not c.ok]
    return {
        "config": config, "seed": seed,
        "request": None if insight is None else insight.request.model_dump(),
        "status": None if insight is None else insight.status,
        "attempts": None if insight is None else insight.attempts,
        "sentences": 0 if insight is None else len(insight.sentences),
        "aired_with_errors": bool(bad),
        "errors_aired": [p for c in bad for p in c.problems],
        "tokens": None if insight is None else insight.tokens,
        "seconds": round(seconds, 2), "error": error,
    }


async def run_config(config: str, match: Match, chain: list, request: TurnRequest) -> Insight:
    if config == "desk":
        return await Desk(match, chain).run(request)
    return await run_solo(match, chain, request, verify_and_retry=config == "solo+verifier")


def cell(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({k / n:.0%}, 95% CI {lo:.0%}-{hi:.0%})"


def previous_runs() -> list[dict]:
    """Runs already recorded, so an interrupted evaluation resumes where it stopped."""
    path = runs_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def run_all(n: int) -> list[dict]:
    rows = previous_runs()
    done = {(r["seed"], r["config"]) for r in rows if r["error"] is None}
    rows = [r for r in rows if (r["seed"], r["config"]) in done]  # retry errored runs
    runs_path().parent.mkdir(parents=True, exist_ok=True)
    async with DefaultAzureCredential() as credential:
        chain = foundry_chain(credential)
        with runs_path().open("w", encoding="utf-8", newline="\n") as out:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            for seed, request in moments(n):
                match = simulate_match(seed)
                for config in CONFIGS:
                    if (seed, config) in done:
                        continue
                    t0, insight, error = time.perf_counter(), None, None
                    try:
                        insight = await run_config(config, match, chain, request)
                    except Exception as err:  # noqa: BLE001 - record and move on
                        error = f"{type(err).__name__}: {err}"
                    row = record(config, seed, insight, time.perf_counter() - t0, error)
                    rows.append(row)
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                    print(f"{seed} {config:14s} {row['status']} {row['seconds']}s "
                          f"{row['tokens']} tok {'ERR ' + error if error else ''}")
    return rows


def summarize(rows: list[dict], n_moments: int) -> str:
    lines = [
        f"# Agent ablation, round {ROUND}: desk vs single agent",
        "",
        f"Generated by `uv run python scripts/evaluate_agents.py --round {ROUND}`. Same "
        "model (Microsoft "
        "Foundry, gpt-4.1-mini with gpt-5-mini fallback), tools and prompts in every "
        f"configuration; {n_moments} held-out moments from test seeds {FIRST_SEED}+, one "
        "per match, rotating persona, language and kind (every fourth is a recap).",
        "",
        "- **Aired with errors:** narratives that would reach viewers with at least one "
        "sentence failing verification (unsupported or misattributed number, misspelled "
        "name). Without a verifier, everything a model writes airs.",
        "- **Published:** a narrative airs (verified, or unverified for `solo`); otherwise "
        "the viewer sees evidence only.",
        "",
        "| Config | Runs | Aired with errors | Published | Verified first time | "
        "Latency p50 | Tokens mean |",
        "|---|---|---|---|---|---|---|",
    ]
    for config in CONFIGS:
        rs = [r for r in rows if r["config"] == config and r["error"] is None]
        n = len(rs)
        if n == 0:
            lines.append(f"| {config} | 0 | - | - | - | - | - |")
            continue
        aired_bad = sum(r["aired_with_errors"] for r in rs)
        published = sum(r["status"] in ("verified", "verified_after_retry", "unverified")
                        for r in rs)
        first = sum(r["status"] == "verified" for r in rs)
        lines.append(
            f"| {config} | {n} | {cell(aired_bad, n)} | {cell(published, n)} | "
            f"{cell(first, n)} | "
            f"{statistics.median(r['seconds'] for r in rs):.1f} s | "
            f"{statistics.fmean(r['tokens'] or 0 for r in rs):.0f} |"
        )
    errors = [r for r in rows if r["error"]]
    lines += ["", f"Runs that errored (excluded above): {len(errors)}.", ""]
    problems = [p for r in rows if r["config"] == "solo" for p in r["errors_aired"]]
    if problems:
        lines += ["Examples of errors the unverified single agent would have aired:", ""]
        lines += [f"- {p}" for p in problems[:8]]
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    global ROUND, FIRST_SEED
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=40, help="number of held-out moments")
    parser.add_argument("--round", choices=sorted(ROUNDS), default="v1")
    args = parser.parse_args()
    ROUND, FIRST_SEED = args.round, ROUNDS[args.round]
    rows = asyncio.run(run_all(args.n))
    wanted = {seed for seed, _ in moments(args.n)}
    rows = [r for r in rows if r["seed"] in wanted]
    report_path().parent.mkdir(parents=True, exist_ok=True)
    report_path().write_bytes(summarize(rows, args.n).encode())
    print(f"\nwrote {report_path()}")


if __name__ == "__main__":
    main()
