"""A/B test backends.

Both backends have the same methods, so the loop does not care which one it
talks to:

  create(change, share) -> test id   a 50/50 test on `share` of new users
  start(test_id), stop(test_id)      turn it on or off
  read(test_id) -> results           users and conversions per group, per step
  mark(test_id) -> token             remember "now", for a re-test on fresh users
  read_since(test_id, token)         results from users who arrived after the mark
  ship(test_id)                      give the treatment to everyone

SimulatedExperiments is what the demo runs. AmplitudeExperiments shows the
real calls; it is not run in this demo because the app does not yet read
Amplitude Experiment variants.
"""
import base64
import datetime
import json
import math
import os
import random
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

STEPS = ["choose_path", "sign_in", "adoption", "home", "finish"]
PATTERN = json.loads((Path(__file__).resolve().parent.parent / "data" / "daily_pattern.json").read_text())
COUNT_KEYS = ["users", *STEPS]
BOLD_TYPES = {"reorder", "new_screen", "new_flow", "redesign"}


class SimulatedExperiments:
    """Fake new users walk through the funnel; the treatment group gets a hidden true effect.

    The true effect is decided by a hidden rule the loop never sees (see
    true_lift). The loop only gets user counts back, like it would from
    Amplitude.
    """

    def __init__(self, baseline: dict, weekly_new_users: int, seed: int, start_day: int | None = None):
        self.baseline = dict(baseline)        # step -> conversion rate into that step
        self.weekly_new_users = weekly_new_users
        self.rng = random.Random(seed)
        self.tests = {}
        # Real traffic shape from eight real weeks (data/daily_pattern.json, indexes only): users per weekday,
        # and each day's swing in the finish rate, which hits both groups of a test alike, as in real tests.
        self.weekday_share = list(PATTERN["weekday_share_last_4_weeks"].values())
        swings = [d["completion_index"] for d in PATTERN["days"]]
        if start_day is None:
            # The loop's runs: weeks start on a Monday, and the swings start at a random day of the eight weeks.
            self.day, self.first_weekday = random.Random(seed).randrange(len(swings)), 0
            self.day_swing = swings
        else:
            # The stress test: start on a given day of the eight weeks (day 0 is a Monday), with that day's
            # weekday and swing together, and swings centred on 1 so they do not shift the base rates.
            self.day, self.first_weekday = start_day, start_day % 7
            mean = sum(swings) / len(swings)
            self.day_swing = [x / mean for x in swings]
        self.hour = 0

    def true_lift(self, change: dict, luck: bool = True) -> float:
        """Hidden ground truth: relative change in the target step's conversion.

        Calibrated to published experiment results, where roughly a third of
        ideas help, a third make no measurable difference and a third hurt.
        The kind of change and where it lands shift the odds; the rest is luck
        the loop cannot see. The same idea helps less once the step is already good.
        """
        by_type = {"copy": 0.0, "hint": 0.005, "wait_info": 0.02, "notification": 0.0, "layout": 0.0,
                   "incentive": -0.01, "reorder": 0.0, "new_screen": -0.01, "new_flow": 0.0, "redesign": 0.0}
        # Assumption: big moves are not better on average, but they spread wider both ways.
        spread = 0.07 if change.get("type") in BOLD_TYPES else 0.035
        lift = by_type.get(change.get("type"), 0.0)
        step = change.get("target_step")
        if step == "sign_in" and change.get("type") in {"hint", "copy"}:
            lift += 0.02                      # sign-in confusion is real in the support mail
        if step in {"adoption", "home"} and change.get("type") == "wait_info":
            lift += 0.02                      # the long wait is where people give up
        if luck:                              # luck=False: only the part that kind and step explain
            lift += random.Random(change["title"]).gauss(0, spread)
        headroom = (1 - self.baseline.get(step, 0.8)) / 0.3
        return round(lift * headroom, 4)

    def create(self, change: dict, share: float) -> str:
        test_id = f"sim-{len(self.tests) + 1}"
        lift = self.true_lift(change)
        self.tests[test_id] = {"change": change, "lift": lift, "share": share,
                               "effects": {change["target_step"]: lift}, "weekdays": None,
                               "on": False, "control": _empty(), "treatment": _empty(),
                               "finishers_delta": 0.0, "carry": [0.0, 0.0]}
        return test_id

    def plant(self, test_id: str, effects: dict, weekdays: set | None = None) -> None:
        """Stress tests only: replace a test's hidden effects (step -> relative change), optionally on some weekdays."""
        t = self.tests[test_id]
        t["effects"], t["weekdays"] = dict(effects), weekdays
        t["lift"] = effects.get(t["change"]["target_step"], 0.0)

    def start(self, test_id: str) -> None:
        self.tests[test_id]["on"] = True

    def run_hour(self) -> None:
        """One more hour of traffic for every running test.

        Users per hour follow the real weekday shares, spread evenly over the
        day. The day's swing scales every step of both groups alike. A test's
        effects are relative changes per step; the loop's tests change only
        their target step, while the stress test may also plant harm further
        down the funnel or on some weekdays only. The expected change in
        finishers in each treatment group (hidden from the loop) is kept per
        test, so harm can be reported afterwards.
        """
        weekday = (self.first_weekday + self.hour // 24) % 7
        swing = self.day_swing[(self.day + self.hour // 24) % len(self.day_swing)] ** (1 / len(STEPS))
        base = {s: min(0.99, r * swing) for s, r in self.baseline.items()}
        finish = math.prod(base.values())
        for t in self.tests.values():
            if not t["on"]:
                continue
            active = t["weekdays"] is None or weekday in t["weekdays"]
            effects = t["effects"] if active else {}
            ratio = math.prod(min(base[s] * (1 + x), 0.99) / base[s] for s, x in effects.items())
            # fractional users carry over to the next hour so a week has exactly the planned traffic
            for g, key in enumerate(("control", "treatment")):
                t["carry"][g] += self.weekly_new_users * self.weekday_share[weekday] / 24 * t["share"] / 2
                n = int(round(t["carry"][g], 6))
                t["carry"][g] -= n
                _walk(self.rng, base, {} if key == "control" else effects, n, t[key])
                if key == "treatment":
                    t["finishers_delta"] += n * finish * (ratio - 1)
        self.hour += 1

    def run_week(self) -> None:
        """One more week of traffic for every running test."""
        for _ in range(7 * 24):
            self.run_hour()

    def stop(self, test_id: str) -> None:
        self.tests[test_id]["on"] = False

    def read(self, test_id: str) -> dict:
        t = self.tests[test_id]
        return {"control": dict(t["control"]), "treatment": dict(t["treatment"])}

    def mark(self, test_id: str) -> dict:
        return self.read(test_id)

    def read_since(self, test_id: str, mark: dict) -> dict:
        now = self.read(test_id)
        return {g: {k: now[g][k] - mark[g][k] for k in now[g]} for g in now}

    def ship(self, test_id: str) -> None:
        """A winner goes to everyone: the baseline for later weeks changes."""
        t = self.tests[test_id]
        step = t["change"]["target_step"]
        self.baseline[step] = min(0.98, self.baseline[step] * (1 + t["lift"]))


def _empty() -> dict:
    return dict.fromkeys(COUNT_KEYS, 0)


def _walk(rng, baseline, effects, n, counts) -> None:
    for _ in range(n):
        counts["users"] += 1
        for step in STEPS:
            p = baseline[step] * (1 + effects.get(step, 0.0))
            if rng.random() >= min(p, 0.99):
                break
            counts[step] += 1


def proportion_test(x1: int, n1: int, x2: int, n2: int) -> dict:
    """Pooled two-proportion z-test, with the relative lift and its delta-method standard error.

    When the control rate is 0 the relative lift is undefined; the absolute
    difference is reported instead. With no users the result is marked as
    fully uncertain (p = 1, standard error 1).
    """
    if n1 == 0 or n2 == 0:
        return {"control": 0, "treatment": 0, "lift": 0, "lift_se": 1.0, "p": 1.0}
    p1, p2 = x1 / n1, x2 / n2
    pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(max(pool * (1 - pool) * (1 / n1 + 1 / n2), 1e-12))
    p = math.erfc(abs((p2 - p1) / se) / math.sqrt(2))
    v1, v2 = p1 * (1 - p1) / n1, p2 * (1 - p2) / n2
    if p1 > 0:
        lift = (p2 - p1) / p1
        lift_se = math.sqrt(v2 + (p2 / p1) ** 2 * v1) / p1
    else:
        lift = p2 - p1
        lift_se = math.sqrt(v1 + v2) or 1.0
    return {"control": round(p1, 4), "treatment": round(p2, 4), "lift": round(lift, 4),
            "lift_se": round(lift_se, 4), "p": round(p, 6)}


PREVIOUS = {"choose_path": "users", "sign_in": "choose_path", "adoption": "sign_in",
            "home": "adoption", "finish": "home"}


def compare(result: dict, step: str) -> dict:
    """The test's own step (conversion from the step before), plus finishing onboarding overall."""
    c, t = result["control"], result["treatment"]
    prev = PREVIOUS[step]
    return {"step": proportion_test(c[step], c[prev], t[step], t[prev]),
            "finish": proportion_test(c["finish"], c["users"], t["finish"], t["users"]),
            "users_per_group": c["users"]}


class AmplitudeExperiments:
    """The same calls against Amplitude. Not run in this demo.

    Needs: AMPLITUDE_MANAGEMENT_KEY (Experiment management API key),
    AMPLITUDE_API_KEY and AMPLITUDE_SECRET_KEY (project keys for reading data),
    AMPLITUDE_PROJECT_ID and AMPLITUDE_DEPLOYMENT_ID. EVENTS must be set to the
    project's own onboarding event names.
    The app must fetch the variant for each new user and show the onboarding
    config in the variant payload; Amplitude then records which group each user
    is in as the user property "[Experiment] <key>".
    """

    EXP = "https://experiment.amplitude.com/api/1"
    DATA = "https://amplitude.com/api/2"
    EVENTS = {"users": "onboarding_started", "choose_path": "path_chosen", "sign_in": "sign_in_started",
              "adoption": "adoption_confirmed", "home": "home_first_seen", "finish": "onboarding_finished"}

    def __init__(self):
        self.keys = {}
        self.started_on = {}

    def _call(self, method, path, body=None):
        req = urllib.request.Request(
            f"{self.EXP}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {os.environ['AMPLITUDE_MANAGEMENT_KEY']}",
                     "Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # fixed https host
            raw = resp.read()
        return json.loads(raw) if raw else {}

    @staticmethod
    def _today() -> str:
        return datetime.date.today().strftime("%Y%m%d")

    def create(self, change: dict, share: float) -> str:
        slug = "".join(ch if ch.isalnum() else "-" for ch in change["title"].lower())[:30]
        key = f"onb-{slug}-{uuid.uuid4().hex[:8]}"    # titles can repeat across rounds; keys must not
        out = self._call("POST", "/experiments", {
            "projectId": os.environ["AMPLITUDE_PROJECT_ID"], "key": key, "name": change["title"],
            "description": change["change"], "evaluationMode": "remote", "bucketingKey": "amplitude_id",
            "deployments": [os.environ["AMPLITUDE_DEPLOYMENT_ID"]],
            "variants": [{"key": "control"}, {"key": "treatment", "payload": change.get("config", {})}],
            "rolloutWeights": {"control": 1, "treatment": 1}})
        self._call("PATCH", f"/experiments/{out['id']}", {"rolloutPercentage": share * 100})
        self.keys[out["id"]] = key
        return out["id"]

    def start(self, test_id: str) -> None:
        self._call("PATCH", f"/experiments/{test_id}", {"enabled": True})
        self.started_on[test_id] = self._today()

    def stop(self, test_id: str) -> None:
        self._call("PATCH", f"/experiments/{test_id}", {"enabled": False})

    def ship(self, test_id: str) -> None:
        """Everyone gets the treatment: all traffic, treatment weight only."""
        self._call("PATCH", f"/experiments/{test_id}/variants/control", {"rolloutWeight": 0})
        self._call("PATCH", f"/experiments/{test_id}", {"rolloutPercentage": 100, "enabled": True})

    def read(self, test_id: str) -> dict:
        return self._funnel(test_id, self.started_on[test_id], self._today())

    def mark(self, test_id: str) -> str:
        """A re-test reads a separate date range of newly arrived users, not a subtraction."""
        return (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y%m%d")

    def read_since(self, test_id: str, mark: str) -> dict:
        return self._funnel(test_id, mark, self._today())

    def _funnel(self, test_id: str, start: str, end: str) -> dict:
        """Funnel per group for users who started onboarding in [start, end] (Dashboard REST API)."""
        key = self.keys[test_id]
        token = f"{os.environ['AMPLITUDE_API_KEY']}:{os.environ['AMPLITUDE_SECRET_KEY']}"
        out = {}
        for variant in ("control", "treatment"):
            seg = [{"prop": f"gp:[Experiment] {key}", "op": "is", "values": [variant]}]
            params = [("e", json.dumps({"event_type": self.EVENTS[k]})) for k in COUNT_KEYS]
            params += [("start", start), ("end", end), ("s", json.dumps(seg))]
            req = urllib.request.Request(f"{self.DATA}/funnels?" + urllib.parse.urlencode(params), headers={
                "Authorization": "Basic " + base64.b64encode(token.encode()).decode()})
            with urllib.request.urlopen(req, timeout=60) as resp:  # fixed https host
                counts = json.load(resp)["data"][0]["cumulativeRaw"]
            out[variant] = dict(zip(COUNT_KEYS, counts, strict=True))
        return out
