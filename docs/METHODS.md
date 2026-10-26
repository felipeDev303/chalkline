# Methods

How every number Pitchside shows is computed. Code: `src/pitchside/metrics/`.
Metrics consume only the event contract (`src/pitchside/events/`): never simulator
internals, never ground-truth sidecars (both enforced by `tests/test_metrics_isolation.py`).

## Contract

- A tool is a pure function of the match metadata and the events up to `as_of_seq`
  (inclusive). Later events are cut away before any computation, so a tool cannot
  look ahead during a live replay.
- Output is a `ToolResult`: `facts`, an optional `table` (at most 20 rows), `sample_size`,
  `method`, `caveats` and `cannot_tell`.
- A **fact** has a stable `evidence_id` (`pass.team:T06.completion_pct`), a `value`,
  a `unit`, a `label` and a `display` string. Values are rounded to display precision,
  half away from zero:

  | Unit | Display | Example |
  |---|---|---|
  | count | integer | `1029` |
  | decimal (a mean of counts) | 1 decimal | `5.0` |
  | pct (a rate) | 1 decimal + `%` | `83.6%` |
  | share (a split of a whole) | integer + `%` | `55%` |
  | m, km/h, seconds | 1 decimal + unit | `22.8 m`, `92.4 km/h`, `3.0 s` |
  | per_min | 1 decimal + `/min` | `-4.3/min` |
  | xg (expected goals / threat) | 2 decimals | `0.08` |
  | score (0-100 index) | integer | `72` |
  | minute | minute mark | `63'`, `45+2'` |
  | formation | outfield shape, defenders first | `4-3-3` |
  | scoreline | home-away goals, one fact per match | `2-1` |
  | label | words only, no digits | `control` |

- Table cells are for rendering only. A number a narrative may quote must be a fact.
- **Minimum samples:** when a tool lacks the sample to support a number, it omits the
  fact and says why in `cannot_tell`; a weak number never reaches a narrative.
- Errors the agent can fix (unknown team or player, `as_of_seq` out of range) raise
  `ToolError` with a code and a message safe to show the model.

## Shared definitions

Defined once in `metrics/_timeline.py`; every tool uses these.

- **Attacking direction** comes from `MatchMetadata.home_attacks_high_x_in_period_1`;
  teams swap ends at half time. Zones are measured in the attacking team's frame
  (it attacks towards x = 105): final third is x >= 70 m; the box is x >= 88.5 m
  and |y - 34| <= 20.16 m.
- **Minute** follows football convention: 0-59 s is 1'; the second half starts at 46';
  time past 45 minutes of a period is added time (`45+2'`, `90+1'`).
- **Possession.** A kickoff starts a possession; a possession change starts one
  unless that team already has the ball (the change that follows a kickoff after a
  goal); half time and full time close it. Pressures and tackles by the defending
  team stay inside the attacking team's possession. Possession length = passes in it.
- **Possession time** counts in-play seconds only. The gap between two consecutive
  events goes to the team in possession after the first, except when the second is
  a restart: a phase event, or a possession change caused by `out_of_play`, `foul`,
  `other` or `shot_end`. Those gaps are dead time (ball out, celebrations, set-up).
  Caveat: a blocked shot recovered by the defence is `shot_end` too, so a couple of
  live seconds are dropped there.
- **Windows** are consecutive 5-minute slices of each period's clock, never spanning
  half time. A window's observed time runs to the last visible event, so the current
  window and the added-time window are partial; rates use observed time.

## Grounding

`metrics/grounding.py` checks that every number in a generated narrative equals a
fact's `display`. On failure the pipeline retries once, then hides the narrative
and shows the evidence.

- **One agent turn only.** A narrative is validated against the facts returned in
  the same agent turn, never against facts from earlier `as_of_seq` calls: a number
  that was true at minute 30 may be stale at minute 60. `validate` enforces this by
  rejecting results with different `as_of_seq`.
- **Locale-aware digits.** `en`: `1,029` and `83.6`; `es`: `1.029` and `83,6 %`. A
  number written in the other locale's style does not parse and is rejected, as are
  space-separated thousands (`1 029`).
- **Single tokens:** minute marks (`63'`, `45+2'`, also `45+2` without the mark) and
  hyphenated digit groups. A formation must match in order (`4-3-3` is not `3-3-4`).
  A scoreline matches as an unordered pair, so "lost 1-2" and "won 2-1" both match
  the `2-1` fact. **Who won, who leads, and which team a scoreline is told from is not
  checked here; that attribution is the verifier agent's job.**
- **Number words 0-20** (`three`, `tres`) count as numbers. `un`/`una` do not (they are
  mostly articles). Idioms whose number word is no quantity claim are exempt, each
  covered by a test: en `one of`, `one-two`, `one-on-one`, `one on one`, `one-touch`,
  `no one`, `this one`, `that one`, `1st half`, `2nd half`; es `uno de`, `una de`,
  `los dos`, `las dos`, `uno a uno`, `uno contra uno`, `1er tiempo`, `1.er tiempo`,
  `2º tiempo`, `2.º tiempo`.
- **Matching** compares values after normalisation: `83.60` matches `83.6%`; units and
  `%` are ignored; `84` does not match `83.6%`. There is no exemption for small
  integers. Digits glued to letters (ids such as `T06`) are not numbers.
- **What it cannot tell:** whether a number is attributed to the right subject. "T06
  completed 83.6%" passes if 83.6% belongs to T07. `matched_ids` makes that traceable;
  claim-level checks belong to the verifier agent. Ordinal words (`third goal`) and
  multiplicatives (`twice`) are not extracted.

## Tools

Registered in `metrics/registry.py`, which also exports strict JSON schemas for function
calling. Every threshold below is a constant in the tool's `THRESHOLDS`; a test fails if
this document and the code disagree.

### `match_summary`

- **Definition:** scoreline (home-away), current minute, and per team: goals, shots,
  shots on target (goal or saved), passes, pass completion, possession share, formation.
- **Formula:** counts of events so far; completion = completed / attempted passes;
  possession share = team in-play seconds / total in-play seconds (see Shared definitions).
- **Thresholds:** `min_passes` = 15 (completion), `min_in_play_s` = 60 (possession share).
- **Caveats:** possession is time-based, not pass-based, so it can differ from broadcast
  figures.
- **Cannot tell:** who deserved to win; quality of the shots (use `shot_quality`).

### `pass_profile`

- **Definition:** passing of a team or a player: count, completion, mean length, mean
  ball speed, mean difficulty, and the 3 hardest completed passes (difficulty, minute,
  length).
- **Formula:** length = straight line start to end (m); ball speed = length / flight
  duration x 3.6 (km/h). **Difficulty** (0-100), in the passer's attacking frame:

  ```text
  100 * clamp(0.30 * min(length / 50, 1)
            + 0.20 * under_pressure
            + 0.15 * height                         # ground 0, low 0.5, high 1
            + 0.20 * clamp(forward_progress / 30, 0, 1)
            + 0.15 * zone,                          # box 1, final third 0.5, else 0
            0, 1)
  ```

  Ties among the hardest passes go to the earlier one.
- **Thresholds:** `min_passes` = 15 (rates and means), `hardest_shown` = 3.
- **Caveats:** a fixed formula, not a learned model; it ignores where other players are
  (no tracking data), so a short pass through a crowded midfield scores low.
- **Cannot tell:** whether a pass was the right choice; intended receiver of failed passes.

### `shot_profile`

- **Definition:** shots, on target, goals, expected goals (xG, the sum of the shots'
  xG), fastest and mean shot speed, best chance (xG and minute) and xG per shot for a
  team or a player.
- **Formula:** xG from the fitted model below (Expected goals).
- **Thresholds:** `min_shots` = 3 (means).
- **Caveats:** xG ignores where defenders and the goalkeeper stand.
- **Cannot tell:** how well a shot was struck beyond its speed; deflections.

### Expected goals and pass completion (fitted models)

- **Models:** two logistic regressions fitted by IRLS (Newton's method) in numpy by
  `scripts/fit_models.py` on simulated seeds 0-99, written as `metrics/_models.py` (no
  file reads at run time). **xG**: P(goal | shot) from distance to the goal centre, the
  angle between the posts seen from the shot (`atan2` of the two post vectors), header,
  under pressure. **xPass**: P(complete | pass) from length, forward progress, height
  (high, low; ground is the base), under pressure, ending in the final third, ending
  in the box.
- **Explanation:** each feature's effect on a shot is `coef x (value - training mean)`
  in log-odds; with the average shot's log-odds the effects add up to the shot's, so
  "xG low because the angle was tight and the shooter was pressed" is a sum of facts.
- **Check:** the simulator draws every shot and pass from a latent probability and
  writes it to the truth sidecar only. On held-out seeds 200-399 the models are
  compared with those latent probabilities and with outcomes (Brier, deciles, mean
  absolute error to the truth): `docs/data/CALIBRATION.md`.

### `shot_quality`

- **Definition:** one shot (`scope` latest or best so far): minute, shooter, xG, "scored
  about once every N such shots" (N = round(1 / xG), so narratives never compute it),
  outcome, and the effects that move its xG most; plus each team's goals and total xG
  ("the table lies" when they disagree).
- **Thresholds:** `min_effect` = 0.1 (log-odds; smaller effects are not listed).
- **Caveats:** defenders and the goalkeeper's position are not in the model.
- **Cannot tell:** whether a shot was well struck beyond where it was taken from.

### `win_probability`

- **Definition:** chance of a home win, a draw and an away win now; each goal's
  before and after for the scoring team (`scope` goals); the missed chance with the
  highest leverage, with the scoring team's chance of winning at the time and had it
  gone in. A table of checkpoints every `every_min` minutes.
- **Formula:** goals still to come are independent Poisson for each team, summed up to
  `max_goals` further goals and renormalised. Rate for the time left:
  `lambda = (t_left / 90) x ((1 - a) x prior + a x xG_so_far / t_played x 90)`,
  `a = t_played / 90`, prior = the league's goals per team per 90 (1.605, seeds 0-99).
  Added time counts as no time left. A shot's swing = win probability had it gone in
  minus just before it; leverage = xG x swing.
- **Thresholds:** `max_goals` = 10, `every_min` = 5, `goals_shown` = 6.
- **Caveats:** equal teams before kickoff; no game-state effects (a leading team does
  not sit back) and no red cards. Calibrated against final results on held-out seeds
  (`docs/data/CALIBRATION.md`).
- **Cannot tell:** who will win: these are probabilities, not a prediction.

### `threat_profile`

- **Definition:** expected threat (xT) added by a team's or a player's completed passes:
  total, number of passes valued, and the 3 passes that added the most, with minute.
  The football counterpart of basketball's expected possession value.
- **Formula:** the pitch is cut into 12 x 8 zones in the attacking frame. A zone's xT is
  the probability that possession from there ends in a goal, from a Markov model of
  actions (Singh, 2018): `xT(z) = s(z) g(z) + m(z) sum_z' T(z, z') xT(z')`, with s / m
  the shares of shots and passes from z, g the goal rate of shots from z, and T the rate
  of completed passes from z to z' (failed passes add 0), solved by 50 iterations.
  A completed pass adds `xT(end) - xT(start)`.
- **Fit and check:** the grid is fitted on simulated seeds 0-99 (`scripts/fit_xt.py`
  writes `metrics/_xt_grid.py`, so metrics never read files) and its calibration on
  untouched seeds 200-399 is in `docs/data/CALIBRATION.md` (ECE and deciles).
- **Thresholds:** `top_shown` = 3.
- **Caveats:** reflects the simulated league's style; carries and failed passes are not
  credited; values are small per pass (goals are rare), shown with 2 decimals.
- **Cannot tell:** the off-ball movement that made a pass possible.

### `off_ball_credit`

- **Definition:** decisive off-ball runs behind completed passes into the final third:
  who ran, who received, own run or decoy, and the receiver's control of the pass
  destination with and without the run.
- **Formula:** frames come from the pass and from the event where the passer got the
  ball. Each teammate's movement in between, minus their team's median movement (the
  block shifts with the ball; a run is moving differently from it), is undone in turn,
  together with any defender within 3 m who moved at least 3 m relative to their own
  block (they went with the runner). The receiver's control of the destination is
  `logistic(BETA x (I_receiver - sum of I_defenders))`, with Gaussian influence
  `I = exp(-d^2 / (2 SIGMA^2))`, `SIGMA` = 6 m and `BETA` = 3; other attackers do not
  count, or a decoy (runner and marker leaving together) would cancel out. Undoing the
  receiver's own run moves the pass target with them. Credit = control with minus
  control without; the top-credited teammate is the runner, decisive if credit >=
  `decisive_credit`. Teammates who moved less than `min_run_m` made no run.
- **Thresholds:** `decisive_credit` = 0.3, `min_run_m` = 4, `shown` = 5. SIGMA, BETA and
  the decisive threshold were chosen on dev seeds (rule for the threshold: best recall
  with precision >= 0.70, as for pressure shifts).
- **Validation:** treated matches plant three kinds of run (free direct, decoy, tracked
  direct) with labels in the truth sidecar. On untouched seeds 200-399
  `docs/data/CALIBRATION.md` reports how often the engine credits the runner first,
  against two naive rules (credit the recipient: fails every decoy; credit whoever moved
  most: credits tracked runs that created nothing).
- **Caveats:** control is a geometric index, not a probability; frames are event-level,
  without velocities; only passes into the final third are analysed by the tool.
- **Cannot tell:** runs that no pass used; whether a run was meant as a decoy.

### `control_vs_chaos`

- **Definition:** each 5-minute window classified as `control`, `contested` or `chaos`,
  with possession split, open-play turnovers per minute (interceptions and tackles won),
  pressures per minute per team and pass completion; plus rhythm: events per minute and
  passes per possession.
- **Formula:** a window is **chaos** if turnovers/min >= `chaos_turnovers_per_min` or
  completion < `chaos_completion_pct`; else **control** if the dominant team's possession
  share >= `control_share_pct` and turnovers/min <= `control_turnovers_per_min`; else
  **contested**. Windows are classified once they have events and `min_window_s` of play.
- **Scope:** `latest` returns the most recent complete window plus the current partial
  window when it can be classified; `all` returns every classified window (about 9 facts
  each). Both include the match-level state shares and rhythm.
- **Thresholds:** `min_window_s` = 120, `min_window_passes` = 5 (completion shown),
  `control_share_pct` = 56, `control_turnovers_per_min` = 1.2,
  `chaos_turnovers_per_min` = 2.0, `chaos_completion_pct` = 70. Chosen from 3,911
  eligible windows over simulated seeds 0-199 so that 25% are control, 51% contested and
  24% chaos.
- **Caveats:** thresholds are percentile-based, not tuned against ground truth. With
  planted regimes, windows inside a planted high-pressure spell are chaos more often
  than windows outside (rates in `docs/data/CALIBRATION.md`); on the dev seeds the split
  is 22% / 52% / 26%. The current window is partial.
- **Cannot tell:** why a window was chaotic; quality of play in a "controlled" window.

### `pressure_shift`

- **Definition:** moments when a team's pressures per minute change sharply between
  consecutive complete 5-minute windows (they may straddle half time).
- **Formula:** shift if |after - before| >= `min_delta_per_min` and
  |after - before| >= `min_relative_change` x before.
- **Scope:** `latest` returns the team's average, latest complete-window rate and shift
  count, the shift only if it shows in the latest complete window, and the current
  partial window's rate when it has `min_window_s` of play; `all` returns every shift.
  Shifts are numbered over the whole match, so `shift3` has the same id in both scopes.
- **Thresholds:** `min_delta_per_min` = 1.8, `min_relative_change` = 0.25,
  `min_complete_windows` = 2. (Re-tuned with schema 0.3.0: at 1.6 the dev seeds gave
  1.1 false positives per control match, over the cap, so the rule moved to 1.8.)
- **Validation:** simulated matches carry planted pressing changes (ground truth in a
  `.truth.json` sidecar that metrics never read). Thresholds were tuned on dev seeds
  0-99 by `scripts/tune_detectors.py` with a fixed rule: best F1 among settings with at
  most 1.0 false positive per control-group match (no planted regimes). The lower
  threshold with the best F1 (0.8/min) produced about 8 false "tactical changes" per
  match, unusable for live commentary. Precision, recall by cause and false positives
  on untouched test seeds 200-399 are in `docs/data/CALIBRATION.md`: increases are
  found, drops in pressing mostly are not, since they are smaller than the threshold.
- **Caveats:** says the rate changed, not why; misses most drops in pressing.
- **Cannot tell:** the cause of a shift (tactics, score, fatigue, where the ball was);
  **that pressing stayed the same.** The detector is conservative by design (tuned so
  what goes on air is reliable), so the absence of a detected shift is no evidence of
  no change. Every result past the minimum sample carries this in `cannot_tell`, and so
  does `key_moments`, so a narrator never turns "nothing detected" into "kept its
  intensity".

### `key_moments`

- **Definition:** ranked moments up to `as_of_seq`, each with its minute, an importance
  score and its own facts (evidence ids `moment:<kind>@<seq>...`).
- **Formula:** goals and big chances are scored by match impact (`win_probability`): a
  goal 60 + 40 x min(|swing| / 0.5, 1), so goals rank among themselves by how much they
  moved the scoring team's chance of winning; a big chance (missed shot with xG >=
  `big_chance_xg`) 40 + 50 x min(leverage / 0.15, 1), so a 0.4 chance at 88' with the
  score level outranks the same chance at 5'. Goal facts add the xG and the win
  probability before and after; big chances add xG, "once every N shots", and the win
  probability at the time and had it gone in. Other moments keep fixed weights:
  decisive off-ball run 55 (the 3 strongest); control/chaos swing (consecutive
  classified windows going control to chaos or back) 50; pressure shift 40; hardest
  completed pass 35; the completed pass that added the most expected threat 35;
  passing sequence (possession with >= `sequence_passes` passes) 30 + 2 per pass beyond
  10, capped at 90; a player's `milestone_passes`-th pass 20. Ranked by importance,
  then time.
- **Thresholds:** `big_chance_xg` = 0.2 (about 2 per team per simulated match),
  `sequence_passes` = 10, `milestone_passes` = 50.
- **Caveats:** impact comes from a win-probability model with equal teams and no
  game-state effects; the weights of the other moments are editorial.
- **Cannot tell:** off-ball runs that no pass used.

### `player_focus`

- **Definition:** one player's shirt number, touches (passes, shots and possessions won),
  passes, completion, mean pass difficulty, shots, goals, tackles (won), pressures, and
  the key moments where they are the passer, shooter or milestone owner, with those
  moments' facts.
- **Thresholds:** `min_passes` = 15 (completion and mean difficulty), `moments_shown` = 5.
- **Caveats:** off-ball work is credited by `off_ball_credit`, not here.
- **Cannot tell:** the player's influence on moments they did not touch.

## Producer

The producer agent (`api/producer.py`) decides which moments go on air during a
replay. It is deterministic and causal: every `step_events` events it computes
`key_moments` on the match cut there and considers only moments it has not seen. It
airs one when:

- its importance is at least `min_importance` (goals always qualify);
- at least `gap_s` seconds of match time have passed since the last story, unless it
  is a goal or its importance is at least `break_in_importance`;
- no story of the same kind for the same team aired in the last `repeat_s` seconds.

Thresholds: `step_events` = 25, `min_importance` = 40, `break_in_importance` = 90,
`gap_s` = 90, `repeat_s` = 300. Hardest pass and most threatening pass are "best so
far" moments that keep changing as the match goes on, so they are left to recaps.
Each story's instant headline is a template filled only with the story's fact displays;
a test checks every kind in English and Spanish against grounding.
