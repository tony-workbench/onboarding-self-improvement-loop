"""Which test setup improves onboarding fastest? Compare setups in the simulator.

Uses every change the model proposed and scored in runs/round_*.json as the
pool of ideas, with the simulator's hidden true effect for each. Each setup is
run for the same number of weeks over many random seeds, with no model calls.

A setup is:
  tests     how many tests run at the same time (at most one per funnel step
            when tests overlap, so two tests never change the same screen)
  layout    "split": each test gets its own slice of new users
            "overlap": all tests share one slice; a user can be in several tests
  share     share of new users in tests (split: per test; overlap: total)
  weeks     the longest a test runs before it is called "no clear effect"
  looks     "weekly": check every week at p<0.05 (the naive way)
            "corrected": check every week, with the threshold split across looks
            "end": check once, at the last week
  ship      "best": ship only the round's best winner; "all": every winner
            (winners touch different steps, so they can all ship)

Output: runs/policy_study.json
"""
import json
import math
import os
import random
from pathlib import Path

from .experiments import STEPS, SimulatedExperiments
from .loop import CONFIG

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / os.environ.get("RSI_RUNS_DIR", "runs")
HORIZON = 12          # weeks
SEEDS = 600
NEW_USERS = CONFIG["weekly_new_users"]


def pool():
    funnel = json.loads((ROOT / "data/funnel_week0.json").read_text())
    base = {s["step"]: s["conversion_from_previous"] for s in funnel["steps"]}
    sim = SimulatedExperiments(base, NEW_USERS, 0)
    ideas = []
    for f in sorted(RUNS.glob("round_*.json")):
        for c in json.loads(f.read_text())["candidates"]:
            if c["guard"]["pass"]:
                lift = sim.true_lift(c)
                ideas.append({"title": c["title"], "step": c["target_step"], "score": c["score"],
                              "lift": lift, "raw": lift / ((1 - base[c["target_step"]]) / 0.3)})
    return base, ideas


def reach(base, step):
    """Share of starting users who reach the step before `step`."""
    r = 1.0
    for s in STEPS:
        if s == step:
            return r
        r *= base[s]
    return r


def draw(rng, n, p):
    if n <= 0:
        return 0
    sd = math.sqrt(n * p * (1 - p))
    return min(n, max(0, round(n * p + rng.gauss(0, sd))))


def pvalue(x1, n1, x2, n2):
    if n1 == 0 or n2 == 0:
        return 1.0, 0.0
    p1, p2 = x1 / n1, x2 / n2
    pool_ = (x1 + x2) / (n1 + n2)
    se = math.sqrt(max(pool_ * (1 - pool_) * (1 / n1 + 1 / n2), 1e-12))
    return math.erfc(abs((p2 - p1) / se) / math.sqrt(2)), p2 - p1


def run(setup, base0, ideas, seed):
    rng = random.Random(seed)
    base = dict(base0)
    used, shipped, false_wins = set(), [], 0
    week = 0
    exposed = 0.0         # user-weeks in a treatment group, as share of all new-user weeks
    harmed = 0.0          # the same, but only for changes that are actually worse
    while week < HORIZON:
        # pick the round's tests: best scores first, one per step if overlapping
        avail = sorted([i for i in ideas if i["title"] not in used], key=lambda i: -i["score"] + rng.random() * 2)
        tests, steps = [], set()
        for i in avail:
            if setup["layout"] == "overlap" and i["step"] in steps:
                continue
            lift = i["raw"] * (1 - base[i["step"]]) / 0.3      # less room once a step is already good
            tests.append({**i, "lift": lift, "c": [0, 0], "t": [0, 0], "done": None})
            steps.add(i["step"])
            used.add(i["title"])
            if len(tests) == setup["tests"]:
                break
        if not tests:
            break
        per_test = setup["share"] if setup["layout"] == "split" else setup["share"]
        if setup["layout"] == "split" and setup["share"] * len(tests) > 1:
            per_test = 1 / len(tests)
        k = 0
        while any(t["done"] is None for t in tests) and week < HORIZON:
            week += 1
            k += 1
            for t in tests:
                if t["done"] is not None:
                    continue
                n = NEW_USERS * per_test / 2 * reach(base, t["step"])
                n = int(n)
                p = base[t["step"]]
                t["c"][0] += draw(rng, n, p)
                t["c"][1] += n
                t["t"][0] += draw(rng, n, min(0.99, p * (1 + t["lift"])))
                t["t"][1] += n
                exposed += per_test / 2 / HORIZON
                if t["lift"] < 0:
                    harmed += per_test / 2 / HORIZON
                last = k >= setup["weeks"]
                if setup["looks"] == "end" and not last:
                    continue
                alpha = 0.05 if setup["looks"] in ("weekly", "end") else 0.05 / setup["weeks"]
                pv, diff = pvalue(t["c"][0], t["c"][1], t["t"][0], t["t"][1])
                if pv < alpha:
                    t["done"] = "won" if diff > 0 else "lost"
                elif last:
                    t["done"] = "none"
        winners = sorted([t for t in tests if t["done"] == "won"],
                         key=lambda t: t["t"][0] / t["t"][1] - t["c"][0] / t["c"][1], reverse=True)
        to_ship = winners[:1] if setup["ship"] == "best" else winners
        for t in to_ship:
            base[t["step"]] = min(0.98, base[t["step"]] * (1 + t["lift"]))
            shipped.append(t["title"])
            if t["lift"] <= 0:
                false_wins += 1
    total = 1.0
    for s in STEPS:
        total *= base[s]
    return total, len(shipped), false_wins, exposed, harmed


REFERENCE = {"layout": "overlap", "tests": 5, "share": 0.50, "weeks": 1, "looks": "end", "ship": "all"}
VARIANTS = [
    ("layout", "Each test gets its own 10% (same 50% in total)", {"layout": "split", "share": 0.10}),
    ("tests", "1 test at a time", {"tests": 1}),
    ("tests", "3 tests at a time", {"tests": 3}),
    ("weeks", "Up to 2 weeks per test, weekly looks, corrected", {"weeks": 2, "looks": "corrected"}),
    ("weeks", "Up to 2 weeks per test, weekly looks, no correction", {"weeks": 2, "looks": "weekly"}),
    ("weeks", "2 weeks per test, one look at the end", {"weeks": 2, "looks": "end"}),
    ("weeks", "Up to 3 weeks per test, weekly looks, corrected", {"weeks": 3, "looks": "corrected"}),
    ("ship", "Ship only the best winner per round", {"ship": "best"}),
    ("share", "10% of new users in tests", {"share": 0.10}),
    ("share", "100% of new users in tests", {"share": 1.0}),
]


def main():
    base, ideas = pool()
    start = 1.0
    for s in STEPS:
        start *= base[s]

    def evaluate(setup):
        res = [run(setup, base, ideas, seed) for seed in range(SEEDS)]
        return {"completion": round(sum(r[0] for r in res) / SEEDS, 4),
                "gain": round(sum(r[0] for r in res) / SEEDS / start - 1, 4),
                "shipped": round(sum(r[1] for r in res) / SEEDS, 2),
                "false_wins": round(sum(r[2] for r in res) / SEEDS, 3),
                "harmed": round(sum(r[4] for r in res) / SEEDS, 3)}

    rows = [{"factor": "reference", "label": "Chosen setup", **REFERENCE, **evaluate(REFERENCE)}]
    for factor, label, change in VARIANTS:
        setup = {**REFERENCE, **change}
        rows.append({"factor": factor, "label": label, **setup, **evaluate(setup)})
    out = {"horizon_weeks": HORIZON, "seeds": SEEDS, "weekly_new_users": NEW_USERS, "ideas": len(ideas),
           "start_completion": round(start, 4), "rows": rows}
    (RUNS / "policy_study.json").write_text(json.dumps(out, indent=1))
    for r in rows:
        print(f"{r['label']:48} gain {r['gain']:+.1%}  shipped {r['shipped']:5}  false wins {r['false_wins']:.3f}  "
              f"exposed to harm {r['harmed']:.2f}")


if __name__ == "__main__":
    main()
