# Safety case

This page sets out why the loop could be run on real new users, in the claims-arguments-evidence form the UK AI Security Institute
uses for its safety case templates. Each claim has the argument for it, the evidence in this repository, and the gaps that are not
closed yet. Numbers are in `docs/index.html`; the files named here produce them.

**Top claim.** Run on a company's onboarding, the loop changes only onboarding, keeps every step and every job a screen does, reads
only aggregate onboarding data, and each test has a planned cost in users that about 19 runs in 20 stay under.

## 1. Changes stay inside onboarding and delete nothing

- **Argument.** Every proposed change is checked in code before a test can exist: every existing screen stays, in its order; each part
  of a screen keeps its job, and a replacement must be able to do that job; a change may edit only the screens of its own funnel step;
  anything naming something outside onboarding is rejected. Code decides first; two model reviews (base rules, fair design) can only
  block more, never let more through.
- **Evidence.** `rsi/safeguards.py`; `tests/test_safeguards.py`, which checks both that big moves pass and that every bypass found by a
  red-team pass is blocked; the audit log in every run folder, which records every allowed and blocked action.
- **Gaps.** The model reviews can be wrong in both directions. A config only describes the change; the app must render exactly what the
  config says.

## 2. No pressure or unfair design

- **Argument.** Code blocks what code can check reliably (prices, links, markup, look-alike characters, timers other than a real wait,
  requests for personal data). A separate model review reads every user-facing text for pressure, shaming, skipping and money, however
  worded. The rules follow the FTC dark-patterns report, EU DSA Article 25, EU AI Act Article 5 and the UK Age Appropriate Design Code.
- **Evidence.** `rsi/safeguards.py`, the `FAIR` review in `rsi/loop.py`, and 34 ordinary onboarding lines in the tests that must not be
  blocked.
- **Gaps.** Meaning is judged by a model, not proven.

## 3. Data access is limited

- **Argument.** The loop reads through one gateway that serves only the onboarding funnel and anonymized support themes, as aggregates.
  It never sees user-level data, raw mail or keys. Experiment calls go through one wrapper that allows only the loop's own tests and a
  fixed set of actions.
- **Evidence.** `DataGateway` and `ScopedExperiments` in `rsi/safeguards.py`, and their tests.
- **Gaps.** The service that holds the keys must itself be locked down; that is outside this demo.

## 4. One bad test costs little, and its cost is planned

- **Argument.** Every hour each test is checked on its own step, the next step and finishing onboarding with an always-valid
  sequential test (the method Amplitude Experiment uses by default), and switched off as soon as one is clearly worse; the experiment
  wrapper then refuses to ship it. Reading it every hour does not raise the false-alarm rate. Before a test starts, its cost is
  planned: for every drop from 1% to 99%, on its own step, the next step or further down, and for every weekday it could start on, the
  finishers lost before the stop, planned for an unlucky draw. The largest of these is the planned cost.
- **Evidence.** `rsi/sequential.py` and `planned_harm` in `rsi/loop.py`; `rsi/stress_test.py` and `runs/stress_test.json`, which
  plant drops of 5% to 90% on every step, harm two steps further down, and harm on weekends only, and run harmless A/A tests from every
  day of eight real weeks of traffic; the comparison of the same loop with and without the check in `docs/index.html`.
- **Gaps.**
  - The planned cost is a 19-in-20 bound, not a guarantee: the stress test reports how often runs went over it.
  - Harm further down the funnel than the next step is seen only through finishing overall and is caught slowly; it is often not
    stopped within the week, though its cost stays near the plan. Harm on weekends only is diluted by weekday data.
  - Simulated only. Traffic within a day is assumed even, and simulated users finish at once; real users take minutes to days, so a
    real stop comes later. The Amplitude code reads by day; hourly reading has not been tried on the app.
  - Tests that run together share users and are watched one by one; their combined effect, and that of winners shipped together, is
    assumed to be the sum of their single effects.
  - Harm that appears later than finishing onboarding (retention, support mail) is not watched hourly.

## 5. What a week of tests costs is known, and can be capped

- **Argument.** Each test's planned cost is recorded before it starts, so a week's planned cost is their sum. A company can
  cap that sum at a share of the week's finishers (`RSI_HARM_BUDGET`); a test that does not fit gets less traffic or is skipped
  that round.
- **Evidence.** `planned_harm` and `allocate` in `rsi/loop.py` and their tests; the three-way comparison in `docs/index.html` of the
  hourly check alone, the check with a 10% cap, and no check.
- **Gaps.** The cap is off by default; without it a week is limited only by the five tests that may run at once, whose planned costs
  add up to a large share of a week's finishers, mostly from harm further down the funnel that the check is slow to see (see
  `docs/index.html`). It is off because in the saved runs a 10% cap ran far fewer tests and, on all new users over 20 weeks,
  cost more finishers through slower improvement than it saved inside tests. Whether to use it is a business choice.

## 6. Bad changes rarely ship

- **Argument.** A change ships only if its own step is clearly better after a full week and finishing onboarding is not clearly
  worse; a winner whose effect is mostly noise is re-tested on fresh users first.
- **Evidence.** The "shipped, of which actually bad" rows in `docs/index.html`, counted against the simulator's hidden true effects:
  a few of the shipped changes in the saved runs were actually slightly bad.
- **Gaps.** True effects in the simulator are calibrated to published results, not measured on this app.

## 7. People stay in control

- **Argument.** The loop acts only through the experiment wrapper, every action is logged, and the company sets the traffic share, the
  harm budget and the false-alarm rate. Any test can be switched off on the experiment platform at any time.
- **Evidence.** `audit.jsonl` in every run folder; the settings table in `docs/how-it-works.md`.

## Before real traffic

1. Have the app read onboarding from the Amplitude Experiment variant.
2. Run an A/A test on the app (both groups see the current onboarding) and check that assignment, events and the hourly check behave
   as in the simulator.
3. Start with one test at a small share, then follow the setup in `docs/index.html`.
