# Onboarding self-improvement loop

A demo of an AI loop that improves an app's first-run onboarding by itself, with safeguards that let it make big changes but never
delete a step, leave onboarding or pressure users, and an hourly harm check that stops a bad test early and gives each test a planned
cost. The data is one real, anonymized week of a desktop pet app; the A/B users are
simulated.

The full write-up with all results is `docs/index.html`.

## What you need

- Python 3.10 or newer (from python.org or your package manager). No other packages.
- Git, to download the code.
- Optional: a Gemini API key from Google AI Studio, only to run the loop live. Everything else works without a key.

## Run it

1. Download the code:

   ```bash
   git clone https://github.com/tony-workbench/onboarding-self-improvement-loop.git
   cd onboarding-self-improvement-loop
   ```

2. Open `docs/index.html` in a browser to read the results.

3. Replay the saved run (no key needed; it reuses the saved model answers and gives the same results):

   ```bash
   RSI_REPLAY=1 python3 -m rsi.loop
   ```

4. Run the tests:

   ```bash
   python3 -m unittest discover -s tests -t .
   ```

5. Stress-test the harm limits, compare test setups and scorers in the simulator, then rebuild the report (the scorer
   comparison takes several minutes):

   ```bash
   python3 -m rsi.stress_test
   python3 -m rsi.policy_study
   python3 -m rsi.scorer_study
   python3 report/build_report.py
   ```

6. Optional, run the loop live with your own key (writes to a new folder):

   ```bash
   GEMINI_API_KEY=your-key RSI_RUNS_DIR=runs_new python3 -m rsi.loop
   ```

## More

- `docs/how-it-works.md`: the code layout, the saved runs and every setting.
- `docs/safety-case.md`: each safety claim, the argument for it, the evidence, and what is not yet shown.
