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
- **Cannot tell:** who deserved to win; quality of the shots (use `shot_profile`).

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

- **Definition:** shots, on target, goals, fastest and mean shot speed, best and mean
  chance quality for a team or a player.
- **Formula:** **chance quality** (0-100) = angle between the posts seen from the shot
  location (goal 7.32 m wide), divided by that angle from the penalty spot (0.6423 rad),
  capped at 1, x 100; headers x 0.7. A geometric index, unrelated to the simulator's
  internal scoring. Check against outcomes over simulated seeds 0-99 (2,626 shots):
  conversion rises steadily with quality, 3.3% (0-20), 5.6% (20-40), 9.1% (40-60),
  13.1% (60-80), 17.1% (80-100), 25.1% (100).
- **Thresholds:** `min_shots` = 3 (means).
- **Caveats:** not a probability and not calibrated to real conversion rates; ignores
  defenders and the goalkeeper (no tracking data).
- **Cannot tell:** how well a shot was struck beyond its speed; deflections.

### `control_vs_chaos`

- **Definition:** each 5-minute window classified as `control`, `contested` or `chaos`,
  with possession split, open-play turnovers per minute (interceptions and tackles won),
  pressures per minute per team and pass completion; plus rhythm: events per minute and
  passes per possession.
- **Formula:** a window is **chaos** if turnovers/min >= `chaos_turnovers_per_min` or
  completion < `chaos_completion_pct`; else **control** if the dominant team's possession
  share >= `control_share_pct` and turnovers/min <= `control_turnovers_per_min`; else
  **contested**. Windows are classified once they have events and `min_window_s` of play.
- **Thresholds:** `min_window_s` = 120, `min_window_passes` = 5 (completion shown),
  `control_share_pct` = 56, `control_turnovers_per_min` = 1.2,
  `chaos_turnovers_per_min` = 2.0, `chaos_completion_pct` = 70. Chosen from 3,911
  eligible windows over simulated seeds 0-199 so that 25% are control, 51% contested and
  24% chaos.
- **Caveats:** thresholds not validated against ground truth yet (planned: simulator
  tactical regimes with labels); the current window is partial.
- **Cannot tell:** why a window was chaotic; quality of play in a "controlled" window.

### `pressure_shift`

- **Definition:** moments when a team's pressures per minute change sharply between
  consecutive complete 5-minute windows (they may straddle half time).
- **Formula:** shift if |after - before| >= `min_delta_per_min` and
  |after - before| >= `min_relative_change` x before.
- **Thresholds:** `min_delta_per_min` = 1.6, `min_relative_change` = 0.5,
  `min_complete_windows` = 2. 1.6/min lies between the 95th and 99th percentile of
  window-to-window changes in simulated matches, which contain no planned shifts, so on
  those matches every detection is a false positive: 1.2 per match on average over seeds
  0-199 (both teams), and 74 of the 200 matches have none.
- **Caveats:** thresholds not validated against ground truth yet.
- **Cannot tell:** the cause of a shift (tactics, score, fatigue, where the ball was).

### `key_moments`

- **Definition:** ranked moments up to `as_of_seq`, each with its minute, an importance
  score and its own facts (evidence ids `moment:<kind>@<seq>...`).
- **Formula:** importance: goal 100; big chance (non-goal shot with chance quality >=
  `big_chance_quality`) 40 + 0.4 x quality; control/chaos swing (consecutive classified
  windows going control to chaos or back) 50; pressure shift 40; hardest completed pass
  35; passing sequence (possession with >= `sequence_passes` passes) 30 + 2 per pass
  beyond 10, capped at 90 so it never outranks a goal; a player's `milestone_passes`-th
  pass 20. Ranked by importance, then time.
- **Thresholds:** `big_chance_quality` = 90 (about 2.5 per team per simulated match),
  `sequence_passes` = 10, `milestone_passes` = 50.
- **Caveats:** importance is a fixed editorial weighting, not a measure of impact.
- **Cannot tell:** moments that leave no event (a run that drags a defender away).

### `player_focus`

- **Definition:** one player's shirt number, touches (passes, shots and possessions won),
  passes, completion, mean pass difficulty, shots, goals, tackles (won), pressures, and
  the key moments where they are the passer, shooter or milestone owner, with those
  moments' facts.
- **Thresholds:** `min_passes` = 15 (completion and mean difficulty), `moments_shown` = 5.
- **Caveats:** off-ball work is invisible without tracking data.
- **Cannot tell:** the player's influence on moments they did not touch.
