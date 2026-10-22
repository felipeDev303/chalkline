"""Every tunable of the simulator. Calibrate here, then rerun scripts/calibrate.py.

Ranges are `(lo, hi)` for uniform draws. Per-zone tuples are indexed by
`pitch.DEFENSIVE, MIDDLE, FINAL_THIRD, BOX`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

Range = tuple[float, float]


class SimParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- time -------------------------------------------------------------
    stoppage_s: Range = (60.0, 300.0)
    carry_time_s: Range = (1.3, 4.5)
    carry_prob: float = 0.45
    carry_max_m: float = 7.0
    dead_time_out_s: Range = (8.0, 25.0)
    dead_time_foul_s: Range = (15.0, 40.0)
    dead_time_goal_s: Range = (50.0, 80.0)
    dead_time_goal_kick_s: Range = (15.0, 30.0)
    dead_time_save_s: Range = (3.0, 10.0)

    # --- defending --------------------------------------------------------
    pressure_prob: tuple[float, float, float, float] = (0.10, 0.18, 0.28, 0.35)
    pressure_duration_s: Range = (0.5, 2.5)
    tackle_prob: float = 0.012
    tackle_prob_pressured: float = 0.12
    tackle_win_prob: float = 0.6
    foul_prob: float = 0.006  # foul by the team in possession -> turnover

    # --- passing ----------------------------------------------------------
    pass_scale_m: float = 12.0  # receiver weight halves at this distance
    forward_bias: float = 1.6
    gk_pass_weight: float = 0.4
    long_ball_prob: float = 0.06
    pass_noise_m: float = 4.0
    pass_max_x: float = 102.0  # passes aim no deeper than this (attacking frame)
    shape_margin_m: float = 2.0  # nominal positions stay this far inside the lines
    in_play_margin_m: float = 0.5  # in-play passes end this far inside the lines
    backward_scale_m: float = 12.0  # receiver weight halves at this distance backwards
    throw_in_max_m: float = 25.0  # throw-ins only reach teammates this close
    pass_base: float = 0.95
    pass_dist_penalty: float = 0.004  # per metre beyond 10 m
    pass_pressure_penalty: float = 0.10
    pass_final_third_penalty: float = 0.06
    pass_box_penalty: float = 0.10
    pass_high_penalty: float = 0.08
    pass_prob_bounds: Range = (0.30, 0.98)
    fail_offside_prob: float = 0.10
    fail_out_prob: float = 0.22
    # (ground, low, high) weights for passes < 20 m, < 35 m, longer
    height_weights_short: tuple[float, float, float] = (0.88, 0.10, 0.02)
    height_weights_medium: tuple[float, float, float] = (0.60, 0.30, 0.10)
    height_weights_long: tuple[float, float, float] = (0.15, 0.35, 0.50)
    cross_high_prob: float = 0.7  # wide final third -> box passes that are lofted
    # ball speed in m/s for (ground, low, high), reached at pass_speed_full_m;
    # shorter passes are slower, down to pass_speed_floor of that speed
    pass_speed_ms: tuple[Range, Range, Range] = ((11.0, 17.0), (13.0, 19.0), (15.0, 22.0))
    pass_speed_full_m: float = 30.0
    pass_speed_floor: float = 0.5

    # --- shooting ---------------------------------------------------------
    shot_prob_box_central: float = 0.32
    shot_prob_box_wide: float = 0.145
    shot_prob_long: float = 0.056
    shot_long_min_x: float = 78.0
    shot_pressure_factor: float = 0.7
    header_prob: float = 0.5
    header_max_dist_m: float = 16.0
    foot_weights: tuple[float, float, float] = (0.66, 0.31, 0.03)  # right, left, other
    xg_scale: float = 0.45
    xg_dist_m: float = 10.0
    xg_angle_floor: float = 0.35
    header_xg_factor: float = 0.6
    pressure_xg_factor: float = 0.75
    # (blocked, off_target, saved, post) when not a goal
    shot_miss_weights: tuple[float, float, float, float] = (0.28, 0.40, 0.29, 0.03)
    rebound_defender_prob: float = 0.55
    # (mean, sd, min, max) in km/h
    shot_speed_foot: tuple[float, float, float, float] = (92.0, 14.0, 35.0, 150.0)
    shot_speed_head: tuple[float, float, float, float] = (55.0, 10.0, 30.0, 90.0)

    # --- planted tactical regimes (ground truth in <match>.truth.json) -----
    control_every: int = 5  # seeds divisible by this are the control group: no regimes
    spells_per_team: tuple[int, int] = (1, 2)  # planned pressing spells, inclusive
    spell_start_s: Range = (300.0, 1800.0)  # on the period clock
    spell_duration_s: Range = (600.0, 1080.0)
    spell_latest_end_s: float = 2640.0  # spells end before 44:00 of a period
    spell_min_gap_s: float = 600.0  # between two spells of the same team
    high_spell_prob: float = 0.65  # otherwise the spell is a drop
    high_factor: Range = (2.2, 3.0)  # pressure intensity multiplier in a high spell
    low_factor: Range = (0.25, 0.45)  # and in a low spell
    trailing_factor: float = 1.6  # a trailing team presses harder...
    trailing_from_s: float = 900.0  # ...from 60' (15:00 of period 2)
    max_pressure_prob: float = 0.9

    # --- positions and planted off-ball runs (truth in <match>.truth.json) ---
    position_jitter_m: float = 1.0  # noise on every player's position in a frame
    run_prob: float = 0.04  # per on-ball step from the middle third on, if no run is active
    run_min_x: float = 35.0  # ball at least this far up (attacking frame)
    decoy_prob: float = 0.35  # otherwise a direct run
    tracked_prob: float = 0.4  # direct runs where the marker follows the runner
    run_forward_m: Range = (8.0, 14.0)
    run_lateral_m: Range = (2.0, 6.0)
    run_pass_prob: float = 0.75  # the carrier plays the run (runner, or decoy's beneficiary)
    run_pass_noise_m: float = 2.0
    marker_follow_m: float = 1.5  # a following marker stays this far goal-side
    # Pass completion rises with space at the destination (distance to the nearest
    # defender): a swing of pass_space_bonus between no space and space_ref_m or more.
    space_ref_m: float = 8.0
    pass_space_bonus: float = 0.14


DEFAULT_PARAMS = SimParams()
