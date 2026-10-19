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
  | pct (a rate) | 1 decimal + `%` | `83.6%` |
  | share (a split of a whole) | integer + `%` | `55%` |
  | m, km/h, seconds | 1 decimal + unit | `22.8 m`, `92.4 km/h`, `3.0 s` |
  | per_min | 1 decimal + `/min` | `-4.3/min` |
  | score (0-100 index) | integer | `72` |
  | minute | minute mark | `63'`, `45+2'` |
  | label | as is | `4-3-3`, `2-1`, `control` |

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
  hyphenated digit groups (`4-3-3`, `2-1`) are matched against display strings, so a
  score must be quoted in the fact's order (home-away).
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

Documented here as each tool lands: definition, formula, thresholds, minimum sample,
caveats and what it cannot tell.
