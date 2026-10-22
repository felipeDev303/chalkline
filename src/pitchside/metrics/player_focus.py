"""Player focus: one player's involvement so far, and the key moments they shaped."""

from __future__ import annotations

from statistics import fmean
from typing import Annotated

from pydantic import Field

from pitchside.events.match import Match
from pitchside.metrics._timeline import view
from pitchside.metrics.contract import Fact, Table, ToolParams, ToolResult, fact
from pitchside.metrics.expected_threat import pass_threat
from pitchside.metrics.key_moments import all_moments, moment_ids, ranked
from pitchside.metrics.pass_profile import pass_difficulty

TOOL_NAME = "player_focus"
DESCRIPTION = (
    "Everything one player has done so far: shirt number, touches, passes, completion, "
    "mean pass difficulty, shots, goals, tackles (won), pressures, and the key moments "
    "they were part of with their minutes. Use it for player-focus mode or when a viewer "
    "asks about a specific player."
)

THRESHOLDS: dict[str, float] = {
    "min_passes": 15,  # completion and mean difficulty need this many passes
    "moments_shown": 5,  # key moments involving the player, most important first
}
ON_BALL = frozenset({"pass", "shot", "possession_change"})


class Params(ToolParams):
    player_id: Annotated[str, Field(description="Player id, e.g. 'T06-09'.")]


def run(match: Match, params: Params) -> ToolResult:
    v = view(match, params.as_of_seq)
    pid = params.player_id
    team, player = v.player(pid)
    mine = [e for e in v.events if e.player_id == pid]
    passes = [e for e in mine if e.type == "pass"]
    shots = [e for e in mine if e.type == "shot"]
    tackles = [e for e in mine if e.type == "tackle"]
    prefix = f"player:{pid}"
    facts: list[Fact] = [
        fact(f"{prefix}.shirt_number", "Shirt number", player.shirt_number, "count"),
        fact(f"{prefix}.touches", "Touches", sum(1 for e in mine if e.type in ON_BALL), "count"),
        fact(f"{prefix}.passes", "Passes", len(passes), "count"),
        fact(f"{prefix}.shots", "Shots", len(shots), "count"),
        fact(f"{prefix}.goals", "Goals", sum(1 for e in shots if e.outcome == "goal"), "count"),
        fact(f"{prefix}.tackles", "Tackles", len(tackles), "count"),
        fact(f"{prefix}.tackles_won", "Tackles won", sum(1 for e in tackles if e.won), "count"),
        fact(f"{prefix}.pressures", "Pressures", sum(1 for e in mine if e.type == "pressure"),
             "count"),
        fact(f"{prefix}.threat_added", "Expected threat added by completed passes",
             sum(pass_threat(v.metadata, e) or 0.0 for e in passes), "xg"),
    ]
    cannot_tell: list[str] = []
    if len(passes) >= THRESHOLDS["min_passes"]:
        completed = sum(1 for e in passes if e.outcome == "complete")
        facts += [
            fact(f"{prefix}.completion_pct", "Pass completion", 100 * completed / len(passes),
                 "pct"),
            fact(f"{prefix}.mean_difficulty", "Mean pass difficulty",
                 fmean(pass_difficulty(v.metadata, e) for e in passes), "score"),
        ]
    else:
        cannot_tell.append(f"Fewer than {THRESHOLDS['min_passes']:g} passes: no completion "
                           "or difficulty average.")
    involved = [m for m in ranked(all_moments(v)) if m.player_id == pid]
    shown = involved[:int(THRESHOLDS["moments_shown"])]
    facts.append(fact(f"{prefix}.key_moments", "Key moments involving the player",
                      len(involved), "count"))
    for m in shown:
        facts += m.facts
    rows = tuple((m.minute.display, m.kind, round(m.importance, 1), moment_ids(m))
                 for m in shown)
    return ToolResult(
        tool_name=TOOL_NAME,
        params=params.model_dump(),
        as_of_seq=v.as_of_seq,
        facts=tuple(facts),
        table=Table(columns=("minute", "kind", "importance", "evidence_ids"),
                    rows=rows) if rows else None,
        sample_size=len(mine),
        method=(
            f"Events credited to the player ({team.short_name}). Touches are on-ball "
            "actions: passes, shots and possessions won. Key moments are those from "
            "key_moments where the player is the passer, shooter or milestone owner."
        ),
        caveats=("Without tracking data, off-ball work (runs, positioning) is invisible.",),
        cannot_tell=tuple(cannot_tell),
    )
