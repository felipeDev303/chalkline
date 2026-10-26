"""Instant headlines for on-air stories: deterministic, built only from the story's facts.

They go on screen the moment a story airs, while the agent desk writes its verified
narrative. Every number is a fact display (Spanish swaps the decimal point for a
comma), so headlines pass grounding by construction; tests check every kind.
"""

from __future__ import annotations

from pitchside.agents.contracts import Language
from pitchside.events.schema import MatchMetadata
from pitchside.metrics.key_moments import Moment

OUTCOME_ES = {"off target": "desviado", "saved": "atajado", "blocked": "bloqueado",
              "post": "al palo"}
STATE_ES = {"control": "control", "contested": "disputa", "chaos": "caos"}


def _facts(m: Moment, language: Language) -> dict[str, str]:
    """Fact displays by suffix ("minute", "scoreline", ...), localised numbers."""
    out = {}
    for f in m.facts:
        display = f.display
        if language == "es" and f.unit not in ("label", "minute", "scoreline", "formation"):
            display = display.replace(".", ",")
        out[f.evidence_id.rsplit(".", 1)[-1]] = display
    return out


def headline(m: Moment, metadata: MatchMetadata, language: Language) -> str:
    teams = {t.team_id: t for t in (metadata.home, metadata.away)}
    players = {p.player_id: p.name for t in teams.values() for p in t.players}
    team = teams[m.team_id].name if m.team_id else ""
    player = players.get(m.player_id or "", "")
    f = _facts(m, language)
    en = language == "en"
    home, away = metadata.home.name, metadata.away.name

    if m.kind == "goal":
        if en:
            return (f"{f['minute']} GOAL! {team} score: {home} {f['scoreline']} {away}. "
                    f"Their chance of winning goes from {f['win_before']} to "
                    f"{f['win_after']}.")
        return (f"¡Gol de {team} en el {f['minute']}! {home} {f['scoreline']} {away}. "
                f"Su probabilidad de ganar pasa de {f['win_before']} a {f['win_after']}.")
    if m.kind == "big_chance":
        if en:
            return (f"Big chance for {team} at {f['minute']}: {player}'s shot was worth "
                    f"{f['xg']} xG (scored about once every {f['odds_one_in']} shots), "
                    f"{f['outcome']}. A goal would have lifted their chance of winning from "
                    f"{f['win_now']} to {f['win_if_scored']}.")
        return (f"Ocasión clara de {team} en el {f['minute']}: el remate de {player} valía "
                f"{f['xg']} xG (entra una vez cada {f['odds_one_in']} tiros), "
                f"{OUTCOME_ES.get(f['outcome'], f['outcome'])}. Un gol habría llevado su "
                f"probabilidad de ganar de {f['win_now']} a {f['win_if_scored']}.")
    if m.kind == "decisive_run":
        own = f["kind"] == "own run"
        if en:
            how = ("ran into space; their control of the pass destination went"
                   if own else f"dragged a defender away; {f['recipient']}'s control of "
                   "that space went")
            return (f"The run that made it ({f['minute']}): {f['runner']} "
                    f"(#{f['runner_shirt']}) {how} from {f['control_without']} to "
                    f"{f['control_with']}.")
        how = ("atacó el espacio; su control del destino del pase pasó"
               if own else f"arrastró a un defensor y el control de {f['recipient']} "
               "sobre ese espacio pasó")
        return (f"La carrera que lo hizo posible ({f['minute']}): {f['runner']} "
                f"(#{f['runner_shirt']}) {how} de {f['control_without']} a "
                f"{f['control_with']}.")
    if m.kind == "swing":
        if en:
            return (f"Momentum swing from {f['minute']}: the game turned from "
                    f"{f['from_state']} to {f['to_state']}.")
        return (f"Cambio de guion desde el {f['minute']}: el partido pasó de "
                f"{STATE_ES[f['from_state']]} a {STATE_ES[f['to_state']]}.")
    if m.kind == "pressure_shift":
        up = f["direction"] == "up"
        if en:
            verb = "step up" if up else "drop off"
            return (f"{team} {verb} their pressing from {f['minute']}: pressures went from "
                    f"{f['before_per_min']} to {f['after_per_min']}.")
        verb = "intensifica" if up else "reduce"
        return (f"{team} {verb} la presión desde el {f['minute']}: las presiones pasaron "
                f"de {f['before_per_min']} a {f['after_per_min']}.")
    if m.kind == "sequence":
        return (f"{team} string together {f['passes']} passes from {f['minute']}." if en
                else f"{team} hilvana {f['passes']} pases desde el {f['minute']}.")
    if m.kind == "milestone":
        return (f"{player} reaches {f['passes']} passes at {f['minute']}." if en
                else f"{player} llega a los {f['passes']} pases en el {f['minute']}.")
    raise ValueError(f"no headline for moment kind {m.kind!r}")
