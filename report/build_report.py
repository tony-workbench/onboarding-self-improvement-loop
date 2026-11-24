"""Build docs/index.html from data/, runs/, runs_control/, extra/ and long/. No network, no keys."""
import html
import math
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rsi.loop import BASE_RULES, CONFIG, STEPS, TRUST_AFTER  # noqa: E402
from rsi.safeguards import COMMON_ROLES, COMPONENT_TYPES, MAX_NEW_SCREENS, ROLES, SCREENS  # noqa: E402

E = html.escape
NAMES = {"choose_path": "Choose path", "sign_in": "Sign in", "adoption": "Adoption / generation",
         "home": "Home first view", "finish": "Onboarding completed"}


def pct(x, sign=False):
    return f"{x:+.1%}" if sign else f"{x:.1%}"


def badge(kind):
    text = {"real": "Real data", "sim": "Simulated", "model": "Model output from simulated results"}[kind]
    return f'<span class="badge {kind}">{text}</span>'


def funnel_svg(rates: dict, other: dict = None) -> str:
    w, h, pad, bh = 640, 40 * 6 + 20, 170, 22
    users, rows = 1.0, [("Started onboarding", 1.0, 1.0 if other else None)]
    ou = 1.0
    for s in STEPS:
        users *= rates[s]
        if other:
            ou *= other[s]
        rows.append((NAMES[s], users, ou if other else None))
    desc = "; ".join(f"{name} {v:.1%}" for name, v, _ in rows)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Share of starters reaching each step: {E(desc)}">']
    for i, (name, v, o) in enumerate(rows):
        y = 10 + i * 40
        out.append(f'<text x="{pad - 10}" y="{y + 15}" text-anchor="end" class="lbl">{E(name)}</text>')
        if o is not None:
            out.append(f'<rect x="{pad}" y="{y}" width="{(w - pad - 70) * o:.1f}" height="{bh}" class="bar2" rx="3"/>')
        out.append(f'<rect x="{pad}" y="{y + (8 if o is not None else 0)}" width="{(w - pad - 70) * v:.1f}" '
                   f'height="{bh - (8 if o is not None else 0)}" class="bar" rx="3"/>')
        val = f"{v:.1%}" + (f" → {o:.1%}" if o is not None and abs(o - v) > 1e-9 else "")
        out.append(f'<text x="{pad + (w - pad - 70) * max(v, o or 0) + 6:.1f}" y="{y + 15}" class="val">{val}</text>')
    out.append("</svg>")
    return "".join(out)


def weights_svg(series):
    w, h, left, top, bot = 640, 220, 40, 15, 30
    keys = ["impact", "evidence", "confidence", "cost"]
    n = len(series)
    maxv = max(max(s[k] for k in keys) for s in series) * 1.15
    def x(i):
        return left + i * (w - left - 110) / max(n - 1, 1)

    def y(v):
        return top + (h - top - bot) * (1 - v / maxv)
    desc = "; ".join(f"{k} from {series[0][k]:.2f} to {series[-1][k]:.2f}" for k in keys)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Rubric weights after each round: {E(desc)}">']
    for i in range(n):
        label = "start" if i == 0 else f"r{i}"
        out.append(f'<text x="{x(i):.1f}" y="{h - 8}" text-anchor="middle" class="lbl">{label}</text>')
    out.append(f'<line x1="{left}" x2="{w - 110}" y1="{y(1):.1f}" y2="{y(1):.1f}" class="grid"/>')
    for j, k in enumerate(keys):
        pts = " ".join(f"{x(i):.1f},{y(s[k]):.1f}" for i, s in enumerate(series))
        out.append(f'<polyline points="{pts}" class="line c{j}"/>')
        out.append(f'<text x="{x(n - 1) + 8:.1f}" y="{y(series[-1][k]) + 4:.1f}" class="val c{j}t">{k} {series[-1][k]:.2f}</text>')
    out.append("</svg>")
    return "".join(out)


CSS = """
:root{--bg:#fbfaf8;--fg:#1d1b19;--muted:#635e57;--card:#fff;--line:#e6e1da;--accent:#a9501d;--accent2:#ecd3c2;
--ok:#276b43;--okbg:#e3f2e8;--no:#a33b2b;--nobg:#f7e1dc;--real:#1f5f8b;--realbg:#e1edf6;--sim:#7a5a12;--simbg:#f6ecd2;
--c0:#a9501d;--c1:#1f5f8b;--c2:#276b43;--c3:#7a4aa3;--oncircle:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#171513;--fg:#ece8e2;--muted:#a39d94;--card:#211e1b;
--line:#36312c;--accent:#e08550;--accent2:#5a3a26;--okbg:#1d3326;--ok:#7fcf9c;--nobg:#3c211c;--no:#f0998a;--realbg:#1b2c3a;
--real:#8cc0e6;--simbg:#3a301a;--sim:#e0c378;--c0:#e08550;--c1:#8cc0e6;--c2:#7fcf9c;--c3:#c39ae6;--oncircle:#1d1b19}}
:root[data-theme="dark"]{--bg:#171513;--fg:#ece8e2;--muted:#a39d94;--card:#211e1b;
--line:#36312c;--accent:#e08550;--accent2:#5a3a26;--okbg:#1d3326;--ok:#7fcf9c;--nobg:#3c211c;--no:#f0998a;--realbg:#1b2c3a;
--real:#8cc0e6;--simbg:#3a301a;--sim:#e0c378;--c0:#e08550;--c1:#8cc0e6;--c2:#7fcf9c;--c3:#c39ae6;--oncircle:#1d1b19}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:960px;margin:0 auto;padding:36px 16px 90px}h1{font-size:32px;line-height:1.15;margin:0 0 10px;letter-spacing:-.01em}
h2{font-size:22px;margin:52px 0 10px;padding-top:14px;border-top:1px solid var(--line)}h3{font-size:17px;margin:26px 0 6px}h4{margin:20px 0 6px;font-size:15px}.layers h3{margin-top:0;font-size:15px}
p{max-width:760px}.lead{font-size:18px;color:var(--muted)}.muted{color:var(--muted)}.small{font-size:13px}
.badge{font-size:11px;font-weight:600;padding:2px 7px;border-radius:99px;vertical-align:2px;margin-left:6px;letter-spacing:.02em;white-space:nowrap}
.badge.real{background:var(--realbg);color:var(--real)}.badge.sim,.badge.model{background:var(--simbg);color:var(--sim)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:24px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.kpi b{display:block;font-size:24px;line-height:1.2}
.kpi span{font-size:13px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}th{font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}tr.ref td{font-weight:600;background:var(--simbg)}
.sub{font-size:12.5px;color:var(--muted);margin-top:2px}.tag{font-size:12px;padding:2px 7px;border-radius:6px;background:var(--line);white-space:nowrap}
.tag.yes{background:var(--okbg);color:var(--ok)}.tag.no{background:var(--nobg);color:var(--no)}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:10px 0}
.scroll{overflow-x:auto}a:focus-visible,summary:focus-visible{outline:2px solid var(--real);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
summary{cursor:pointer;font-weight:600}code{font-size:13px}svg{width:100%;height:auto;display:block}
svg .lbl{fill:var(--muted);font-size:12px}svg .val{fill:var(--fg);font-size:12px}svg .bar{fill:var(--accent)}svg .bar2{fill:var(--accent2)}
svg .grid{stroke:var(--line);stroke-dasharray:3 3}svg .line{fill:none;stroke-width:2.5}
.c0{stroke:var(--c0)}.c1{stroke:var(--c1)}.c2{stroke:var(--c2)}.c3{stroke:var(--c3)}
.c0t{fill:var(--c0)}.c1t{fill:var(--c1)}.c2t{fill:var(--c2)}.c3t{fill:var(--c3)}
.flow{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;counter-reset:s;margin:14px 0}
.flow div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:14px}
.flow div::before{counter-increment:s;content:counter(s);display:inline-block;width:20px;height:20px;border-radius:50%;background:var(--accent);color:var(--oncircle);
text-align:center;font-size:12px;line-height:20px;margin-right:6px}.legend span{margin-right:14px;font-size:13px}
.layers{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:12px}@media (max-width:860px){.layers{grid-template-columns:1fr}}.layers .card{margin:0}
.layers h4{margin-top:0}ul{padding-left:20px}li{margin:3px 0}a{color:var(--real)}
"""

SOURCES = [
    ("AlphaEvolve (Google DeepMind), arXiv 2506.13131", "https://arxiv.org/abs/2506.13131"),
    ("AlphaEvolve evaluation harness (Google Cloud docs)", "https://docs.cloud.google.com/gemini/enterprise/docs/alphaevolve/developer-guide/logical-architecture"),
    ("Dream-RSI: recursive self-improvement through evolving worlds (README)", "https://raw.githubusercontent.com/zhengkid/Dream-RSI/main/README.md"),
    ("A/B interactions: a call to relax (Microsoft ExP)", "https://www.microsoft.com/en-us/research/articles/a-b-interactions-a-call-to-relax/"),
    ("Kohavi et al., online controlled experiments at large scale (KDD 2013)", "https://courses.cs.washington.edu/courses/cse454/13wi/papers/p959-kohavi.pdf"),
    ("Sequential test vs. fixed-horizon t-test (Amplitude)", "https://amplitude.com/blog/sequential-test-vs-t-test"),
    ("How long to run an experiment (Optimizely)", "https://support.optimizely.com/hc/en-us/articles/4410283969165"),
    ("OWASP LLM06:2025 Excessive Agency", "https://genai.owasp.org/llmrisk/llm062025-excessive-agency/"),
    ("Auto-rollback (Spotify Confidence)", "https://confidence.spotify.com/glossary/auto-rollback"),
    ("Johari et al., Always valid inference: continuous monitoring of A/B tests (2017)", "https://arxiv.org/abs/1512.04922"),
    ("Sequential testing in Amplitude Experiment (mSPRT, the default)", "https://amplitude.com/docs/experiment/under-the-hood/experiment-sequential-testing"),
    ("Xia et al., Safe Velocity: controlled rollout at Microsoft (ICSE-SEIP 2019)", "https://www.microsoft.com/en-us/research/publication/safe-velocity-a-practical-guide-to-software-deployment-at-scale-using-controlled-rollout/"),
    ("Lindon et al., Rapid regression detection in software deployments through sequential testing (Netflix, KDD 2022)", "https://arxiv.org/abs/2205.14762"),
    ("Guarded rollouts (LaunchDarkly)", "https://launchdarkly.com/docs/home/releases/guarded-rollouts"),
    ("Schultzberg et al., Risk-aware product decisions in A/B tests with multiple metrics (Spotify, 2024)", "https://arxiv.org/abs/2402.11609"),
    ("Wu et al., Conservative bandits (ICML 2016)", "https://proceedings.mlr.press/v48/wu16.html"),
    ("Safety case template, claims-arguments-evidence (UK AI Security Institute)", "https://arxiv.org/abs/2411.08088"),
    ("FTC staff report: Bringing Dark Patterns to Light (2022)", "https://www.ftc.gov/system/files/ftc_gov/pdf/P214800%20Dark%20Patterns%20Report%209.14.2022%20-%20FINAL.pdf"),
    ("EU Digital Services Act, Article 25 (online interface design)", "https://www.springlex.eu/en/packages/dsa/dsa-regulation/article-25/"),
    ("EU AI Act prohibited practices: manipulative techniques (Future of Privacy Forum)", "https://fpf.org/blog/red-lines-under-the-eu-ai-act-understanding-manipulative-techniques-and-the-exploitation-of-vulnerabilities/"),
    ("UK Age Appropriate Design Code, standard 13: nudge techniques (ICO)", "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/childrens-code-guidance-and-resources/age-appropriate-design-a-code-of-practice-for-online-services/13-nudge-techniques/"),
    ("Experiment Management API (Amplitude)", "https://amplitude.com/docs/apis/experiment/experiment-management-api-experiments"),
    ("Deng et al., On post-selection inference in A/B tests (KDD 2021)", "https://arxiv.org/abs/1910.03788"),
    ("Wang et al., Denoising implicit feedback for recommendation (WSDM 2021)", "https://arxiv.org/abs/2006.04153"),
    ("Shao et al., Deep personalization: continuous context observation for local proactive agents (2026)", "https://arxiv.org/abs/2611.13457"),
]


SEEDS = [7, 11, 23, 31, 37, 41, 43, 47]
BATCHES = {
    "short": {"learn": lambda s: "runs" if s == 7 else f"extra/learn_{s}",
              "raw": lambda s: f"extra/learn_raw_{s}",
              "control": lambda s: "runs_control" if s == 7 else f"extra/control_{s}"},
    "long": {"learn": lambda s: f"long/learn_{s}", "raw": lambda s: f"long/raw_{s}",
             "control": lambda s: f"long/control_{s}"},
}
ARMS = {"learn": "Learning, denoised", "raw": "Learning, raw", "control": "No learning"}
def finish_rate(funnel: dict) -> float:
    return math.prod(funnel[s] for s in STEPS)


HARM_ARMS = {
    "check": {"short": lambda s: "runs" if s == 7 else f"extra/learn_{s}", "long": lambda s: f"long/learn_{s}"},
    "both": {"short": lambda s: f"extra/learn_budget_{s}", "long": lambda s: f"long/budget_{s}"},
    "off": {"short": lambda s: f"extra/learn_nostop_{s}", "long": lambda s: f"long/nostop_{s}"},
}
HARM_NAMES = {"check": "Hourly check (the default)", "both": "Hourly check and a weekly budget",
              "off": "One look at the end of the week"}


def decided_tests(folder: str) -> list:
    """Every decided test in a run, including re-tests resolved after the last round."""
    d = ROOT / folder
    out = [x for f in d.glob("round_*.json") for x in json.loads(f.read_text())["decisions"]]
    return out + json.loads((d / "summary.json").read_text()).get("final_retests", [])


def period_finishers(folder: str) -> float:
    """Finishers among all new users over the whole run: the live version each week, plus what tests added or cost."""
    d = ROOT / folder
    total = 0.0
    for f in d.glob("round_*.json"):
        r = json.loads(f.read_text())
        total += (r["ends_week"] - r["starts_week"] + 1) * CONFIG["weekly_new_users"] * finish_rate(r["funnel"])
        total += sum(x["finishers_delta_hidden"] for x in r["decisions"])
    return total          # test rounds only; re-tests resolved after the last round differ in length between runs


def harm_stats(name: str) -> dict:
    """The harm limits on, check only, and off; same seeds, learning with denoising in all three."""
    out = {}
    for arm, folders in HARM_ARMS.items():
        folder = folders[name]
        rates, lost, worst, period, stopped, tests, big = [], [], [], [], 0, 0, 0
        for seed in SEEDS:
            summary = json.loads((ROOT / folder(seed) / "summary.json").read_text())
            rates.append(finish_rate(summary["final_funnel"]))
            xs = decided_tests(folder(seed))
            per_test = [max(0.0, -x["finishers_delta_hidden"]) for x in xs]
            tests += len(xs)
            stopped += sum(x["outcome"].startswith("stopped early") for x in xs)
            big += sum(x["true_lift_hidden"] <= -0.10 for x in xs)
            lost.append(sum(per_test))
            worst.append(max(per_test, default=0.0))
            period.append(period_finishers(folder(seed)))
        out[arm] = {"mean": sum(rates) / len(rates), "rates": rates, "lost": sum(lost) / len(lost),
                    "worst": max(worst), "stopped": stopped, "tests": tests, "big": big,
                    "period": sum(period) / len(period), "periods": period}
    return out


def paired_lists(a: list, b: list) -> tuple[float, float]:
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    m = sum(diffs) / len(diffs)
    se = (sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1)) ** 0.5 / math.sqrt(len(diffs))
    return m, (m / se if se else 0.0)


def batch_stats(name: str):
    """Per arm: final finishing rate per seed, mean, sd, worst, shipped, bad shipped, re-test counts."""
    out = {}
    for arm, folder in BATCHES[name].items():
        rates, shipped, bad, rt_ok, rt_fail, rt_fail_good, finished, weeks, share = [], 0, 0, 0, 0, 0, [], None, None
        for seed in SEEDS:
            d = ROOT / folder(seed)
            summary = json.loads((d / "summary.json").read_text())
            rates.append(finish_rate(summary["final_funnel"]))
            weeks, share = summary["weeks_used"], summary["config"]["test_share"]
            finished.append(len(summary["history"]))
            decided = [x for f in d.glob("round_*.json") for x in json.loads(f.read_text())["decisions"]]
            decided += [{**x, "outcome": x["outcome"].replace("won, confirmed by re-test", "won after re-test, shipped")}
                        for x in summary.get("final_retests", [])]
            for x in decided:
                if "shipped" in x["outcome"]:
                    shipped += 1
                    bad += x["true_lift_hidden"] <= 0
                rt_ok += x["outcome"] == "won after re-test, shipped"
                if x["outcome"] == "lost: did not hold up in re-test":
                    rt_fail += 1
                    rt_fail_good += x["true_lift_hidden"] > 0
        m = sum(rates) / len(rates)
        sd = (sum((r - m) ** 2 for r in rates) / (len(rates) - 1)) ** 0.5
        out[arm] = {"rates": rates, "mean": m, "sd": sd, "worst": min(rates), "shipped": shipped, "bad": bad,
                    "rt_ok": rt_ok, "rt_fail": rt_fail, "rt_fail_good": rt_fail_good, "weeks": weeks, "share": share,
                    "finished": sum(finished) / len(finished)}
    return out


def batch_table(st: dict) -> str:
    head = "".join(f"<th>{E(ARMS[a])}</th>" for a in ARMS)
    rows = "".join("<tr><td>" + str(seed) + "</td>" + "".join(f"<td class='num'>{pct(st[a]['rates'][i])}</td>" for a in ARMS)
                   + "</tr>" for i, seed in enumerate(SEEDS))
    foot = ("<tr><td><b>Average</b></td>" + "".join(f"<td class='num'><b>{pct(st[a]['mean'])}</b></td>" for a in ARMS) + "</tr>"
            "<tr><td>Worst run</td>" + "".join(f"<td class='num'>{pct(st[a]['worst'])}</td>" for a in ARMS) + "</tr>"
            "<tr><td>Spread between runs (sd)</td>" + "".join(f"<td class='num'>{st[a]['sd'] * 100:.1f} pt</td>" for a in ARMS)
            + "</tr><tr><td>Shipped, of which actually bad</td>"
            + "".join(f"<td class='num'>{st[a]['shipped']}, {st[a]['bad']}</td>" for a in ARMS) + "</tr>"
            + "<tr><td>Re-tested winners: held, dropped (dropped but actually good)</td>"
            + "".join(f"<td class='num'>{st[a]['rt_ok']}, {st[a]['rt_fail']} ({st[a]['rt_fail_good']})</td>" for a in ARMS)
            + "</tr>")
    return (f"<div class='card'><table><thead><tr><th>Seed</th>{head}</tr></thead><tbody>{rows}</tbody>"
            f"<tfoot>{foot}</tfoot></table></div>")


T_CRIT_7DF = 2.365            # two-sided 95% critical value of t with 7 degrees of freedom (8 paired seeds)
T_CRIT_7DF_3 = 3.128          # the same with a Bonferroni correction for three comparisons (alpha 0.05 / 3)


def paired(st: dict, a: str, b: str) -> tuple[float, float, float]:
    """Mean of per-seed differences a - b, its standard error, and t."""
    diffs = [x - y for x, y in zip(st[a]["rates"], st[b]["rates"], strict=True)]
    m = sum(diffs) / len(diffs)
    se = (sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1)) ** 0.5 / math.sqrt(len(diffs))
    return m, se, m / se if se else 0.0


def noise_word(st: dict) -> str:
    return "difference beyond the noise" if abs(paired(st, "learn", "control")[2]) > T_CRIT_7DF else "difference within the noise"


def verdict(st: dict) -> str:
    parts = []
    for a, b in (("learn", "control"), ("raw", "control"), ("learn", "raw")):
        m, se, t = paired(st, a, b)
        sig = abs(t) > T_CRIT_7DF
        parts.append(f"{ARMS[a]} vs {ARMS[b].lower()}: {m * 100:+.1f} points on average across seeds "
                     f"(paired t = {t:.2f}; {'significant' if sig else 'not significant'} at 95%)")
    m, se, t = paired(st, "learn", "control")
    if abs(t) > T_CRIT_7DF:
        word = "better" if m > 0 else "worse"
        lead = (f"Learning with denoising did {word} than no learning, beyond the run-to-run noise for this one comparison; "
                + ("it also holds after correcting for the three comparisons made here."
                   if abs(t) > T_CRIT_7DF_3 else
                   "after correcting for the three comparisons made here it is borderline, so it needs repeating before "
                   "it counts as shown."))
    else:
        lead = ("No difference between the versions is beyond the run-to-run noise; "
                + ("the averages lean toward learning." if m > 0 else "the averages lean against learning."))
    return lead + " " + "; ".join(parts) + "."


def main():
    funnel = json.loads((ROOT / "data/funnel_week0.json").read_text())
    support = json.loads((ROOT / "data/support_week0.json").read_text())
    summary = json.loads((ROOT / "runs/summary.json").read_text())
    study = json.loads((ROOT / "runs/policy_study.json").read_text())
    rounds = [json.loads((ROOT / f"runs/round_{i}.json").read_text()) for i in range(1, CONFIG["rounds"] + 1)]
    audit = [json.loads(line) for line in (ROOT / "runs/audit.jsonl").read_text().splitlines()]
    n_tests = (ROOT / "tests" / "test_safeguards.py").read_text().count("    def test_")
    start = summary["start_funnel"]
    short, long_ = batch_stats("short"), batch_stats("long")
    stress = json.loads((ROOT / "runs/stress_test.json").read_text())
    scorer = json.loads((ROOT / "runs/scorer_study.json").read_text())
    harm_short, harm_long = harm_stats("short"), harm_stats("long")

    proposed = sum(len(r["candidates"]) for r in rounds)
    by_code = sum(1 for r in rounds for c in r["candidates"] if not c["guard"]["pass"] and c["guard"]["rule"] == "code")
    by_rule = sum(1 for r in rounds for c in r["candidates"] if not c["guard"]["pass"] and c["guard"]["rule"] != "code")

    steps_rows = "".join(
        f"<tr><td>{E(NAMES[s['step']])}</td><td><code>{E(s['event'])}</code></td>"
        f"<td class='num'>{pct(s['conversion_from_previous'])}</td><td class='num'>{s['median_seconds_from_previous']} s</td>"
        f"<td class='num'>{s['mean_seconds_from_previous'] / 60:.0f} min</td></tr>" for s in funnel["steps"])
    theme_rows = "".join(f"<tr><td>{E(t['theme'])}</td><td>{E(t['step'].replace('_', ' '))}</td>"
                         f"<td class='num'>{t['count']}</td></tr>" for t in support["themes"])

    def reason(c):
        g = c["guard"]
        return f"Blocked by code: {g['reason']}" if g["rule"] == "code" else f"Blocked by rule {g['rule']}: {g['reason']}"

    def pval(p):
        return "&lt;0.0001" if p < 0.0001 else f"{p:.4f}"

    round_html = []
    for rd in rounds:
        rows = []
        for c in rd["candidates"]:
            if not c["guard"]["pass"]:
                st, sc, note = '<span class="tag no">Blocked</span>', "—", reason(c)
            elif c["title"] in rd["picked"]:
                slot = " (big-move slot)" if c.get("slot") == "big move" else ""
                st, sc, note = f'<span class="tag yes">Tested{slot}</span>', f"{c['score']:.1f}", c["change"]
            else:
                st, sc, note = '<span class="tag">Not picked</span>', f"{c['score']:.1f}", c["change"]
            rows.append(f"<tr><td>{E(c['title'])}<div class='sub'>{E(note)}</div></td>"
                        f"<td>{E(NAMES[c['target_step']])}</td><td class='num'>{sc}</td><td>{st}</td></tr>")
        drows = []
        for d in rd["decisions"]:
            res = d["result"]["retest"] if "retest" in d["result"] else d["result"]
            label = " (re-test week)" if "retest" in d["result"] else ""
            when = f" · stopped after {d['hours']} h" if d.get("hours") else ""
            drows.append(f"<tr><td>{E(d['title'])}<div class='sub'>{E(NAMES[d['target_step']])}{label} · "
                         f"{d['share']:.0%} of new users{when}</div></td>"
                         f"<td class='num'>{res['users_per_group']:,}</td>"
                         f"<td class='num'>{pct(res['step']['lift'], True)}</td><td class='num'>{pval(res['step']['p'])}</td>"
                         f"<td><span class='tag {'yes' if d['outcome'].startswith('won') else 'no'}'>{E(d['outcome'])}</span></td></tr>")
        lessons = "".join(f"<li>{E(x)}</li>" for x in rd["lessons_next"])
        shipped = ", ".join(rd["shipped"]) or "nothing"
        held = rd.get("held_by_harm_budget", [])
        held_txt = (f"<p class='muted small'>Held back by the weekly harm budget: {E(', '.join(held))}.</p>" if held else "")
        carried = len(rd.get("carried_retests", []))
        carried_txt = f" · {carried} re-test{'s' if carried != 1 else ''} carried in" if carried else ""
        open_attr = " open" if rd["round"] in (1, len(rounds)) else ""
        round_html.append(f"""
<details{open_attr}>
<summary>Round {rd['round']} <span class="muted">· week {rd['starts_week']} · {len(rd['candidates'])} ideas ·
{sum(not c['guard']['pass'] for c in rd['candidates'])} blocked · {len(rd['picked'])} new tests{carried_txt} · shipped: {E(shipped)}</span></summary>
<h3>Ideas, safeguards and scores {badge('real')}</h3>
<div class="scroll"><table><thead><tr><th>Idea</th><th>Step</th><th>Score</th><th>Result</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h3>A/B results {badge('sim')}</h3>
{held_txt}<div class="scroll"><table><thead><tr><th>Test</th><th>Users per group</th><th>Change on its step</th><th>p</th><th>Decision</th></tr></thead><tbody>{''.join(drows) or '<tr><td colspan="5">No test was decided this round.</td></tr>'}</tbody></table></div>
<h3>Lessons for the next round {badge('model')}</h3>
<ul>{lessons}</ul>
</details>""")

    srows = "".join(
        f"<tr{' class=ref' if r['factor'] == 'reference' else ''}><td>{E(r['label'])}</td><td class='num'>{pct(r['gain'], True)}</td>"
        f"<td class='num'>{r['shipped']:.1f}</td><td class='num'>{r['false_wins']:.2f}</td><td class='num'>{r['harmed']:.2f}</td></tr>"
        for r in study["rows"])

    weights_series = [rounds[0]["weights_used"]] + [rd["weights_next"] for rd in rounds]
    first, last = weights_series[0], weights_series[-1]
    up = [k for k in last if last[k] > first[k] * 1.15]
    down = [k for k in last if last[k] < first[k] * 0.85]
    weights_story = ((f"{' and '.join(chr(34) + k + chr(34) for k in up)} gained weight" if up else "no weight rose much")
                     + (f", while {' and '.join(chr(34) + k + chr(34) for k in down)} lost it." if down else "."))

    components = ", ".join(f"<code>{k}</code>" for k in sorted(COMPONENT_TYPES))
    roles = "; ".join(f"<code>{k}</code>: {', '.join(v)}" for k, v in ROLES.items()) + f"; every screen: {', '.join(COMMON_ROLES)}"
    screens = ", ".join(f"<code>{k}</code>" for k in SCREENS)
    blocked_log = sum(1 for a in audit if not a["allowed"])
    rules, cur = [], None
    for line in BASE_RULES.splitlines()[1:]:
        t = line.strip()
        if t[:2] in {"1.", "2.", "3.", "4.", "5."}:
            cur = [t[3:]]
            rules.append(cur)
        elif cur is not None and t:
            cur.append(t)
    rules_html = "".join(f"<li>{E(' '.join(r))}</li>" for r in rules)
    src_html = "".join(f'<li><a href="{u}">{E(t)}</a></li>' for t, u in SOURCES)
    rt_held = sum(b[a]["rt_ok"] for b in (short, long_) for a in ARMS)
    rt_dropped = sum(b[a]["rt_fail"] for b in (short, long_) for a in ARMS)
    rt_dropped_good = sum(b[a]["rt_fail_good"] for b in (short, long_) for a in ARMS)
    rt_all = rt_held + rt_dropped
    retest_story = ("So in these runs the re-test cost some good changes without catching a bad one; its value would show only "
                    "where more of the winners are false." if rt_dropped and rt_dropped_good == rt_dropped else
                    f"It stopped {rt_dropped - rt_dropped_good} change(s) that were actually bad.")
    by_label = {r["label"]: r for r in study["rows"]}
    fw_corrected = by_label["Up to 2 weeks per test, weekly looks, corrected"]["false_wins"]
    fw_uncorrected = by_label["Up to 2 weeks per test, weekly looks, no correction"]["false_wins"]
    ref = next(r for r in study["rows"] if r["factor"] == "reference")
    expo_full = by_label["100% of new users in tests"]["harmed"] / ref["harmed"]

    st_set = stress["settings"]
    raw_caveat = (" (In the 20-week batch above, learning from raw results still ended higher on average; the difference is within "
                  "the noise.)" if long_["raw"]["mean"] > long_["learn"]["mean"] else "")
    plan = stress["planned_cost"]

    def hours_txt(h):
        return "—" if h is None else f"{h:.0f} h"

    def stress_row(r):
        return (f"<tr><td>{E(NAMES[r['step']])}</td><td>{E(r['harm_on'])}</td><td class='num'>-{r['drop']:.0%}</td>"
                f"<td class='num'>{r['stopped_share']:.0%}</td>"
                f"<td class='num'>{hours_txt(r['median_hours_to_stop'])}</td>"
                f"<td class='num'>{r['finishers_lost_mean']:.0f} ({r['finishers_lost_p95']:.0f})</td>"
                f"<td class='num'>{r['finishers_lost_without_stop']:.0f}</td>"
                f"<td class='num'>{plan[r['step']]:.0f}</td><td class='num'>{r['over_plan_share']:.1%}</td></tr>")
    stress_rows = "".join(stress_row(r) for r in stress["planted"] if r["drop"] in (0.10, 0.30, 0.90))
    harder_rows = "".join(stress_row(r) for r in stress["harder"])
    fa = stress["false_alarms"]
    big_cells = [r for r in stress["planted"] if r["drop"] >= 0.30]
    big_stopped = min(r["stopped_share"] for r in big_cells)
    slowest_big = max(r["p95_hours_to_stop"] for r in big_cells)
    all_cells = stress["planted"] + stress["harder"]
    worst_over = max(all_cells, key=lambda r: r["over_plan_share"])
    planted_over = max(r["over_plan_share"] for r in stress["planted"])
    planned_total = sum(plan.values())
    budget_cfg = json.loads((ROOT / HARM_ARMS["both"]["long"](SEEDS[0]) / "summary.json").read_text())["config"]["harm_budget"]
    test_ratio = harm_long["both"]["tests"] / harm_long["check"]["tests"]
    budget_saved = harm_long["check"]["lost"] - harm_long["both"]["lost"]
    budget_cost = harm_long["check"]["period"] - harm_long["both"]["period"]

    def scorer_cell(r):
        if r["vs_model"] == 0:
            return pct(r["mean"])
        lo, hi = r["vs_model_95"]
        return f"{pct(r['mean'])} ({r['vs_model'] * 100:+.1f} pt; 95% interval {lo * 100:+.1f} to {hi * 100:+.1f})"
    scorer_names = {"random": "Random order", "model": "The model's scores from the saved run",
                    "learnable": "Knows the average effect of each kind of change on each step",
                    "oracle": "Knows each idea's true effect (upper bound)"}
    scorer_rows = "".join(f"<tr><td>{scorer_names[k]}</td><td class='num'>{scorer_cell(scorer['short'][k])}</td>"
                          f"<td class='num'>{scorer_cell(scorer['long'][k])}</td></tr>" for k in scorer_names)
    pools = [sum(c["guard"]["pass"] for c in json.loads(f.read_text())["candidates"])
             for name in ("short", "long") for s_ in SEEDS for f in (ROOT / BATCHES[name]["learn"](s_)).glob("round_*.json")]
    ideas_per_round = sum(pools) / len(pools)
    sl, ll = scorer["short"]["learnable"], scorer["long"]["learnable"]
    so, lo_ = scorer["short"]["oracle"], scorer["long"]["oracle"]
    model_vs_random = max(scorer["short"]["random"]["vs_model"], scorer["long"]["random"]["vs_model"]) >= 0
    if not ll["significant"] and ll["vs_model_95"][1] < lo_["vs_model"] / 2:
        scorer_story = (f"Over 20 weeks, even exact knowledge of the average effect of each kind of change on each step adds at most "
                        f"about {ll['vs_model_95'][1] * 100:.1f} points (95% interval), against {lo_['vs_model'] * 100:.1f} for knowing "
                        f"each idea's true effect. Over 8 weeks the interval for it reaches {sl['vs_model_95'][1] * 100:.1f} points, "
                        f"so a gain there is not shown but not ruled out. In this simulator most of an idea's effect is its own luck, "
                        f"which the simulator draws from the idea's title, not from its content, so there is little for learning from "
                        f"past tests to find.")
    else:
        scorer_story = ("Knowing the average effect of each kind of change on each step adds a gain beyond the noise in at least "
                        "one batch, so there is something here for learning to find.")
    def harm_table(h):
        arms = list(HARM_ARMS)
        rows = [("Finishing onboarding at the end", lambda x: pct(x["mean"])),
                ("Finishers among all new users over the whole run", lambda x: f"{x['period']:,.0f}"),
                ("Finishers lost inside tests, per run", lambda x: f"{x['lost']:.0f}"),
                ("Worst single test (finishers lost)", lambda x: f"{x['worst']:.0f}"),
                ("Tests that truly lowered their step by 10% or more", lambda x: str(x["big"])),
                ("Tests stopped early by the hourly check", lambda x: str(x["stopped"]) if x["stopped"] else "—"),
                ("Tests run (all 8 runs)", lambda x: str(x["tests"]))]
        head = "".join(f"<th>{E(HARM_NAMES[a])}</th>" for a in arms)
        body = "".join(f"<tr><td>{label}</td>" + "".join(f"<td class='num'>{fmt(h[a])}</td>" for a in arms) + "</tr>"
                       for label, fmt in rows)
        return f"<div class='card'><table><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></div>"

    def harm_verdict(h):
        off = h["off"]
        parts = []
        for arm in ("check", "both"):
            x = h[arm]
            cut = 1 - x["lost"] / off["lost"] if off["lost"] else 0
            m, t = paired_lists(x["periods"], off["periods"])
            sig = "beyond" if abs(t) > T_CRIT_7DF else "within"
            parts.append(f"{HARM_NAMES[arm]}: {cut:.0%} fewer finishers lost inside tests, worst single test "
                         f"{x['worst']:.0f} instead of {off['worst']:.0f}, and {m:+,.0f} finishers over the whole run "
                         f"(paired t = {t:.2f}, {sig} the run-to-run noise)")
        return "Against one look at the end of the week. " + "; ".join(parts) + "."

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Onboarding Self-Improvement Loop</title><style>{CSS}</style></head><body><main>
<h1>Onboarding self-improvement loop</h1>
<p class="lead">An AI loop that finds where new users drop out of onboarding, proposes changes (big ones included), blocks anything
that would delete a step or a job a screen does, reach outside onboarding or pressure users, A/B tests the rest, ships the winners,
and rewrites its own lessons and scoring from denoised results. A round ends when its tests have results; the next round starts at
once, on top of the improved version.</p>
<p class="legend"><span>{badge('real')} real data or real model output</span><span>{badge('sim')} simulated A/B users</span></p>
<div class="kpis">
<div class="kpi"><b>{pct(finish_rate(start))}</b><span>finish onboarding today (real)</span></div>
<div class="kpi"><b>{pct(short['learn']['mean'])}</b><span>after 8 weeks, average of 8 runs with learning (simulated; no learning: {pct(short['control']['mean'])}; {noise_word(short)})</span></div>
<div class="kpi"><b>{pct(long_['learn']['mean'])}</b><span>after 20 weeks on all new users, with learning (simulated; no learning: {pct(long_['control']['mean'])}; {noise_word(long_)})</span></div>
<div class="kpi"><b>{by_code + by_rule} of {proposed}</b><span>ideas blocked in the main run ({by_code} by code, {by_rule} by the model reviews)</span></div>
</div>

<h2>How one round works</h2>
<div class="flow">
<div>Read the funnel and support themes through the data gateway</div><div>The model writes {CONFIG['candidates_per_round']} ideas as onboarding config, asked to make at least {CONFIG['bold_min_ideas']} of them big moves</div>
<div>Code check, rule review and fairness review; any of them blocks</div><div>{CONFIG['bold_slots']} test slots go to big moves, then the best idea per funnel step, up to {CONFIG['tests_per_round']} tests</div>
<div>Test them at once on {CONFIG['test_share']:.0%} of new users, 50/50, for one week; check every hour and stop any test that is clearly harmful</div><div>Ship every winner; re-test a winner first if its effect is mostly noise; roll back anything that clearly lowers finishing</div>
<div>Shrink results by their noise, rewrite lessons and rubric weights, start the next round</div></div>
<p>Steps 1 to 4 use real data and a real model (Gemini); step 7 is the same model learning from the simulated results. Step 5 uses simulated users because the app cannot yet switch
onboarding per user; the code that would call Amplitude instead is in the repository. This is the same shape as AlphaEvolve: a
generator proposes, a strict checker filters, a measured result decides what survives, and the result feeds the next round. The
"self" part is that the loop also rewrites the lessons and weights it uses to choose.</p>

<h2>Starting point: where users drop out {badge('real')}</h2>
<p class="muted small">{E(funnel['week'])}. {E(funnel['source'])}. {E(funnel['published_as'])}.</p>
<div class="card">{funnel_svg(start)}<p class="muted small">Share of everyone who started onboarding that reaches each step.</p></div>
<div class="card"><table><thead><tr><th>Step</th><th>Event</th><th>Reached from previous step</th><th>Median time</th><th>Mean time</th></tr></thead>
<tbody>{steps_rows}</tbody></table></div>
<p>The biggest single loss is between sign in and the adoption certificate: about 4 in 10 users stop there, which covers picking a
friend or uploading photos for their own pet. The median time there is under two minutes but the mean is about 17 minutes, so a
smaller group gets stuck for a long time.</p>
<h3>Support mail that week {badge('real')}</h3>
<p class="muted small">{support['emails_read']} inbound emails; {support['by_step'].get('not_about_the_app', 0)} were not about the app.
{E(support['method'][0].upper() + support['method'][1:])}.</p>
<div class="card"><table><thead><tr><th>Theme</th><th>Step</th><th>Emails</th></tr></thead><tbody>{theme_rows}</tbody></table></div>

<h2>Safeguards</h2>
<p>The aim is not to stop the AI from making big changes; it is to make sure no change deletes part of the product, reaches
outside onboarding, or treats users unfairly. Every limit below is enforced in code, outside the model, following OWASP's guidance on
excessive agency (minimal tools, minimal permissions, authorization in code rather than in the model, logs of every action) and
automatic rollback.</p>
<div class="layers">
<div class="card"><h3>1. Big moves allowed, no step or job lost</h3><p class="small">Inside onboarding the model may redesign any
screen, build screens from new components ({components}), add up to {MAX_NEW_SCREENS} new screens or whole sub-flows (also after the
home intro), move sign in later (after adoption, for example), and replace any part of a screen with something better. Code makes
sure it cannot lose a step or a job: every existing screen ({screens}) stays, in its order; each part has a named job ({roles}), and a
replacement must use components that can really do it, with real content (a stamp needs a stamp asset, the path choice needs two
distinct options for adopting and making your own, a sign-in button must say it signs in). Nothing on the sign-in screen may lead past
it without signing in. Layouts and styles come from fixed lists, so nothing can be hidden. A change may only edit the screens of its
own funnel step, and tests that run together never edit the same screen. Anything that names something outside onboarding, including
new screens that look like payment, sign-up, account or settings screens, is rejected before any test exists.</p></div>
<div class="card"><h3>2. Fair design</h3><p class="small">Regulators do not limit how much a product changes; they limit changes that
deceive or pressure people. Code handles what code can check reliably: text is normalised (look-alike, full-width and invisible
characters are rejected), links, addresses and markup are blocked, timers may only count a real wait, inputs may only ask for the pet's
name, choices may not be age ranges, and a short list of phrases that are never fine (prices, skipping, pressure, shaming, personal
questions) is blocked. Meaning is judged by a separate fairness review, a model call that reads every user-facing text and blocks
anything that mentions money, suggests skipping, pressures, shames or asks about the person, however it is worded. Broad word lists
were tried first: they both missed rewordings and blocked ordinary copy such as "feel free to look around". Because a pet app has young
users, nothing may nudge children toward sharing more data (UK Age Appropriate Design Code, standard 13).</p></div>
<div class="card"><h3>3. What the loop may do</h3><p class="small">Experiment calls go through one wrapper: create, start, stop, read,
re-test and ship, only for tests this loop created, at most {CONFIG['tests_per_round']} running at once, traffic between 0 and the cap
(checked against the number actually sent). Titles and descriptions sent to the platform are checked for links and markup. Other calls
raise an error. Every hour, a test that is clearly worse on its step, the next step or finishing is switched off (see Harm limits).</p></div>
<div class="card"><h3>4. What data it may read</h3><p class="small">Read-only, through a gateway that serves the onboarding funnel
(onboarding events only) and the anonymized support themes. No user-level data, no raw mail, no keys: the model never holds a
credential. Support themes reach the model marked as data, not instructions.</p></div>
<div class="card"><h3>5. Base rules</h3><p class="small">A rule review, another model call that sees every full config, applies
the company's rules; a change ships only if the code check, the rule review and the fairness review all pass it:</p><ul class="small">{rules_html}</ul></div>
</div>
<p>{n_tests} safeguard tests check both sides: that big moves pass (a redesigned screen, a whole new sub-flow, sign in moved, the stamp
or the pet picker replaced by something that does the same job) and that every way to delete, leave or pressure is blocked, including
each bypass found by a red-team pass (look-alike characters, prices in words, hidden layouts, empty replacements, fake payment or
sign-in screens, buttons past sign-in, hollow replacements, over-long configs, traffic outside the cap, tests left unclosed), plus 34
ordinary onboarding lines that must not be blocked. In the main run the audit log holds {len(audit)} entries; {blocked_log} are blocked
attempts. The two model reviews are not guarantees and can be wrong in both directions; every block and its reason is listed in the
round tables below.</p>

<h2>Harm limits: what one bad test can cost {badge('sim')}</h2>
<p>The safeguards above decide what a change may be. They do not limit what a permitted change does to the users who see it while it
is tested: a fair, in-scope redesign can still make a step much harder. Before these limits, every test ran a full week and was judged
once at the end, so a change that cut a step by a fifth hit every user in its group for seven days. A company deploying this needs a
number for what one test can cost. Two parts give it, and a third is optional.</p>
<ul>
<li><b>Hourly checks that stay valid however often they are read.</b> Every hour each test is checked on its own step, the step after
it, and finishing onboarding. The check is a mixture sequential probability ratio test, the method Amplitude Experiment uses by default,
so reading it every hour does not raise the false-alarm rate; the {CONFIG['harm_alpha']:.0%} allowed over a whole test is shared by the
three metrics. A test that is clearly worse on any of them is switched off at once, its users go back to the current version, and the
experiment wrapper refuses to ship it. Amplitude does not switch a test off by itself, so the loop does it. This follows controlled
rollout at Microsoft, Netflix's sequential canary tests, LaunchDarkly's guarded rollouts and Spotify's guardrail metrics.</li>
<li><b>A planned cost for every test.</b> A big drop is caught within hours; a small one may never be proven within the week, but costs
little per user. Before a test starts, the loop computes for every drop from 1% to 99%, on the test's own step, on the next step and
further down (where only finishing overall sees it), and for every weekday the test could start on, how many finishers it would cost
before the check stops it, and takes the largest. Each case is planned for an unlucky draw, so about 19 runs in 20 should cost less;
it is a planned bound, not a guarantee. At {st_set['share']:.0%} of new users it is {min(plan.values()):.0f} to
{max(plan.values()):.0f} finishers per test, depending on the step, against about {st_set['weekly_finishers']:,} finishers in a
simulated week.</li>
<li><b>An optional weekly harm budget.</b> The planned costs of all tests running in a week can be capped at a share of the week's
finishers (<code>RSI_HARM_BUDGET</code>); a test that does not fit gets less traffic, down to a fifth of the usual share, or is skipped
that round. Without a cap, the week is limited only by the {CONFIG['tests_per_round']} tests that may run at once, which together plan
for {planned_total:.0f} finishers ({planned_total / st_set['weekly_finishers']:.0%} of a week's). The cap is off by default, because
the comparison below shows what a {budget_cfg:.0%} cap costs.</li>
</ul>
<h3>Stress test: planted harm and false alarms</h3>
<p>Deliberately bad changes cannot be shown to real users, so the stress test runs in the simulator, with the real traffic shape:
weekday shares and the day-to-day swings in the finish rate from eight real weeks of the daily report. Each test starts on a different
one of those {st_set['start_days']} days, with its weekday and its swing, so every weekend, quiet day and busy day is covered; a swing
hits both groups of a test alike, as in a real test. {st_set['runs_per_cell']} tests per cell, at {st_set['share']:.0%} of new
users.</p>
<p><b>False alarms:</b> {fa['stopped']} of {fa['tests']} harmless tests ({fa['rate']:.1%}) were stopped by mistake, within the
{CONFIG['harm_alpha']:.0%} allowed. That is the cost of a false alarm: one good idea dropped, nobody harmed.</p>
<div class="card"><table><thead><tr><th scope="col">Step changed</th><th scope="col">Where the harm is</th><th scope="col">True drop</th>
<th scope="col">Stopped within the week</th><th scope="col">Median time to stop</th><th scope="col">Finishers lost: mean (95th percentile)</th>
<th scope="col">Lost if run the whole week</th><th scope="col">Planned cost</th><th scope="col">Runs over the plan</th></tr></thead>
<tbody>{stress_rows}</tbody></table>
<p class="muted small">Drops of 30% or more on the changed step were stopped in at least {big_stopped:.1%} of runs, and 19 runs in 20
were stopped within {slowest_big:.0f} hours. At most {planted_over:.1%} of runs in any cell cost more than the plan. All drops from 5% to
90% are in <code>runs/stress_test.json</code>.</p></div>
<h4>Harder cases</h4>
<p>Harm two steps further down than the changed step is seen only through finishing overall, which has the lowest rate, so it is
caught most slowly; the plan includes it. Harm on Saturdays and Sundays only is diluted by weekday data in the running total.</p>
<div class="card"><table><thead><tr><th scope="col">Step changed</th><th scope="col">Where the harm is</th><th scope="col">True drop</th>
<th scope="col">Stopped within the week</th><th scope="col">Median time to stop</th><th scope="col">Finishers lost: mean (95th percentile)</th>
<th scope="col">Lost if run the whole week</th><th scope="col">Planned cost</th><th scope="col">Runs over the plan</th></tr></thead>
<tbody>{harder_rows}</tbody></table>
<p class="muted small">The case most often over the plan is {E(NAMES[worst_over['step']].lower())}, {E(worst_over['harm_on'])},
-{worst_over['drop']:.0%}: {worst_over['over_plan_share']:.1%} of runs.</p></div>
<h3>The same loop with and without the checks</h3>
<p>Learning with denoising, same seeds, run three ways: with the hourly check only (the default), with the check and a
{budget_cfg:.0%} weekly budget, and with one look at the end of each week. Finishers lost uses the simulator's hidden true effects,
which a real deployment would not know; it is the number the checks exist to keep small. Finishers over the whole run counts every
new user in the test rounds, at the version live that week plus what the tests added or cost, so a limit that slows improvement shows
up there.</p>
<h4>8 weeks on 50% of new users</h4>
{harm_table(harm_short)}
<p>{harm_verdict(harm_short)}</p>
<h4>20 weeks on all new users</h4>
{harm_table(harm_long)}
<p>{harm_verdict(harm_long)}</p>
<p><b>What we chose.</b> The hourly check cuts the worst single test from {harm_long['off']['worst']:.0f} to
{harm_long['check']['worst']:.0f} finishers on all new users ({harm_short['off']['worst']:.0f} to {harm_short['check']['worst']:.0f} at
half the traffic, where tests are smaller and slower to prove), and changes the end result by an amount within the run-to-run noise, so
it is always on. The {budget_cfg:.0%} weekly budget cuts the harm inside tests further, but on all new users over 20 weeks it ran
{test_ratio:.0%} as many tests, saved about {budget_saved:.0f} finishers per run inside tests, and still ended about {budget_cost:,.0f} finishers
behind over the whole run, because improvement slowed. It stays available for a company that would rather improve more slowly than risk a bad week, set with
<code>RSI_HARM_BUDGET</code>.</p>
<h3>What this does not show</h3>
<ul>
<li>Users per hour are spread evenly over each day; real traffic has quiet nights and busy evenings, which slows the check at night.</li>
<li>Simulated users go through the whole funnel at once. Real users take minutes to days, so finishing counts lag and a real stop comes
later than planned here. The check also needs funnel data every hour; the Amplitude code in this repository reads by day, and hourly
reading has not been tried on the app.</li>
<li>Tests run at the same time share one slice of users and are watched one by one. Their combined effect, and the combined effect of
winners shipped together, is not watched; it is assumed to be the sum of their single effects.</li>
<li>Harm here means fewer users reaching the next step or finishing. Harm that shows later (fewer users coming back in a week, more
support mail) is not watched by the hourly check.</li>
<li>All of it is simulated. Before real traffic, an A/A test on the app (both groups see the current onboarding) should confirm that
assignment, events and the check behave as here.</li>
</ul>

<h2>Choosing how many tests and how long {badge('sim')}</h2>
<p>Five tests and one week are not guesses. We ran each setup for {study['horizon_weeks']} simulated weeks, {study['seeds']} times, on the ideas the model
wrote, with true effects calibrated to published results (roughly a third of ideas help, a third make no measurable difference and a
third hurt). One assumption is ours, not from a source: big moves are no better on average than small ones, but their effects spread
twice as wide in both directions. Each row changes one thing from the chosen setup.</p>
<div class="card"><table><thead><tr><th>Setup</th><th>Gain in finishing onboarding</th><th>Changes shipped</th>
<th>Shipped changes that were actually bad</th><th>Exposure to bad changes</th></tr></thead><tbody>{srows}</tbody></table>
<p class="muted small">Chosen setup: up to {CONFIG['tests_per_round']} tests at once, one per funnel step, all sharing {CONFIG['test_share']:.0%} of new users; one full week each, one look
at the end to decide a winner; ship every winner. (This study predates the hourly harm checks, which only ever stop tests early.) Exposure counts, per week on average, the share of new users sitting in a treatment that is actually
worse (a user in several tests counts several times).</p></div>
<ul>
<li><b>Share traffic, don't split it.</b> Giving each test its own slice leaves each with too few users; it ships fewer winners and
more false ones. Microsoft runs hundreds of overlapping tests for the same reason, isolating only tests that touch the same thing. Here
that means one test per funnel step.</li>
<li><b>More tests at once is better</b>, up to one per step.</li>
<li><b>Short tests, one look.</b> One full week (the usual minimum, so weekdays and weekends both count) lets more ideas through in
the same time. Checking every week without correcting the threshold raises false winners from {fw_corrected:.2f} to
{fw_uncorrected:.2f} per run.</li>
<li><b>Ship every winner.</b> Winners touch different steps, so they stack.</li>
<li><b>Traffic is the risk dial.</b> 100% of new users finds more winners but exposes {expo_full:.1f} times as many users to bad
changes; 10% is safe but slow and more often fooled by noise. 50% with automatic rollback is the chosen middle.</li>
</ul>
<p class="muted">These numbers come from the ideas of the published main run. With another run's ideas the size of each effect
differs, and the order of close setups, such as one-week against two-week tests, can change.</p>

<h2>Round by round (main run)</h2>
<p class="muted small">In each round, two test slots go to big moves first, then the best-scoring idea per funnel step, and two tests
never edit the same screen, so a high score can still be "not picked". The A/B table lists the tests decided that round, including
re-tests carried in from the round before; a re-test row shows its fresh week.</p>
{''.join(round_html)}

<h2>Did it improve itself? {badge('sim')}</h2>
<p>The fair test is a control run: the same loop, same weeks, same simulator, but with learning switched off (no lessons, no
re-weighting, no feedback on blocked ideas or measured results). Learning was run two ways: from raw measured results, and from
denoised results (below). Each row shares a random seed across the three versions. The cell is the share of new users finishing
onboarding at the end; every run starts at {pct(finish_rate(start))}.</p>
<h3>8 weeks on 50% of new users</h3>
{batch_table(short)}
<p>{verdict(short)}</p>
<h3>20 weeks on all new users</h3>
<p class="muted small">More users per test makes each result less noisy, and 20 weekly rounds give the learning step about
{long_['learn']['finished']:.0f} finished tests per run, close to the 100 at which the loop's own history starts to count for more than the prior.</p>
{batch_table(long_)}
<p>{verdict(long_)}</p>
<h3>How much could a better scorer add?</h3>
<p>To tell a weak learning method from a simulator with little to learn, the same rounds were replayed offline with four ways of
ordering the ideas that passed the safeguards in each saved learning run: a random order, the model's scores from that run, a scorer
that knows the average effect of each kind of change on each step (what learning from past tests is meant to find), and one that
knows each idea's true effect, luck included. Tests, shipping and the simulator are as in the loop, but without re-tests, the hourly
check, the shared-screen rule or the harm budget, so the levels differ from the tables above; compare the rows with each other.
Differences are against the model's scores, paired by seed, with 8 seeds and {scorer['settings']['runs_per_seed']['short']} (8 weeks)
or {scorer['settings']['runs_per_seed']['long']} (20 weeks) simulated runs per seed; <code>runs/scorer_study.json</code>.</p>
<div class="card"><table><thead><tr><th scope="col">Ideas ordered by</th><th scope="col">8 weeks on 50% of new users</th>
<th scope="col">20 weeks on all new users</th></tr></thead><tbody>{scorer_rows}</tbody></table></div>
<p>{scorer_story}{" The model's scores did no better than a random order." if model_vs_random else ""}</p>
<p>Three limits. The model's scores were given on the saved run's own path (its funnel, history and lessons) and are replayed on
other paths here. With about {ideas_per_round:.0f} ideas a round that pass the safeguards, up to {CONFIG['tests_per_round']} tests and one per step, the rules leave a scorer little choice beyond
which idea runs within each step, which also limits what any scorer can add. And the ideas themselves were proposed with learning on,
so any effect of learning on what gets proposed is not measured here. The simulator therefore cannot show whether a model can judge an
individual idea; real tests can. In a real deployment the loop would record every predicted effect and, after a few dozen tests,
check whether its predictions beat a random order.</p>
<h3>Denoising the learning signal</h3>
<p>A one-week test on a few thousand users measures the true effect plus a lot of luck, and the winners are the ones that got lucky
(the winner's curse). Learning straight from those numbers teaches the loop the luck.{raw_caveat} Four published ideas are applied before anything
is learned:</p>
<ul>
<li><b>Shrink every measured effect toward zero</b> by how noisy it is: corrected = τ² / (τ² + se²) × measured, where τ² is the spread
of true effects around zero estimated from all tests so far (empirical Bayes, as in Deng et al., KDD 2021). The prior counts for more
than our own history until about {TRUST_AFTER} tests, because the paper warns that 50 to 100 past experiments are needed for a stable estimate.</li>
<li><b>Weight results by reliability</b> when averaging by kind of change, so noisy tests count for less (the reweighting idea in Wang
et al., WSDM 2021, for noisy implicit feedback).</li>
<li><b>Re-test noisy winners</b>: when shrinkage keeps less than half of a winner's measured effect, it runs one more week on fresh
users while the next round starts. It ships if both weeks together, shrunk toward zero, are still clearly above zero and the fresh week
points the same way; the loop learns from the fresh week alone, so choosing the winner and estimating its effect use different data.
This is a shipping rule, so all three versions use it. Across all {rt_all} re-tests in both batches, {rt_held} held up and
{rt_dropped} were dropped, of which {rt_dropped_good} were actually good changes. {retest_story}</li>
<li><b>Require repeated evidence</b>: a kind of change counts as a pattern only after two tests agree, and the model is asked to call a
kind helpful only if a test of that kind actually won. This follows recent work on proactive assistants that learn a user's habits from repeated signals rather
than single events (Shao et al., 2026).</li>
</ul>
<h3>Rubric weights in the main run {badge('model')}</h3>
<div class="card">{weights_svg(weights_series)}</div>
<p>After each round, every weight moves toward the sub-scores that went with real gains; in this run {weights_story}</p>

<h2>Running it on Amplitude for real</h2>
<p><code>AmplitudeExperiments</code> in <code>rsi/experiments.py</code> has the same methods as the simulator:</p>
<ul>
<li><b>Create</b>: <code>POST experiment.amplitude.com/api/1/experiments</code> with control and treatment at 1:1, the change's config as
the treatment payload, and a unique key per test.</li>
<li><b>Traffic and start</b>: <code>PATCH …/experiments/{{id}}</code> with <code>rolloutPercentage</code>, then <code>enabled: true</code>.</li>
<li><b>Results</b>: the onboarding funnel per group from the Dashboard REST API, split by the <code>[Experiment] &lt;key&gt;</code> user
property; a re-test reads a separate date range of newly arrived users.</li>
<li><b>Ship</b>: the treatment gets all traffic.</li>
</ul>
<p>What the app needs first: at first launch, fetch the user's variant from Amplitude Experiment and build onboarding from that config.
The keys stay in the service that runs the loop; the model never sees them. In this demo the loop advances the simulator one hour at a
time; with Amplitude, an hourly job would read each test's funnel and switch off any test the check flags, which needs the hourly
Dashboard REST API rather than the daily reads in this code. This part has not been run, so the calls, including the variant-weight
change used to ship, should be checked against the current API first.</p>

<h2>Data handling</h2>
<ul>
<li>Funnel: one week of the real funnel with generic event names; only rates and times between steps are published, no user counts.
Simulated traffic uses an illustrative {CONFIG['weekly_new_users']:,} new users a week.</li>
<li>Support mail: addresses, links, numbers and long IDs were stripped on the mail server; the stripped text was sent to the Gemini API,
which rewrote every issue in its own words; a second model pass and a pattern check drop any line that still looks personal. The issues
were then grouped by hand into themes, and anything raised by only one person was folded into a broader theme. No raw mail and no
single-person issue is in this repository.</li>
<li>Traffic shape: eight weeks of daily onboarding starts and same-day finish rates, published only as indexes (each day divided by
the eight-week average), with no user counts. The daily starts were counted two ways, daily unique users and daily cohort sizes, and
matched on all {st_set['start_days']} days.</li>
<li>Every model prompt and answer is saved in each run folder's <code>cache/</code>, so every run replays exactly without an API key.</li>
</ul>

<h2>Sources</h2><ul class="small">{src_html}</ul>
</main></body></html>"""
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
