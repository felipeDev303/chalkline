# Evaluation

Every claim Pitchside makes is measured on simulated matches that were not used to
build or tune it. Seeds 0-99 are for development and tuning; seeds 200 and up are
held out.

| What | Where | Held-out result |
|---|---|---|
| Realism of the simulated league | [CALIBRATION.md](data/CALIBRATION.md) | passes, completion, shots, goals inside targets, all at least 2.5 standard errors from a bound |
| Pressing-change detector vs planted regimes | [CALIBRATION.md](data/CALIBRATION.md) | precision 0.71, recall 0.23, 0.68 false alarms per control match (1.2 before tuning) |
| Expected threat (xT) calibration | [CALIBRATION.md](data/CALIBRATION.md) | ECE 0.0012 over 212,613 actions |
| Expected goals (xG) vs the simulator's true scoring probability | [CALIBRATION.md](data/CALIBRATION.md) | mean absolute error 0.014 over 5,193 shots; Brier 0.0943 vs 0.0938 for the true probabilities themselves |
| Pass completion (xPass) vs the true completion probability | [CALIBRATION.md](data/CALIBRATION.md) | mean absolute error 0.041 over 206,457 passes; ECE 0.011 |
| Win probability vs final results | [CALIBRATION.md](data/CALIBRATION.md) | Brier 0.455 every 5 minutes of 200 matches (no information: 0.656; score and time only: 0.456) |
| Off-ball run attribution vs planted runs | [CALIBRATION.md](data/CALIBRATION.md) | credits the runner of an effective run first 86% of the time (credit the recipient: 44%, whoever moved most: 54%); credits a run that created no space 11% (those rules: 75%, 55%); AUC 0.94 |
| Agent desk vs single agent | [round v1](evaluation/ablation-v1.md), [round v2](evaluation/ablation-v2.md) | see below |

## Agent ablation

Same model (Microsoft Foundry gpt-4.1-mini, gpt-5-mini fallback), tools and prompts; 40
held-out moments per round, rotating persona, language and kind.

| Round | Config | Aired with errors | Published |
|---|---|---|---|
| v1 (seeds 200-239) | solo, no verifier | 35% | 100% |
| | solo + verifier | 0% | 95% |
| | desk | 0% | 75% |
| v2 (seeds 240-279) | solo, no verifier | 40% | 100% |
| | solo + verifier | 0% | 85% |
| | desk | 0% | 82% |

What it shows:

- **The verifier agent is what makes the narrative trustworthy.** A single LLM agent with
  tools airs a narrative with an unsupported number, a wrong attribution or a misspelled
  name 35-40% of the time; with the verifier in the loop, none reach the viewer.
- **Splitting analyst and narrator did not add measurable quality.** After round v1 the
  desk's retry was fixed (the narrator now sees its own draft and fixes only the failed
  sentences); round v2, on fresh seeds, puts the desk level with the single agent plus
  verifier (82% vs 85%, overlapping intervals), at higher latency and token use.
- Round v1 is kept as recorded; the fix was measured on seeds it was not designed against.
