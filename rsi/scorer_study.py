"""How much could a better scorer add? Offline, no model calls.

Each round offers exactly the ideas that passed the safeguards in a saved run
with learning and denoising, so every scorer chooses from the same pool. A
scorer orders the ideas; tests are picked under the loop's rules (big-move
slots first, one test per funnel step, up to five), the simulator runs one
week, winners ship (rsi/loop.py decide, without re-tests or the hourly check),
and the next round starts on the new version. Scorers:

  random     a shuffled order
  model      the score the model gave in that saved run
  learnable  knows the average effect of each kind of change on each step
             (what learning from past tests is meant to find), not how
             widely each kind spreads; ties go to the model's score
  oracle     knows every idea's true effect, luck included: an upper bound no
             scorer can reach

Output: runs/scorer_study.json
"""
import json
import math
import os
import random
import statistics
from pathlib import Path

from . import loop
from .experiments import BOLD_TYPES, SimulatedExperiments, compare

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / os.environ.get("RSI_RUNS_DIR", "runs") / "scorer_study.json"
SEEDS = [7, 11, 23, 31, 37, 41, 43, 47]
BATCHES = {"short": {"share": 0.5, "rounds": 8, "reps": 100,
                     "folder": lambda s: "runs" if s == 7 else f"extra/learn_{s}"},
           "long": {"share": 1.0, "rounds": 20, "reps": 40, "folder": lambda s: f"long/learn_{s}"}}
SCORERS = ["random", "model", "learnable", "oracle"]
T_CRIT_7DF = 2.365


def learnable(sim: SimulatedExperiments, c: dict) -> float:
    """The true effect without its idea-specific luck (see SimulatedExperiments.true_lift)."""
    return sim.true_lift(c, luck=False)


def pick(cands: list, key) -> list:
    ranked = sorted(cands, key=key, reverse=True)
    picked, steps = [], set()
    for c in [c for c in ranked if c["type"] in BOLD_TYPES]:
        if len(picked) >= loop.CONFIG["bold_slots"]:
            break
        if c["target_step"] not in steps:
            picked.append(c)
            steps.add(c["target_step"])
    for c in ranked:
        if len(picked) >= loop.CONFIG["tests_per_round"]:
            break
        if c["target_step"] not in steps:
            picked.append(c)
            steps.add(c["target_step"])
    return picked


def run(pools: list, start: dict, scorer: str, share: float, seed: int) -> float:
    """Finish rate after the rounds, for one scorer and one simulator seed."""
    sim = SimulatedExperiments(start, loop.CONFIG["weekly_new_users"], seed)
    rng = random.Random(seed)
    keys = {"random": lambda c: rng.random(), "model": lambda c: c["score"],
            "learnable": lambda c: (learnable(sim, c), c["score"]), "oracle": lambda c: sim.true_lift(c)}
    for cands in pools:
        tids = []
        for c in pick(cands, keys[scorer]):
            tid = sim.create(c, share)
            sim.start(tid)
            tids.append(tid)
        sim.run_week()
        for tid in tids:
            sim.stop(tid)
            res = compare(sim.read(tid), sim.tests[tid]["change"]["target_step"])
            if (loop.decide(res, 1) or "").startswith("won"):
                sim.ship(tid)
    return math.prod(sim.baseline.values())


def study(batch: dict, reps: int) -> dict:
    per_seed = {s: [] for s in SCORERS}
    for seed in SEEDS:
        d = ROOT / batch["folder"](seed)
        rounds = sorted(d.glob("round_*.json"), key=lambda p: int(p.stem.split("_")[1]))[:batch["rounds"]]
        pools = [[c for c in json.loads(p.read_text())["candidates"] if c["guard"]["pass"] and "score" in c]
                 for p in rounds]
        start = json.loads((d / "summary.json").read_text())["start_funnel"]
        for scorer in SCORERS:
            per_seed[scorer].append(statistics.mean(
                run(pools, start, scorer, batch["share"], 1000 * seed + rep) for rep in range(reps)))
    out = {}
    for scorer, rates in per_seed.items():
        diffs = [a - b for a, b in zip(rates, per_seed["model"], strict=True)]
        se = statistics.stdev(diffs) / math.sqrt(len(diffs)) if any(diffs) else 0.0
        t = statistics.mean(diffs) / se if se else 0.0
        m = statistics.mean(diffs)
        out[scorer] = {"mean": round(statistics.mean(rates), 4), "per_seed": [round(x, 4) for x in rates],
                       "vs_model": round(m, 4), "t": round(t, 2), "significant": abs(t) > T_CRIT_7DF,
                       "vs_model_95": [round(m - T_CRIT_7DF * se, 4), round(m + T_CRIT_7DF * se, 4)]}
    return out


def main() -> None:
    scale = float(os.environ.get("RSI_STUDY_SCALE", "1"))
    result = {"settings": {"seeds": SEEDS, "runs_per_seed": {k: max(1, int(b["reps"] * scale)) for k, b in BATCHES.items()},
                           "note": "no re-tests and no hourly check, so levels differ from the loop's runs; "
                                   "compare scorers with each other"}}
    for name, batch in BATCHES.items():
        result[name] = study(batch, result["settings"]["runs_per_seed"][name])
        for scorer, r in result[name].items():
            print(f"{name:5s} {scorer:9s} {r['mean']:.1%}  vs model {r['vs_model'] * 100:+.1f} pt (t {r['t']})")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
