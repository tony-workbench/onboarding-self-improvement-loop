"""Stress test of the harm limits, with no real users and no model calls.

Three checks, all in the simulator, which replays the real traffic shape
(weekday shares and the day-to-day swings of eight real weeks, as indexes in
data/daily_pattern.json):

1. False alarms. A/A tests: the treatment is identical to control. Each one
   starts on a different real day (weekday and swing together), so every
   weekend, quiet day and busy day of the eight weeks is covered. Counts how
   often the hourly check stops a harmless test.
2. Planted harm. Tests whose change lowers its own step by 5% up to 90%.
   Measures how often and how fast the hourly check stops them, and how many
   finishers each one cost, against the planned cost (rsi/loop.py
   planned_harm) and against the old setup, which looked only at the end of
   the week.
3. Harder cases. Harm two steps further down the funnel than the step the
   test changes (seen only through finishing overall), and harm on Saturdays
   and Sundays only.

Output: runs/stress_test.json
"""
import json
import math
import os
import statistics
from pathlib import Path

from .experiments import PATTERN, STEPS, SimulatedExperiments
from .loop import CONFIG, guard_counts, guard_metrics, planned_harm
from .sequential import HarmMonitor

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / os.environ.get("RSI_RUNS_DIR", "runs") / "stress_test.json"
DROPS = [0.05, 0.10, 0.20, 0.30, 0.50, 0.90]
REPS = int(os.environ.get("RSI_STRESS_REPS", "200"))
DAYS = len(PATTERN["days"])


def one_test(base: dict, step: str, effects: dict, share: float, seed: int, weekdays: set | None = None) -> dict:
    """Run one test for a week with hourly checks. Returns when it stopped and what it cost."""
    sim = SimulatedExperiments(base, CONFIG["weekly_new_users"], seed, start_day=seed % DAYS)
    change = {"title": f"stress-{seed}", "target_step": step, "type": "copy", "change": "", "config": {}}
    tid = sim.create(change, share)
    sim.plant(tid, effects, weekdays)
    sim.start(tid)
    monitor = HarmMonitor(guard_metrics(step), CONFIG["harm_alpha"])
    for hour in range(1, 7 * 24 + 1):
        sim.run_hour()
        harmed = monitor.look(guard_counts(sim.read(tid), monitor.metrics))
        if harmed:
            return {"stopped_hour": hour, "metric": harmed, "finishers_delta": sim.tests[tid]["finishers_delta"]}
    return {"stopped_hour": None, "metric": None, "finishers_delta": sim.tests[tid]["finishers_delta"]}


def full_week_cost(base: dict, step: str, lift: float, share: float) -> float:
    """Expected finishers lost if the test runs the whole week (the old setup's one look at the end)."""
    finish = math.prod(base.values())
    step_rate = base[step]
    users = CONFIG["weekly_new_users"] * share / 2
    return -users * finish * (min(step_rate * (1 + lift), 0.99) / step_rate - 1)


def summarize(rows: list, base: dict, step: str, drop: float, share: float, plan: float, where: str = "own step",
              week_share: float = 1.0) -> dict:
    stopped = [r for r in rows if r["stopped_hour"]]
    lost = sorted(-r["finishers_delta"] for r in rows)
    hours = sorted(r["stopped_hour"] for r in stopped)
    return {"step": step, "harm_on": where, "drop": drop, "runs": len(rows),
            "over_plan_share": round(sum(x > plan for x in lost) / len(rows), 3),
            "stopped_share": round(len(stopped) / len(rows), 3),
            "median_hours_to_stop": statistics.median(hours) if hours else None,
            "p95_hours_to_stop": hours[int(0.95 * (len(hours) - 1))] if hours else None,
            "finishers_lost_mean": round(statistics.mean(lost), 2),
            "finishers_lost_p95": round(lost[int(0.95 * (len(lost) - 1))], 2),
            "finishers_lost_without_stop": round(full_week_cost(base, step, -drop, share) * week_share, 2)}


def main() -> None:
    funnel = json.loads((ROOT / "data/funnel_week0.json").read_text())
    base = {s["step"]: s["conversion_from_previous"] for s in funnel["steps"]}
    share = CONFIG["test_share"]
    weekly_finishers = CONFIG["weekly_new_users"] * math.prod(base.values())

    plan = {s: planned_harm(s, share, base) for s in STEPS}
    aa = []
    for step in STEPS:
        for k in range(REPS):
            aa.append(one_test(base, step, {}, share, 10_000 + k + 1000 * STEPS.index(step)))
    false_alarms = sum(1 for r in aa if r["stopped_hour"])

    planted = []
    for step in STEPS:
        for drop in DROPS:
            rows = [one_test(base, step, {step: -drop}, share, 20_000 + k) for k in range(REPS)]
            planted.append(summarize(rows, base, step, drop, share, plan[step]))

    harder = []
    for step in STEPS[:-2]:                       # harm two steps down, seen only through finishing overall
        far = STEPS[STEPS.index(step) + 2]
        for drop in (0.20, 0.30):
            rows = [one_test(base, step, {far: -drop}, share, 30_000 + k) for k in range(REPS)]
            harder.append(summarize(rows, base, step, drop, share, plan[step], f"two steps down ({far})"))
    for step in STEPS:                            # harm on Saturdays and Sundays only
        rows = [one_test(base, step, {step: -0.9}, share, 40_000 + k, weekdays={5, 6}) for k in range(REPS)]
        weekend = sum(list(PATTERN["weekday_share_last_4_weeks"].values())[5:])
        harder.append(summarize(rows, base, step, 0.9, share, plan[step], "own step, weekends only", weekend))

    out = {
        "settings": {"share": share, "weekly_new_users": CONFIG["weekly_new_users"], "runs_per_cell": REPS,
                     "harm_alpha": CONFIG["harm_alpha"], "start_days": DAYS, "weekly_finishers": round(weekly_finishers)},
        "false_alarms": {"tests": len(aa), "stopped": false_alarms, "rate": round(false_alarms / len(aa), 4)},
        "planned_cost": {s: round(v, 1) for s, v in plan.items()},
        "planted": planted,
        "harder": harder,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"A/A: {false_alarms}/{len(aa)} stopped by mistake")
    for p in planted + harder:
        print(f"{p['step']:12s} {p['harm_on']:28s} -{p['drop']:.0%}: stopped {p['stopped_share']:.0%}, median {p['median_hours_to_stop']}h, "
              f"lost {p['finishers_lost_mean']} (p95 {p['finishers_lost_p95']}) vs {p['finishers_lost_without_stop']}"
              " without the hourly check")


if __name__ == "__main__":
    main()
