# How it works

`docs/index.html` explains one round, the safeguards, the data and all results. This page covers the code, the saved runs and the
settings.

## Code

| Path | What it is |
|---|---|
| `rsi/loop.py` | The round loop, prompts, base rules and settings (`CONFIG`) |
| `rsi/safeguards.py` | Limits enforced in code: what a change may touch, the job each screen part must keep, text and fair-design checks, experiment calls, data access, audit log |
| `rsi/experiments.py` | Simulated A/B tests, hour by hour with the real traffic shape, and the statistics, plus the same calls against Amplitude Experiment (not run here) |
| `rsi/sequential.py` | The hourly harm check (always-valid sequential test) and each test's planned cost |
| `rsi/stress_test.py` | Planted-harm and false-alarm tests of the harm limits |
| `rsi/scorer_study.py` | Replays the saved idea pools with four scorers: random, the model's saved scores, the average effect of each kind of change on each step (ties go to the model's score), and each idea's true effect |
| `rsi/policy_study.py` | Compares test setups (how many tests, how long, how much traffic) |
| `rsi/llm.py` | Gemini client with a per-run answer cache |
| `prepare/anonymize_support.py` | Sends one week of stripped support mail to the Gemini API and writes paraphrased issues outside the repo; they were then grouped by hand into `data/support_week0.json` |
| `report/build_report.py` | Builds `docs/index.html` from the data and the saved runs |
| `tests/` | Safeguard tests (big moves pass, every way out is blocked) and tests of the statistics |

## Saved runs

Eight random seeds (7, 11, 23, 31, 37, 41, 43, 47) in two batches. The first three versions compare learning; the last three compare
the harm limits, all with learning and denoising:

| Batch | Learning with denoising | Learning from raw results | No learning | Learning, plus a 10% weekly harm budget | Learning, no hourly harm check |
|---|---|---|---|---|---|
| 8 weeks, 50% of new users | `runs/` (seed 7), `extra/learn_<seed>/` | `extra/learn_raw_<seed>/` | `runs_control/` (seed 7), `extra/control_<seed>/` | `extra/learn_budget_<seed>/` | `extra/learn_nostop_<seed>/` |
| 20 weeks, all new users | `long/learn_<seed>/` | `long/raw_<seed>/` | `long/control_<seed>/` | `long/budget_<seed>/` | `long/nostop_<seed>/` |
| Settings to replay | none | `RSI_DENOISE=0` | `RSI_LEARN=0` | `RSI_HARM_BUDGET=0.10` | `RSI_HARM_STOP=0` |

The 20-week batch also needs `RSI_SHARE=1.0 RSI_ROUNDS=20`. Every run re-tests noisy winners; each summary records its settings.

`runs/stress_test.json` holds the stress test, `runs/policy_study.json` the setup comparison and `runs/scorer_study.json` the
scorer comparison. `data/daily_pattern.json`
holds the real traffic shape the simulator follows, as indexes only. In the loop's runs, weeks start on a Monday and the day-to-day
swings start at a random day of the eight weeks, so a simulated weekday may carry another weekday's swing, and the swings are not
re-centred, so those runs sit about 1% below the stated finish rate; the stress test starts on each of the 56 days with its own
weekday and swing, re-centred.

Each folder holds one JSON file per round, a summary, an audit log of every allowed or blocked action, and `cache/` with every model
prompt and answer, so `RSI_REPLAY=1` reproduces the run exactly.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `RSI_RUNS_DIR` | `runs` | Folder to write the run to (and to read the cache from) |
| `RSI_REPLAY` | off | `1` uses only saved model answers and never calls the network |
| `RSI_SEED` | `7` | Simulator seed |
| `RSI_ROUNDS` | `8` | Number of one-week rounds |
| `RSI_SHARE` | `0.50` | Share of new users in tests, shared by all tests (up to 1.0) |
| `RSI_LEARN` | `1` | `0` turns off lessons, re-weighting and feedback (the control version) |
| `RSI_DENOISE` | `1` | `0` learns from raw measured results |
| `RSI_REPLICATE` | `1` | `0` skips re-tests of noisy winners |
| `RSI_HARM_STOP` | `1` | `0` turns off the hourly harm check and any harm budget (one look at the end of each week) |
| `RSI_HARM_BUDGET` | `0` | Cap on the planned cost of a week's tests, as a share of that week's finishers; `0` means no cap |
| `RSI_STRESS_REPS` | `200` | Tests per cell in `rsi.stress_test` |
| `RSI_STUDY_SCALE` | `1` | Scales the runs per seed in `rsi.scorer_study` (for a quick look, e.g. `0.05`) |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Model for live runs |
| `GEMINI_API_KEY` | none | Needed only for live runs |

To reproduce a saved run, use the same seed, folder and settings, for example
`RSI_REPLAY=1 RSI_SEED=11 RSI_SHARE=1.0 RSI_ROUNDS=20 RSI_RUNS_DIR=long/learn_11 python3 -m rsi.loop`.
