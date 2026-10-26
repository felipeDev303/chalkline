"""Possession state machine: seed -> synthetic match.

Locations are worked out in the attacking frame of the team they belong to (see
`pitch`) and converted to absolute pitch coordinates only when an event is
emitted. The teams always attack opposite goals, so moving a point between their
frames is `flip`. Determinism: one seeded `Rng` and IEEE-exact maths only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pitchside.events.match import Match, attacks_high_x
from pitchside.events.schema import (
    EventBase,
    Frame,
    MatchEvent,
    MatchMetadata,
    Pass,
    Phase,
    PlayerXY,
    Point,
    PossessionChange,
    Pressure,
    Shot,
    Tackle,
)
from pitchside.simulator.names import CLUBS, FORWARDS, GK, MIDFIELDERS, ST, make_team
from pitchside.simulator.params import DEFAULT_PARAMS, SimParams
from pitchside.simulator.pitch import (
    BOX_HALF_WIDTH_M,
    CENTRE,
    FINAL_THIRD_X,
    GOAL,
    GOAL_AREA_HALF_WIDTH_M,
    XY,
    clamp,
    distance,
    flip,
    in_box,
    to_point,
    zone,
)
from pitchside.simulator.regimes import (
    Latent,
    MatchTruth,
    RegimeTracker,
    is_control,
    plan_spells,
)
from pitchside.simulator.rng import Rng
from pitchside.simulator.runs import ActiveRun, RunLabel

PERIOD_S = 45 * 60
COMPETITION = "Chalkline Synthetic League"
SEASON_START = datetime(2026, 8, 8, tzinfo=UTC)
KICKOFF_MINUTES = (12 * 60 + 30, 15 * 60, 17 * 60 + 30, 20 * 60)

# Nominal 4-3-3 positions in the team's attacking frame, same slot order as names.POSITIONS.
FORMATION: tuple[XY, ...] = (
    (5.0, 34.0),
    (30.0, 60.0), (24.0, 44.0), (24.0, 24.0), (30.0, 8.0),
    (48.0, 50.0), (42.0, 34.0), (48.0, 18.0),
    (68.0, 58.0), (74.0, 34.0), (68.0, 10.0),
)
HEIGHTS = ("ground", "low", "high")
# Restart kinds. Opponents must give space at all of them (no pressure or tackle).
KICKOFF, THROW_IN, SET_PIECE = "kickoff", "throw_in", "set_piece"
FEET = ("right_foot", "left_foot", "other")
SHOT_MISSES = ("blocked", "off_target", "saved", "post")


def simulate_match(seed: int, params: SimParams = DEFAULT_PARAMS) -> Match:
    return simulate_match_with_truth(seed, params)[0]


def simulate_match_with_truth(
    seed: int, params: SimParams = DEFAULT_PARAMS
) -> tuple[Match, MatchTruth]:
    """The match plus its ground truth (planted regimes and off-ball runs), which never
    enters the event stream."""
    rng = Rng(seed)
    metadata = _make_metadata(seed, rng)
    tracker = RegimeTracker(seed=seed, params=params,
                            team_ids=(metadata.home.team_id, metadata.away.team_id),
                            spells=plan_spells(seed, params))
    engine = _Engine(metadata, rng, params, tracker)
    events = engine.run()
    truth = tracker.truth(metadata.match_id).model_copy(
        update={"runs": tuple(engine.run_labels), "shots": tuple(engine.shot_truth),
                "passes": tuple(engine.pass_truth)})
    return Match(metadata=metadata, events=events), truth


def _make_metadata(seed: int, rng: Rng) -> MatchMetadata:
    home = rng.index(len(CLUBS))
    away = (home + 1 + rng.index(len(CLUBS) - 1)) % len(CLUBS)
    kickoff = SEASON_START + timedelta(days=rng.index(270), minutes=rng.choice(KICKOFF_MINUTES))
    return MatchMetadata(
        match_id=f"sim-{seed}",
        seed=seed,
        home=make_team(home),
        away=make_team(away),
        competition=COMPETITION,
        venue=CLUBS[home][2],
        kickoff_utc=kickoff,
        home_attacks_high_x_in_period_1=True,
    )


def shape(ball: XY, margin: float) -> list[XY]:
    """Positions of a team's 11 players given the ball, both in that team's frame."""
    sx = min(max((ball[0] - 45.0) * 0.6, -18.0), 26.0)
    sy = (ball[1] - 34.0) * 0.3
    gk = (FORMATION[GK][0] + max(sx, 0.0) * 0.4, FORMATION[GK][1] + sy * 0.5)
    return [gk] + [clamp(x + sx, y + sy, margin) for x, y in FORMATION[1:]]


class _Engine:
    def __init__(self, meta: MatchMetadata, rng: Rng, params: SimParams,
                 regimes: RegimeTracker) -> None:
        self.meta = meta
        self.rng = rng
        self.regimes = regimes
        self.goals = [0, 0]  # by side, for the trailing-team regime
        self.p = params
        self.teams = (meta.home, meta.away)
        self.events: list[MatchEvent] = []
        self.period = 1
        self.clock = 0.0
        self.att = 0  # side in possession: 0 home, 1 away
        self.carrier = ST  # formation slot of the ball carrier
        self.ball: XY = CENTRE  # in the attacking frame of `att`
        self.pressured = False
        self.from_cross = False  # carrier received a high pass (enables headers)
        self.restart: str | None = None  # kind of restart the next action is, if any
        # Positions and runs draw from their own streams: they never shift the match's.
        self.positions_rng = Rng(f"positions:{meta.seed}")
        self.runs_rng = Rng(f"runs:{meta.seed}")
        self.plant_runs = not is_control(meta.seed, params)
        self.active_run: ActiveRun | None = None
        self.run_labels: list[RunLabel] = []
        # Latent outcome probabilities, recorded for evaluation only (never emitted).
        self.shot_truth: list[Latent] = []
        self.pass_truth: list[Latent] = []
        self._pass_p = 1.0

    @property
    def dfn(self) -> int:
        return 1 - self.att

    def run(self) -> tuple[MatchEvent, ...]:
        first = self.rng.index(2)
        for period, kicker in ((1, first), (2, 1 - first)):
            self.period, self.clock = period, 0.0
            end = PERIOD_S + self.rng.uniform(*self.p.stoppage_s)
            self._kickoff(kicker)
            while self.clock < end:
                self._step()
            self._emit(Phase, 0, None, CENTRE, phase="half_time" if period == 1 else "full_time")
        return tuple(self.events)

    # --- helpers ----------------------------------------------------------

    def _point(self, side: int, p: XY) -> Point:
        attacks_up = attacks_high_x(self.meta, self.teams[side].team_id, self.period)
        return to_point(p if attacks_up else flip(p))

    def _pid(self, side: int, slot: int) -> str:
        return self.teams[side].players[slot].player_id

    def _positions(self) -> tuple[list[XY], list[XY]]:
        """Both teams' positions now: attackers (their frame), defenders (theirs)."""
        margin = self.p.shape_margin_m
        att = shape(self.ball, margin)
        att[self.carrier] = self.ball
        dfn = shape(flip(self.ball), margin)
        run = self.active_run
        if run is not None and run.side == self.att:
            att[run.runner] = run.target
            if run.follows:  # goal-side of the runner
                t = flip(run.target)
                dfn[run.marker] = clamp(t[0] - self.p.marker_follow_m, t[1], margin)
        return att, dfn

    def _frame(self) -> Frame:
        att, dfn = self._positions()
        j = self.p.position_jitter_m
        players = []
        for side, positions in ((self.att, att), (self.dfn, dfn)):
            up = attacks_high_x(self.meta, self.teams[side].team_id, self.period)
            for slot, xy in enumerate(positions):
                if not (side == self.att and slot == self.carrier):
                    xy = (xy[0] + self.positions_rng.uniform(-j, j),
                          xy[1] + self.positions_rng.uniform(-j, j))
                x, y = clamp(*(xy if up else flip(xy)))
                players.append(PlayerXY(player_id=self._pid(side, slot),
                                        x=round(x, 2), y=round(y, 2)))
        players.sort(key=lambda p: p.player_id)
        return Frame(players=tuple(players))

    def _emit(
        self, cls: type[EventBase], side: int, slot: int | None, loc: XY, **fields: Any
    ) -> None:
        seq = len(self.events)
        self.events.append(cls(
            event_id=f"{self.meta.match_id}-{seq:05d}",
            match_id=self.meta.match_id,
            seq=seq,
            period=self.period,
            clock_s=round(self.clock, 2),
            team_id=self.teams[side].team_id,
            player_id=None if slot is None else self._pid(side, slot),
            location=self._point(side, loc),
            frame=self._frame(),
            **fields,
        ))

    def _nearest(self, side: int, p: XY, *, outfield: bool = True) -> list[int]:
        """Slots of `side` sorted by distance to `p` (given in that side's frame)."""
        ball = self.ball if side == self.att else flip(self.ball)
        positions = shape(ball, self.p.shape_margin_m)
        slots = range(1 if outfield else 0, len(positions))
        return sorted(slots, key=lambda s: (distance(positions[s], p), s))

    def _turnover(self, slot: int, loc: XY, cause: str, *, restart: str | None = None) -> None:
        """Give the ball to `slot` of the defending side; `loc` is in that side's frame."""
        old = self.att
        self.active_run = None
        self.att, self.carrier, self.ball = 1 - old, slot, loc
        self._emit(
            PossessionChange, 1 - old, slot, loc,
            from_team_id=self.teams[old].team_id, cause=cause,
        )
        self.from_cross = False
        self.restart = restart

    def _kickoff(self, side: int, *, after_goal: bool = False) -> None:
        self._emit(Phase, side, None, CENTRE, phase="kickoff")
        if after_goal:
            self._emit(
                PossessionChange, side, ST, CENTRE,
                from_team_id=self.teams[1 - side].team_id, cause="shot_end",
            )
        self.att, self.carrier, self.ball = side, ST, CENTRE
        self.from_cross = False
        self.restart = KICKOFF
        self.active_run = None

    def _carry(self, *, force: bool = False) -> None:
        p = self.p
        self.clock += self.rng.uniform(*p.carry_time_s)
        if force or self.rng.chance(p.carry_prob):
            x = min(self.ball[0] + self.rng.uniform(0.0, p.carry_max_m), p.pass_max_x)
            y = self.ball[1] + self.rng.uniform(-3.0, 3.0)
            self.ball = clamp(x, y, p.in_play_margin_m)

    # --- one action by the ball carrier -------------------------------------

    def _step(self) -> None:
        self.regimes.observe(self.period, self.clock, self.goals)
        self.pressured = False
        restart, self.restart = self.restart, None
        if (restart is None and self.plant_runs and self.active_run is None
                and self.ball[0] >= self.p.run_min_x
                and self.runs_rng.chance(self.p.run_prob)):
            self._start_run()
        if restart is None and self._contest():
            return
        can_shoot = restart in (None, SET_PIECE)
        if can_shoot and self.rng.chance(self._shot_prob()):
            self._shoot()
        else:
            self._pass(restart)

    def _contest(self) -> bool:
        """Defenders press, tackle, or the carrier fouls. True if possession was lost."""
        p, rng = self.p, self.rng
        here = flip(self.ball)  # the ball in the defenders' frame
        presser: int | None = None
        press = p.pressure_prob[zone(self.ball)] * self.regimes.intensity(self.dfn)
        if rng.chance(min(press, p.max_pressure_prob)):
            near = self._nearest(self.dfn, here)
            presser = near[0] if rng.chance(0.7) else near[1]
            self._emit(
                Pressure, self.dfn, presser, here,
                target_player_id=self._pid(self.att, self.carrier),
                duration_s=round(rng.uniform(*p.pressure_duration_s), 2),
            )
            self.pressured = True

        if rng.chance(p.tackle_prob_pressured if self.pressured else p.tackle_prob):
            tackler = presser if presser is not None else self._nearest(self.dfn, here)[0]
            self.clock += rng.uniform(0.3, 1.2)
            won = rng.chance(p.tackle_win_prob)
            self._emit(
                Tackle, self.dfn, tackler, here,
                opponent_id=self._pid(self.att, self.carrier), won=won,
            )
            if won:
                self._turnover(tackler, here, "tackle")
                return True
            self.pressured = False  # carrier beat the tackle
            self._carry(force=True)

        if rng.chance(p.foul_prob):
            self.clock += rng.uniform(*p.dead_time_foul_s)
            here = flip(self.ball)
            self._turnover(self._nearest(self.dfn, here)[0], here, "foul", restart=SET_PIECE)
            return True
        return False

    # --- planted off-ball runs ----------------------------------------------

    def _start_run(self) -> None:
        """Plant a run for the team in possession; its label goes to the truth."""
        rr, p = self.runs_rng, self.p
        margin = p.shape_margin_m
        att = shape(self.ball, margin)
        dfn = shape(flip(self.ball), margin)
        outfield = [s for s in (*MIDFIELDERS, *FORWARDS) if s != self.carrier]
        forward = rr.uniform(*p.run_forward_m)
        lateral = rr.uniform(*p.run_lateral_m)

        def nearest_defender(xy: XY) -> int:
            return min(range(1, len(dfn)), key=lambda s: (distance(dfn[s], flip(xy)), s))

        if rr.chance(p.decoy_prob):
            # A decoy takes away the defender marking the receiver: pick the receiver,
            # their nearest defender is the marker, and the runner is the teammate
            # closest to that marker, who runs away and drags them along.
            kind, follows = "decoy", True
            beneficiary = rr.choice(outfield)
            marker = nearest_defender(att[beneficiary])
            mates = [s for s in range(1, len(att)) if s not in (beneficiary, self.carrier)]
            runner = min(mates, key=lambda s: (distance(att[s], flip(dfn[marker])), s))
            nominal = att[runner]
            away = 1.0 if nominal[1] >= att[beneficiary][1] else -1.0
            target = (nominal[0] + 0.6 * forward, nominal[1] + away * (lateral + 4.0))
        else:
            runner = rr.choice(outfield)
            nominal = att[runner]
            marker = nearest_defender(nominal)
            kind, follows, beneficiary = "direct", rr.chance(p.tracked_prob), runner
            # Runners look for a gap: of a few forward options, the one furthest from
            # any defender (a tracked runner finds it too, but the marker goes along).
            options = [clamp(min(nominal[0] + f, p.pass_max_x), nominal[1] + s * lateral,
                             margin)
                       for f in (forward, 0.7 * forward) for s in (-1.0, 0.0, 1.0)]
            target = max(options, key=lambda xy: (min(distance(xy, flip(d)) for d in dfn),
                                                  xy))
        target = clamp(min(target[0], p.pass_max_x), target[1], margin)
        side, opp = self.att, self.dfn
        self.run_labels.append(RunLabel(
            team_id=self.teams[side].team_id, player_id=self._pid(side, runner), kind=kind,
            tracked=follows, effective=kind == "decoy" or not follows,
            marker_id=self._pid(opp, marker), beneficiary_id=self._pid(side, beneficiary),
            start_seq=len(self.events),
        ))
        self.active_run = ActiveRun(side, kind, runner, marker, beneficiary, target, follows,
                                    len(self.run_labels) - 1)

    def _close_run(self, pass_seq: int, receiver: int, outcome: str) -> None:
        run = self.active_run
        if run is None or run.side != self.att:
            return
        label = self.run_labels[run.label_index]
        self.run_labels[run.label_index] = label.model_copy(update={
            "pass_seq": pass_seq, "pass_to_beneficiary": receiver == run.beneficiary,
            "pass_outcome": outcome,
        })
        self.active_run = None

    def _space(self, end: XY) -> float:
        """Distance from a point (attacking frame) to the nearest defender."""
        _, dfn = self._positions()
        return min(distance(end, flip(d)) for d in dfn)

    # --- passing ----------------------------------------------------------

    def _pass(self, restart: str | None = None) -> None:
        p, rng = self.p, self.rng
        mates, _ = self._positions()
        receiver = self._choose_receiver(mates, restart)
        tx, ty = mates[receiver]
        run = self.active_run
        played_run = run is not None and run.side == self.att and receiver == run.beneficiary
        n = p.run_pass_noise_m if played_run else p.pass_noise_m
        end = clamp(
            min(tx + rng.uniform(-n, n), p.pass_max_x),
            ty + rng.uniform(-n, n),
            p.in_play_margin_m,
        )
        if restart == KICKOFF:
            height = "ground"
        elif restart == THROW_IN:
            height = "low"
        elif self._is_cross(end) and rng.chance(p.cross_high_prob):
            height = "high"
        else:
            height = HEIGHTS[rng.weighted_index(self._height_weights(distance(self.ball, end)))]
        outcome = "complete" if restart == KICKOFF else self._pass_outcome(end, height)
        next_restart: tuple[int, XY, str] | None = None
        if outcome == "out":
            end, next_restart = self._out_of_play(end)
        dist = distance(self.ball, end)
        lo, hi = p.pass_speed_ms[HEIGHTS.index(height)]
        reach = min(dist / p.pass_speed_full_m, 1.0)
        scale = p.pass_speed_floor + (1.0 - p.pass_speed_floor) * reach
        duration = max(0.2, dist / (rng.uniform(lo, hi) * scale))
        self._emit(
            Pass, self.att, self.carrier, self.ball,
            end_location=self._point(self.att, end),
            recipient_id=self._pid(self.att, receiver) if outcome == "complete" else None,
            duration_s=round(duration, 2),
            outcome=outcome,
            height=height,
            under_pressure=self.pressured,
        )
        if restart != KICKOFF:
            self.pass_truth.append(Latent(seq=self.events[-1].seq, p=round(self._pass_p, 6)))
        self._close_run(len(self.events) - 1, receiver, outcome)
        self.clock += duration

        if outcome == "complete":
            self.carrier, self.ball = receiver, end
            self.from_cross = height == "high"
            self._carry()
        elif outcome == "incomplete":
            spot = flip(end)
            self._turnover(self._nearest(self.dfn, spot, outfield=False)[0], spot, "interception")
        elif outcome == "offside":
            self.clock += rng.uniform(*p.dead_time_foul_s)
            spot = flip(end)
            self._turnover(self._nearest(self.dfn, spot)[0], spot, "other", restart=SET_PIECE)
        else:
            assert next_restart is not None
            slot, spot, kind = next_restart
            self.clock += rng.uniform(*p.dead_time_out_s)
            self._turnover(slot, spot, "out_of_play", restart=kind)

    def _choose_receiver(self, mates: list[XY], restart: str | None = None) -> int:
        p, rng = self.p, self.rng
        if restart == KICKOFF:
            return rng.choice(MIDFIELDERS)
        run = self.active_run
        if (restart is None and run is not None and run.side == self.att
                and self.runs_rng.chance(p.run_pass_prob)):
            return run.beneficiary
        bx = self.ball[0]
        if restart is None and bx < 45.0 and rng.chance(p.long_ball_prob):
            targets = [s for s in FORWARDS if s != self.carrier]
            return rng.choice(targets)
        weights = []
        for slot, pos in enumerate(mates):
            d = distance(self.ball, pos)
            if slot == self.carrier or (restart == THROW_IN and d > p.throw_in_max_m):
                weights.append(0.0)
                continue
            r = d / p.pass_scale_m
            w = 1.0 / (1.0 + r * r)
            if pos[0] > bx + 3.0:
                w *= p.forward_bias
            elif pos[0] < bx:
                b = (bx - pos[0]) / p.backward_scale_m
                w /= 1.0 + b * b
            if slot == GK:
                w *= p.gk_pass_weight if bx < 40.0 else 0.0
            weights.append(w)
        if not any(weights):  # throw-in with nobody close: nearest teammate
            return self._nearest(self.att, self.ball)[0]
        return rng.weighted_index(weights)

    def _is_cross(self, end: XY) -> bool:
        wide = abs(self.ball[1] - GOAL[1]) > BOX_HALF_WIDTH_M
        return wide and self.ball[0] >= FINAL_THIRD_X and in_box(end)

    def _height_weights(self, dist: float) -> tuple[float, float, float]:
        if dist < 20.0:
            return self.p.height_weights_short
        if dist < 35.0:
            return self.p.height_weights_medium
        return self.p.height_weights_long

    def _pass_outcome(self, end: XY, height: str) -> str:
        p, rng = self.p, self.rng
        prob = p.pass_base - p.pass_dist_penalty * max(0.0, distance(self.ball, end) - 10.0)
        if self.pressured:
            prob -= p.pass_pressure_penalty
        if end[0] >= FINAL_THIRD_X:
            prob -= p.pass_final_third_penalty
        if in_box(end):
            prob -= p.pass_box_penalty
        if height == "high":
            prob -= p.pass_high_penalty
        space = min(self._space(end), p.space_ref_m) / p.space_ref_m
        prob += p.pass_space_bonus * (space - 0.5)
        lo, hi = p.pass_prob_bounds
        self._pass_p = min(max(prob, lo), hi)
        if rng.chance(self._pass_p):
            return "complete"
        forward = end[0] > self.ball[0]
        if forward and end[0] >= FINAL_THIRD_X and rng.chance(p.fail_offside_prob):
            return "offside"
        if rng.chance(p.fail_out_prob):
            return "out"
        return "incomplete"

    def _out_of_play(self, end: XY) -> tuple[XY, tuple[int, XY, str]]:
        """Move a failed pass's end onto the line; return it and the restart.

        The restart is (slot, spot, kind) with the spot in the defending side's frame.
        No corners in v1: a ball over the goal line is a goal kick.
        """
        if end[0] >= 95.0 and self.rng.chance(0.5):
            line = (GOAL[0], end[1])
            return line, (GK, (5.5, GOAL[1] + self.rng.uniform(-9.0, 9.0)), SET_PIECE)
        line = (end[0], 0.0 if end[1] < GOAL[1] else 2 * GOAL[1])
        spot = flip(line)
        return line, (self._nearest(self.dfn, spot)[0], spot, THROW_IN)

    # --- shooting ---------------------------------------------------------

    def _shot_prob(self) -> float:
        p = self.p
        if in_box(self.ball):
            central = abs(self.ball[1] - GOAL[1]) <= GOAL_AREA_HALF_WIDTH_M
            prob = p.shot_prob_box_central if central else p.shot_prob_box_wide
        elif self.ball[0] >= p.shot_long_min_x:
            prob = p.shot_prob_long
        else:
            return 0.0
        return prob * p.shot_pressure_factor if self.pressured else prob

    def _shoot(self) -> None:
        p, rng = self.p, self.rng
        self.active_run = None  # the carrier shot instead of playing the run
        d = distance(self.ball, GOAL)
        header = self.from_cross and d < p.header_max_dist_m and rng.chance(p.header_prob)
        body = "head" if header else FEET[rng.weighted_index(p.foot_weights)]
        centrality = (GOAL[0] - self.ball[0]) / max(d, 0.1)
        r = d / p.xg_dist_m
        xg = p.xg_scale / (1.0 + r * r) * (p.xg_angle_floor + (1.0 - p.xg_angle_floor) * centrality)
        if header:
            xg *= p.header_xg_factor
        if self.pressured:
            xg *= p.pressure_xg_factor
        if rng.chance(xg):
            outcome = "goal"
        else:
            outcome = SHOT_MISSES[rng.weighted_index(p.shot_miss_weights)]
        mu, sd, lo, hi = p.shot_speed_head if header else p.shot_speed_foot
        speed = min(max(rng.normal(mu, sd), lo), hi)
        self._emit(
            Shot, self.att, self.carrier, self.ball,
            outcome=outcome, body_part=body, speed_kmh=round(speed, 1),
            under_pressure=self.pressured,
        )
        self.shot_truth.append(Latent(seq=self.events[-1].seq, p=round(min(xg, 1.0), 6)))
        self.clock += rng.uniform(0.5, 1.5)
        self.from_cross = False

        if outcome == "goal":
            self.goals[self.att] += 1
            self.clock += rng.uniform(*p.dead_time_goal_s)
            self._kickoff(self.dfn, after_goal=True)
        elif outcome == "saved":
            self.clock += rng.uniform(*p.dead_time_save_s)
            saved_at = (rng.uniform(4.0, 10.0), rng.uniform(28.0, 40.0))
            self._turnover(GK, saved_at, "shot_end", restart=SET_PIECE)
        elif outcome == "off_target":
            self.clock += rng.uniform(*p.dead_time_goal_kick_s)
            goal_kick = (5.5, GOAL[1] + rng.uniform(-9.0, 9.0))
            self._turnover(GK, goal_kick, "shot_end", restart=SET_PIECE)
        else:  # blocked or off the post: loose ball
            if outcome == "post":
                loose = (rng.uniform(96.0, 102.0), rng.uniform(26.0, 42.0))
            else:
                loose = clamp(self.ball[0] - rng.uniform(1.0, 5.0),
                              self.ball[1] + rng.uniform(-4.0, 4.0))
            self.clock += rng.uniform(1.0, 3.0)
            if rng.chance(p.rebound_defender_prob):
                spot = flip(loose)
                self._turnover(self._nearest(self.dfn, spot, outfield=False)[0], spot, "shot_end")
            else:
                self.carrier = self._nearest(self.att, loose)[0]
                self.ball = loose
