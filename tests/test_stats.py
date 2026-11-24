"""The numbers behind each decision: tests, shrinkage, re-tests, the simulator and replay. No network, no keys."""
import math
import os
import tempfile
import unittest
from unittest import mock

from rsi import llm, loop, policy_study, scorer_study, sequential
from rsi.experiments import SimulatedExperiments, compare, proportion_test

BASE = {"choose_path": 0.76, "sign_in": 0.73, "adoption": 0.61, "home": 0.81, "finish": 0.65}


def counts(users, **steps):
    out = dict.fromkeys(["users", "choose_path", "sign_in", "adoption", "home", "finish"], 0)
    out.update(users=users, **steps)
    return out


class ProportionTest(unittest.TestCase):
    def test_hand_computed(self):
        r = proportion_test(500, 1000, 550, 1000)
        self.assertAlmostEqual(r["lift"], 0.1)
        self.assertAlmostEqual(r["p"], 0.025164, places=4)       # z = 0.05 / sqrt(.525 * .475 * .002) = 2.2389
        # delta method: sqrt(v2 + (p2/p1)^2 v1) / p1
        self.assertAlmostEqual(r["lift_se"], math.sqrt(0.55 * 0.45 / 1000 + 1.1 ** 2 * 0.25 / 1000) / 0.5, places=4)

    def test_no_users_means_no_information(self):
        r = proportion_test(0, 0, 5, 100)
        self.assertEqual((r["lift"], r["p"], r["lift_se"]), (0, 1.0, 1.0))

    def test_zero_control_rate_still_shows_a_gain(self):
        r = proportion_test(0, 100, 5, 100)
        self.assertGreater(r["lift"], 0)
        self.assertLess(r["p"], 0.05)

    def test_compare_uses_the_step_before(self):
        res = compare({"control": counts(1000, choose_path=500, finish=100),
                       "treatment": counts(1000, choose_path=550, finish=80)}, "choose_path")
        self.assertAlmostEqual(res["step"]["lift"], 0.1)
        self.assertAlmostEqual(res["finish"]["lift"], -0.2)
        self.assertEqual(res["users_per_group"], 1000)


class Shrinkage(unittest.TestCase):
    HISTORY = [{"measured_lift": 0.1, "lift_se": 0.02}, {"measured_lift": -0.1, "lift_se": 0.02}]

    def test_prior_alone_with_no_history(self):
        self.assertAlmostEqual(loop.tau2_now([]), loop.PRIOR_SD ** 2)

    def test_spread_around_zero_blended_with_prior(self):
        data = (0.01 + 0.01) / 2 - 0.0004                       # mean(x^2) - mean(se^2)
        w = 2 / (2 + loop.TRUST_AFTER)
        self.assertAlmostEqual(loop.tau2_now(self.HISTORY), w * data + (1 - w) * loop.PRIOR_SD ** 2)

    def test_denoise_keeps_sign_and_shrinks_noisy_results_more(self):
        tau2 = loop.tau2_now(self.HISTORY)
        clean = loop.denoise(self.HISTORY)
        self.assertAlmostEqual(clean[0]["clean_lift"], tau2 / (tau2 + 0.0004) * 0.1)
        self.assertLess(clean[1]["clean_lift"], 0)
        self.assertLess(abs(clean[0]["clean_lift"]), 0.1)
        precise = loop.denoise([{**self.HISTORY[0], "lift_se": 0.005}, self.HISTORY[1]])
        self.assertGreater(precise[0]["clean_lift"], clean[0]["clean_lift"])

    def test_retest_only_when_mostly_noise(self):
        self.assertTrue(loop.needs_retest({"lift_se": 0.05}, []))     # tau^2 = .0009 vs se^2 = .0025
        self.assertFalse(loop.needs_retest({"lift_se": 0.01}, []))


class Decisions(unittest.TestCase):
    @staticmethod
    def res(step_p, step_lift, fin_p=0.5, fin_lift=0.0, se=0.02):
        return {"step": {"p": step_p, "lift": step_lift, "lift_se": se}, "finish": {"p": fin_p, "lift": fin_lift}}

    def test_ladder(self):
        cases = [
            (self.res(0.01, 0.1, fin_p=0.005, fin_lift=-0.1), None, "rolled back: guardrail"),
            (self.res(0.01, 0.1), None, "won"),
            (self.res(0.01, 0.1, fin_p=0.03, fin_lift=-0.05), None, "lost: no clear effect"),
            (self.res(0.01, -0.1), None, "lost: worse"),
            (self.res(0.4, 0.02), None, "lost: no clear effect"),
        ]
        for res, retest, expected in cases:
            with self.subTest(expected):
                self.assertEqual(loop.decide(res, 1, retest), expected)

    def test_retest_uses_both_weeks_shrunk(self):
        tau2 = 0.03 ** 2
        # two weeks give +10% with se 2%: shrunk to +6.9%, lower bound +4.1% > 0, fresh week agrees
        self.assertEqual(loop.decide(self.res(0.0001, 0.10), 2, self.res(0.3, 0.03), tau2), "won, confirmed by re-test")
        # the fresh week alone need not be significant, but it must point the same way
        self.assertEqual(loop.decide(self.res(0.0001, 0.10), 2, self.res(0.3, -0.01), tau2),
                         "lost: did not hold up in re-test")
        # a noisy combined estimate is not enough once shrunk
        self.assertEqual(loop.decide(self.res(0.04, 0.10, se=0.05), 2, self.res(0.3, 0.05), tau2),
                         "lost: did not hold up in re-test")


class Simulator(unittest.TestCase):
    def change(self, title="t", step="home"):
        return {"title": title, "target_step": step, "type": "wait_info", "change": "x", "config": {}}

    def test_same_seed_same_users(self):
        results = []
        for _ in range(2):
            sim = SimulatedExperiments(BASE, 6000, 1)
            tid = sim.create(self.change(), 0.5)
            sim.start(tid)
            sim.run_week()
            results.append(sim.read(tid))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["control"]["users"], 1500)

    def test_retest_counts_only_new_users(self):
        sim = SimulatedExperiments(BASE, 6000, 1)
        tid = sim.create(self.change(), 0.5)
        sim.start(tid)
        sim.run_week()
        mark = sim.mark(tid)
        sim.run_week()
        fresh = sim.read_since(tid, mark)
        self.assertEqual(fresh["control"]["users"], 1500)
        self.assertEqual(fresh["treatment"]["finish"], sim.read(tid)["treatment"]["finish"] - mark["treatment"]["finish"])

    def test_ship_caps_the_rate(self):
        sim = SimulatedExperiments(BASE, 6000, 1)
        tid = sim.create(self.change(step="finish"), 0.5)
        sim.tests[tid]["lift"] = 0.9
        sim.ship(tid)
        self.assertEqual(sim.baseline["finish"], 0.98)


class Study(unittest.TestCase):
    def test_zero_effect_ideas_change_nothing_and_runs_repeat(self):
        ideas = [{"title": f"i{k}", "step": "home", "score": 5, "lift": 0, "raw": 0} for k in range(5)]
        a = policy_study.run(policy_study.REFERENCE, BASE, ideas, 0)
        b = policy_study.run(policy_study.REFERENCE, BASE, ideas, 0)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a[0], math.prod(BASE.values()))
        self.assertEqual(a[1], 0)


class Replay(unittest.TestCase):
    def test_cache_miss_in_replay_never_calls_the_network(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"RSI_REPLAY": "1"}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")), \
                self.assertRaises(RuntimeError):
            llm.ask_json("a prompt that was never asked", cache_dir=tmp)


class HarmChecks(unittest.TestCase):
    def test_same_rates_give_no_evidence_and_a_big_drop_does(self):
        self.assertGreater(sequential.always_valid_p(700, 1000, 700, 1000)[0], 0.9)
        p, d = sequential.always_valid_p(700, 1000, 500, 1000)
        self.assertLess(p, 0.001)
        self.assertLess(d, 0)

    def test_monitor_stops_only_for_a_worse_treatment(self):
        better = sequential.HarmMonitor(["sign_in"])
        self.assertIsNone(better.look({"sign_in": (500, 1000, 700, 1000)}))
        worse = sequential.HarmMonitor(["sign_in"])
        self.assertEqual(worse.look({"sign_in": (700, 1000, 500, 1000)}), "sign_in")

    def test_evidence_never_goes_back_up(self):
        m = sequential.HarmMonitor(["x"])
        m.look({"x": (70, 100, 55, 100)})
        low = m.best["x"]
        m.look({"x": (700, 1000, 700, 1000)})
        self.assertEqual(m.best["x"], low)

    def test_alpha_is_shared_by_the_guarded_metrics(self):
        self.assertAlmostEqual(sequential.HarmMonitor(["a", "b", "c"], 0.06).alpha, 0.02)

    def test_harmless_tests_are_rarely_stopped_with_hourly_looks(self):
        stopped = 0
        for seed in range(60):
            sim = SimulatedExperiments(BASE, 6000, seed)
            tid = sim.create({"title": f"aa{seed}", "target_step": "sign_in", "type": "copy", "change": "",
                              "config": {}}, 0.5)
            sim.plant(tid, {})
            sim.start(tid)
            m = sequential.HarmMonitor(loop.guard_metrics("sign_in"))
            for _ in range(168):
                sim.run_hour()
                if m.look(loop.guard_counts(sim.read(tid), m.metrics)):
                    stopped += 1
                    break
        self.assertLessEqual(stopped, 2)          # the stress test measures under 1%; 2 of 60 leaves room for chance

    def test_a_broken_step_is_stopped_within_a_day(self):
        sim = SimulatedExperiments(BASE, 6000, 3)
        tid = sim.create({"title": "broken", "target_step": "sign_in", "type": "copy", "change": "", "config": {}}, 0.5)
        sim.plant(tid, {"sign_in": -0.9})
        sim.start(tid)
        m = sequential.HarmMonitor(loop.guard_metrics("sign_in"))
        for hour in range(1, 169):
            sim.run_hour()
            if m.look(loop.guard_counts(sim.read(tid), m.metrics)):
                break
        self.assertLessEqual(hour, 24)


class HarmBudget(unittest.TestCase):
    def test_guarded_metrics(self):
        self.assertEqual(loop.guard_metrics("sign_in"), ["sign_in", "adoption", "finish_overall"])
        self.assertEqual(loop.guard_metrics("finish"), ["finish"])

    def test_planned_cost_grows_with_traffic_but_never_beyond_a_full_week(self):
        small, big = loop.planned_harm("sign_in", 0.2, BASE), loop.planned_harm("sign_in", 0.5, BASE)
        self.assertLess(small, big)
        full_week = 6000 * 0.5 / 2 * math.prod(BASE.values())      # every treated user lost, the upper limit
        self.assertLess(big, full_week)

    def setUp(self):
        self._budget = mock.patch.dict(loop.CONFIG, {"harm_budget": 0.10})
        self._budget.start()
        self.addCleanup(self._budget.stop)

    def test_allocation_keeps_the_round_within_budget(self):
        picked = [{"title": s, "target_step": s} for s in ["choose_path", "sign_in", "adoption", "home", "finish"]]
        kept, held = loop.allocate([dict(c) for c in picked], 0.0, BASE)
        self.assertLessEqual(sum(c["planned_harm"] for c in kept), loop.weekly_budget(BASE) + 1e-9)
        self.assertEqual(len(kept) + len(held), 5)
        self.assertTrue(all(c["share"] <= loop.CONFIG["test_share"] for c in kept))
        self.assertTrue(held or any(c["share"] < loop.CONFIG["test_share"] for c in kept))   # the 10% cap binds

    def test_a_full_budget_holds_every_test(self):
        kept, held = loop.allocate([{"title": "t", "target_step": "home"}], loop.weekly_budget(BASE), BASE)
        self.assertEqual((kept, len(held)), ([], 1))


class Harm(unittest.TestCase):
    def test_harm_further_down_counts_in_the_treatment_group(self):
        sim = SimulatedExperiments(BASE, 6000, 5)
        tid = sim.create({"title": "far", "target_step": "choose_path", "type": "copy", "change": "", "config": {}}, 0.5)
        sim.plant(tid, {"adoption": -0.3})
        sim.start(tid)
        sim.run_week()
        r = sim.read(tid)
        self.assertLess(r["treatment"]["adoption"] / r["treatment"]["sign_in"], r["control"]["adoption"] / r["control"]["sign_in"])
        self.assertLess(sim.tests[tid]["finishers_delta"], -40)       # about 1500 users x 0.178 x 0.3 = 80, less swings

    def test_weekend_only_harm_costs_nothing_on_weekdays(self):
        sim = SimulatedExperiments(BASE, 6000, 5, start_day=0)        # day 0 is a Monday
        tid = sim.create({"title": "wk", "target_step": "home", "type": "copy", "change": "", "config": {}}, 0.5)
        sim.plant(tid, {"home": -0.9}, weekdays={5, 6})
        sim.start(tid)
        for _ in range(5 * 24):
            sim.run_hour()
        self.assertEqual(sim.tests[tid]["finishers_delta"], 0.0)
        for _ in range(2 * 24):
            sim.run_hour()
        self.assertLess(sim.tests[tid]["finishers_delta"], 0.0)

    def test_plan_covers_harm_further_down_the_funnel(self):
        # a change to choose_path is planned for its worst place of harm, which is past the next step
        own_only = sequential.harm_bound(BASE["choose_path"], 1.0, math.prod(BASE.values()),
                                         [6000 * 0.5 / 2 / 168] * 168, 0.05 / 3)["finishers_lost"]
        self.assertGreater(loop.planned_harm("choose_path", 0.5, BASE), own_only)


class ScorerStudy(unittest.TestCase):
    def test_learnable_part_ignores_luck(self):
        sim = SimulatedExperiments(BASE, 6000, 1)
        a = {"title": "one name", "target_step": "sign_in", "type": "hint"}
        b = {**a, "title": "another name"}
        self.assertEqual(sim.true_lift(a, luck=False), sim.true_lift(b, luck=False))
        self.assertNotEqual(sim.true_lift(a), sim.true_lift(b))
        self.assertAlmostEqual(sim.true_lift(a, luck=False), 0.025 * (1 - BASE["sign_in"]) / 0.3, places=4)

    def test_pick_follows_the_loops_rules(self):
        bold = [{"title": f"b{i}", "target_step": s, "type": "redesign", "score": 1}
                for i, s in enumerate(["home", "adoption", "sign_in"])]
        small = [{"title": f"s{i}", "target_step": s, "type": "copy", "score": 9} for i, s in enumerate(loop.STEPS)]
        picked = scorer_study.pick(small + bold, key=lambda c: c["score"])
        self.assertEqual(len({c["target_step"] for c in picked}), len(picked))       # one test per step
        self.assertEqual(len(picked), loop.CONFIG["tests_per_round"])
        self.assertEqual(sum(c["type"] == "redesign" for c in picked), loop.CONFIG["bold_slots"])   # slots kept, though they score lower
        self.assertEqual([c["type"] for c in picked[:2]], ["redesign", "redesign"])

    def test_knowing_the_true_effect_beats_a_random_order_and_runs_repeat(self):
        pools = [[{"title": f"r{r}i{i}", "target_step": s, "type": "redesign", "score": 0}
                  for i, s in enumerate(loop.STEPS * 2)] for r in range(4)]
        oracle = sum(scorer_study.run(pools, BASE, "oracle", 0.5, k) for k in range(10))
        rand = sum(scorer_study.run(pools, BASE, "random", 0.5, k) for k in range(10))
        self.assertGreater(oracle, rand)
        self.assertEqual(scorer_study.run(pools, BASE, "oracle", 0.5, 3), scorer_study.run(pools, BASE, "oracle", 0.5, 3))


if __name__ == "__main__":
    unittest.main()
