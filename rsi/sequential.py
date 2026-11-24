"""Hourly harm checks that stay valid however often they are looked at.

Amplitude Experiment analyses every test with a mixture sequential probability
ratio test (mSPRT) by default, so results can be read at any time without
raising the false-alarm rate. This module uses the same kind of test for the
loop's hourly guardrail check (Johari et al., "Always Valid Inference", 2017;
the normal approximation for a difference in conversion rates).

HarmMonitor  one look per hour: is the treatment clearly worse on a guarded metric?
harm_bound   the finishers one bad test may cost before it is stopped, planned
             from the test's traffic for every size of drop
"""
import math

ALPHA = 0.05             # chance over a whole test that a harmless change is stopped by mistake
TAU_REL = 0.10           # mixing spread: tuned to drops of about 10% of the base rate


def always_valid_p(x1: int, n1: int, x2: int, n2: int, tau_rel: float = TAU_REL) -> tuple[float, float]:
    """mSPRT p-value for "treatment rate = control rate", and the observed difference.

    With a normal mixing distribution N(0, tau^2) over the true difference, the
    mixture likelihood ratio after n users is
        L = sqrt(V / (V + tau^2)) * exp(d^2 tau^2 / (2 V (V + tau^2)))
    where d is the observed difference and V its variance. 1 / L is a p-value
    that may be checked after every new user. Callers keep the running minimum.
    """
    if n1 < 2 or n2 < 2:
        return 1.0, 0.0
    p1, p2 = x1 / n1, x2 / n2
    pool = (x1 + x2) / (n1 + n2)
    v = max(pool * (1 - pool) * (1 / n1 + 1 / n2), 1e-12)
    tau2 = (tau_rel * max(p1, 1e-3)) ** 2
    d = p2 - p1
    log_l = 0.5 * math.log(v / (v + tau2)) + d * d * tau2 / (2 * v * (v + tau2))
    return min(1.0, math.exp(-log_l)), d


class HarmMonitor:
    """Hourly guardrail looks for one test. Each guarded metric gets ALPHA / k, so k metrics share ALPHA."""

    def __init__(self, metrics: list[str], alpha: float = ALPHA):
        self.alpha = alpha / max(1, len(metrics))
        self.metrics = list(metrics)
        self.best = dict.fromkeys(metrics, 1.0)      # running minimum: an always-valid p-value never goes back up

    def look(self, counts: dict) -> str | None:
        """counts: metric -> (x_control, n_control, x_treatment, n_treatment). Returns the harmed metric or None."""
        for m in self.metrics:
            p, d = always_valid_p(*counts[m])
            if d < 0:                                # only evidence that the treatment is worse counts
                self.best[m] = min(self.best[m], p)
                if self.best[m] < self.alpha:
                    return m
        return None


Z_PLAN = 1.645           # plan for the unlucky case: the observed drop 1.645 standard errors smaller than the true one


def users_to_detect(rate: float, drop: float, alpha: float, tau_rel: float = TAU_REL, z: float = Z_PLAN) -> float:
    """Users per group until a drop of `drop` (relative) in `rate` crosses the bound.

    Planned for an unlucky draw: the observed difference is taken z standard
    errors closer to zero than the true one, so about 19 times in 20 the real
    stop comes sooner.
    """
    true_d = rate * drop
    if true_d <= 0:
        return math.inf
    tau2 = (tau_rel * rate) ** 2
    var1 = rate * (1 - rate) + rate * (1 - drop) * (1 - rate * (1 - drop))   # per-user variance, both groups
    lo, hi = 2.0, 1e9
    for _ in range(200):
        n = math.sqrt(lo * hi)
        v = var1 / n
        d = max(true_d - z * math.sqrt(v), 0.0)
        log_l = 0.5 * math.log(v / (v + tau2)) + d * d * tau2 / (2 * v * (v + tau2))
        lo, hi = (lo, n) if log_l >= math.log(1 / alpha) else (n, hi)
    return hi


def harm_bound(rate: float, reach: float, finish_rate: float, slots: list[float], alpha: float) -> dict:
    """Planned cost of one bad test: finishers lost before the hourly check stops it, worst over every drop size.

    rate: the watched metric's base rate; reach: share of starting users who
    count toward it (1 for finishing overall); finish_rate: share of starting
    users who finish; slots: starting users per group in each hour of the
    test. A drop d on the watched metric costs finish_rate * d finishers per
    starting user in the treatment group. The check runs after every hour, so
    a test is stopped after the first hour in which enough users count. A small
    drop is caught late or never but costs little per user; a big one costs a
    lot per user but is caught fast. The plan assumes an unlucky draw (Z_PLAN),
    so about 19 runs in 20 cost less; stress_test.py measures how often more.
    """
    worst = {"finishers_lost": 0.0, "drop": 0.0, "hours_until_stop": len(slots)}
    for k in range(1, 100):
        drop = k / 100
        need = users_to_detect(rate, drop, alpha)
        starts, hours = 0.0, 0
        for slot in slots:
            starts += slot
            hours += 1
            if starts * reach >= need:
                break
        lost = finish_rate * drop * starts
        if lost > worst["finishers_lost"]:
            worst = {"finishers_lost": lost, "drop": drop, "hours_until_stop": hours}
    return worst
