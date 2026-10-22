"""Check the simulator against its realism targets and write docs/data/CALIBRATION.md.

Usage: uv run python scripts/calibrate.py   (~1 min: simulates ROBUSTNESS_SEEDS)
Exits 1 if a target fails on CALIBRATION_SEEDS or the long-run mean is tight
(see realism.MIN_MARGIN_SE). The report has no timestamp, so it only changes
when the simulator's output changes.
"""

from __future__ import annotations

import math
import statistics
import sys
from collections import Counter
from pathlib import Path

from detector_eval import (
    DEV_SEEDS,
    TEST_SEEDS,
    WINDOW_TOLERANCE,
    load,
    score_chaos,
    score_shifts,
)
from off_ball_eval import score as score_off_ball
from xt_eval import calibrate as calibrate_xt

from pitchside.events.schema import SCHEMA_VERSION
from pitchside.metrics import off_ball
from pitchside.metrics.pressure_shift import THRESHOLDS as PRESSURE_THRESHOLDS
from pitchside.simulator import simulate_match
from pitchside.simulator.realism import (
    CALIBRATION_SEEDS,
    MIN_MARGIN_SE,
    ROBUSTNESS_SEEDS,
    TARGETS,
    summarize,
)

OUT = Path(__file__).resolve().parents[1] / "docs" / "data" / "CALIBRATION.md"

# Findings from reading generated matches line by line (2026-10-19). Static: a record
# of what the aggregate targets did not catch and how each issue was fixed.
QUALITATIVE_REVIEW = """\
## Qualitative review

Aggregate targets can pass while the event sequence still reads wrong, so matches
were also read event by event (seed 42, stretches of ~30 lines). Issues found:

| Issue | Cause | Before -> after |
|---|---|---|
| Players stuck on the touchline (runs of events at y = 0 or 68) | Team shape shifts towards the ball and pushed wide players off the pitch; clamping left them on the line | Shape stays 2 m inside the lines, in-play passes and carries 0.5 m; on-line positions now only at throw-ins |
| Short passes too fast | Ball speed did not depend on pass length | Passes < 8 m faster than 12 m/s: 80% -> 0.8% |
| Striker in the box passing 30+ m backwards | Receiver choice did not penalise long backward passes | Passes from the box going back > 30 m: 24% -> 4.2% |
| Pressure at the instant of a kickoff | No notion of a set piece | No pressure or tackle at any restart |
| Kickoff pass going out of play | Kickoff treated as an ordinary pass | Short pass to a midfielder, always complete |
| 35 m lofted throw-ins | Throw-in treated as an ordinary pass | Only to teammates within 25 m, thrown (`low`) |
"""  # noqa: E501 - Markdown table rows cannot be wrapped


def _known_limitations(mean_pass_length_m: float) -> str:
    return f"""\
## Known limitations

- No corners: a ball out over the goal line is always a goal kick.
- Mean pass length is {mean_pass_length_m:.1f} m over the robustness seeds, slightly
  long for professional football (typically around 20 m).
- pressure_shift compares 5-minute windows of a few pressures each, so counting noise
  limits it: it finds clear increases in pressing but almost never a drop, which is
  smaller than its absolute threshold (see recall by cause above).
- Planted regimes change only pressing intensity; other tactics (pace, width, line
  height) are not simulated yet.
- Cross-OS byte identity is designed in (seeded Mersenne Twister streams, only IEEE-exact
  arithmetic and `math.sqrt`, no libm transcendentals) but is only proven by the
  golden SHA-256 test. If Windows and Linux ever produce different bytes, the hash
  from Linux CI is canonical.
"""


FP_PER_MATCH_BEFORE_STAGE_B = 1.2  # pressure_shift on regime-free matches, seeds 0-199


def _detector_section() -> str:
    data = load(TEST_SEEDS)
    s = score_shifts(data, PRESSURE_THRESHOLDS["min_delta_per_min"],
                     PRESSURE_THRESHOLDS["min_relative_change"])
    chaos = score_chaos(data)
    treated = sum(1 for d in data if not d.truth.control_group)
    lines = [
        "## Detector evaluation (planted regimes)",
        "",
        "Simulated matches carry planted pressing changes (ground truth in "
        "`<match>.truth.json`, never in the event stream): seeded spells of pressing "
        "harder or dropping off, and a trailing team pressing harder from 60'. Seeds "
        "divisible by 5 are a control group with no regimes.",
        "",
        f"Thresholds were tuned on dev seeds {_seeds(DEV_SEEDS)} with "
        "`scripts/tune_detectors.py` (rule: best F1 with at most 1.0 false positive per "
        f"control match). Reported here on test seeds {_seeds(TEST_SEEDS)}, never used "
        f"for tuning: {treated} treated and {s.control_matches} control matches. A "
        "detection is a hit if it has the same team and direction as a planted change "
        f"within +/-{WINDOW_TOLERANCE} window.",
        "",
        "| pressure_shift | Value |",
        "|---|---|",
        f"| thresholds | delta >= {PRESSURE_THRESHOLDS['min_delta_per_min']:g}/min, "
        f"relative >= {PRESSURE_THRESHOLDS['min_relative_change']:g} |",
        f"| planted changes / detections (treated) | {s.planted} / {s.detections} |",
        f"| precision | {s.precision:.3f} |",
        f"| recall | {s.recall:.3f} |",
        f"| F1 | {s.f1:.3f} |",
        f"| false positives per control match | {s.fp_per_control_match:.2f} "
        f"(before stage B: {FP_PER_MATCH_BEFORE_STAGE_B:g}) |",
        "",
        "| Recall by cause | Planted | Hit | Recall |",
        "|---|---|---|---|",
    ]
    for cause in sorted(s.planted_by_cause):
        n, hit = s.planted_by_cause[cause], s.hits_by_cause[cause]
        lines.append(f"| {cause} | {n} | {hit} | {hit / n:.3f} |")
    lines += [
        "",
        "| control_vs_chaos (treated matches) | Windows | Chaos | Chaos rate |",
        "|---|---|---|---|",
        f"| inside a planted high-pressure spell | {chaos.inside_windows} | "
        f"{chaos.inside_chaos} | {chaos.inside_rate:.3f} |",
        f"| outside | {chaos.outside_windows} | {chaos.outside_chaos} | "
        f"{chaos.outside_rate:.3f} |",
        "",
    ]
    return "\n".join(lines)


def _xt_section() -> str:
    c = calibrate_xt([simulate_match(seed) for seed in TEST_SEEDS])
    lines = [
        "## Expected threat (xT) calibration",
        "",
        f"Grid fitted on dev seeds {_seeds(DEV_SEEDS)} by `scripts/fit_xt.py`; evaluated here "
        f"on test seeds {_seeds(TEST_SEEDS)}. Prediction: xT of the zone where a pass or "
        "shot starts. Outcome: that possession ends in a goal for the team on the ball.",
        "",
        "| Actions | Goal rate | Brier | Brier (base rate) | Brier skill | ECE |",
        "|---|---|---|---|---|---|",
        f"| {c.n} | {c.base_rate:.4f} | {c.brier:.5f} | {c.brier_base:.5f} | "
        f"{c.brier_skill:.4f} | {c.ece:.4f} |",
        "",
        "| Decile | Mean predicted | Observed | Actions |",
        "|---|---|---|---|",
    ]
    lines += [f"| {i} | {pred:.4f} | {obs:.4f} | {k} |"
              for i, (pred, obs, k) in enumerate(c.bins, start=1)]
    lines += ["", "Goals are rare per action, so the Brier skill over the base rate is "
                  "small; calibration (ECE, deciles) is what makes the values quotable.", ""]
    return "\n".join(lines)


def _off_ball_section() -> str:
    s = score_off_ball(TEST_SEEDS)

    def rate(c: Counter, k: str) -> str:
        return f"{c[k] / s.n[k]:.2f}" if s.n[k] else "-"

    eff = ("free", "decoy")
    n_eff = sum(s.n[k] for k in eff)

    def pooled(c: Counter) -> str:
        return f"{sum(c[k] for k in eff) / n_eff:.2f}" if n_eff else "-"

    precision = s.flagged_true / s.flagged if s.flagged else 0.0
    recall = s.flagged_true / s.planted_effective if s.planted_effective else 0.0
    lines = [
        "## Off-ball attribution (planted runs)",
        "",
        "Treated matches plant off-ball runs, labelled in the truth sidecar: free direct "
        "runs into space, decoy runs that drag the receiver's marker away (the runner does "
        "not receive), and tracked direct runs (the marker follows; no space created). The "
        "engine (`metrics/off_ball.py`) never reads the labels; its constants were chosen on "
        f"dev seeds. Test seeds {_seeds(TEST_SEEDS)}: {s.matches} treated matches.",
        "",
        "Share of runs whose runner each rule credits first (higher is better for free and "
        "decoy runs; lower is better for tracked runs, which created no space):",
        "",
        "| Runs | n | Engine | Credit the recipient | Credit whoever moved most |",
        "|---|---|---|---|---|",
    ]
    for k, label in (("free", "free direct"), ("decoy", "decoy"), ("tracked", "tracked")):
        lines.append(f"| {label} | {s.n[k]} | {rate(s.engine, k)} | {rate(s.recipient, k)} | "
                     f"{rate(s.most_moved, k)} |")
    lines += [
        f"| **effective (free + decoy)** | {n_eff} | **{pooled(s.engine)}** | "
        f"{pooled(s.recipient)} | {pooled(s.most_moved)} |",
        "",
        f"- Runner's credit separates effective from tracked runs with AUC **{s.auc:.3f}**.",
        f"- Decisive runs (top credit >= {off_ball.THRESHOLDS['decisive_credit']:g}, any "
        f"pass): {s.flagged / max(s.matches, 1):.1f} per match, precision "
        f"**{precision:.2f}** against planted effective runs, recall **{recall:.2f}**. "
        "Threshold rule (dev seeds): best recall with precision >= 0.70.",
        "",
    ]
    return "\n".join(lines)


def _fmt(metric: str, value: float) -> str:
    return f"{value:.3f}" if metric == "pass_completion" else f"{value:.1f}"


def _seeds(seeds: range) -> str:
    return f"{seeds[0]}-{seeds[-1]} ({len(seeds)} matches)"


def main() -> int:
    summaries = {seed: summarize(simulate_match(seed).events) for seed in ROBUSTNESS_SEEDS}
    calibration = [summaries[seed] for seed in CALIBRATION_SEEDS]
    robustness = list(summaries.values())
    n_cal = len(calibration)
    failed = []

    lines = [
        "# Simulator calibration",
        "",
        f"Generated by `uv run python scripts/calibrate.py`, schema {SCHEMA_VERSION}. "
        "Do not edit by hand.",
        "",
        f"## Targets over seeds {_seeds(CALIBRATION_SEEDS)}",
        "",
        "The same seeds and bounds as the realism test in `tests/test_simulator.py`.",
        "",
        "| Metric | Mean | Std | Target | Result |",
        "|---|---|---|---|---|",
    ]
    for metric in calibration[0]:
        values = [row[metric] for row in calibration]
        mean, std = statistics.fmean(values), statistics.stdev(values)
        if metric in TARGETS:
            lo, hi = TARGETS[metric]
            target, result = f"{lo:g}-{hi:g}", "pass" if lo <= mean <= hi else "FAIL"
            if result == "FAIL":
                failed.append(f"{metric} (FAIL on calibration seeds)")
        else:
            target, result = "-", "info"
        lines.append(
            f"| {metric} | {_fmt(metric, mean)} | {_fmt(metric, std)} | {target} | {result} |"
        )

    lines += [
        "",
        f"## Robustness: long-run mean over seeds {_seeds(ROBUSTNESS_SEEDS)}",
        "",
        f"A {n_cal}-seed mean is noisy, so the table above can sit near a bound by chance.",
        "Margin = distance from the long-run mean to the nearest bound, in standard errors",
        f"of a {n_cal}-seed mean (std / sqrt({n_cal})). At {MIN_MARGIN_SE:g} SE or more, any "
        f"{n_cal} seeds very likely meet the target; below that the result is `tight`.",
        "",
        "| Metric | Mean | Std | Target | Margin (SE) | Result |",
        "|---|---|---|---|---|---|",
    ]
    for metric, (lo, hi) in TARGETS.items():
        values = [row[metric] for row in robustness]
        mean, std = statistics.fmean(values), statistics.stdev(values)
        margin = min(mean - lo, hi - mean) / (std / math.sqrt(n_cal))
        if margin < 0:
            result = "FAIL"
        elif margin < MIN_MARGIN_SE:
            result = "tight"
        else:
            result = "pass"
        if result != "pass":
            failed.append(f"{metric} ({result} long-run)")
        lines.append(
            f"| {metric} | {_fmt(metric, mean)} | {_fmt(metric, std)} | {lo:g}-{hi:g} "
            f"| {margin:.1f} | {result} |"
        )

    mean_pass_length = statistics.fmean(row["mean_pass_length_m"] for row in robustness)
    report = "\n".join([
        "\n".join(lines) + "\n",
        _detector_section(),
        _xt_section(),
        _off_ball_section(),
        QUALITATIVE_REVIEW,
        _known_limitations(mean_pass_length),
    ])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(report.encode())
    print(report)
    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
