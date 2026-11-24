"""Turn one week of support emails into publishable, anonymous themes.

Input: a JSON list of {"subject", "body"} that already had emails, links,
numbers and long IDs removed at the source. It must live outside this repo.

Output: a list of short paraphrased issues with their onboarding step, written
outside the repo. No customer sentence is copied, and a second model pass
rejects any line that still looks personal. The issues are then grouped by
hand into the themes in data/support_week0.json, folding any problem raised by
only one person into a broader theme.

The mail is sent to the Gemini API for this step; use a paid API tier, whose
prompts are not used for training.

Usage:
  python3 prepare/anonymize_support.py mails.json cache_dir issues_out.json   (all outside the repo)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rsi.llm import ask_json  # noqa: E402

STEPS = ["story", "choose_path", "sign_in", "adoption_or_generation", "waiting_for_pet",
         "home_first_view", "after_onboarding", "not_about_the_app"]

PROMPT = """You read support emails for a desktop pet app. Onboarding steps, in order:
story (intro story screens), choose_path (adopt a pet or make your own), sign_in,
adoption_or_generation (pick a friend, adoption certificate, or uploading photos to generate a pet),
waiting_for_pet (waiting while the custom pet is generated), home_first_view (first look at the home screen).
Use after_onboarding for problems that happen later, and not_about_the_app for spam, sales, or unrelated mail.

For EACH email return one object:
- "step": one of {steps}
- "issue": the problem in your own words, at most 14 words, English, no names, no quotes,
  no email addresses, no order or account numbers, no country or device serials
- "kind": one of bug, confusion, waiting_too_long, payment, account, request, praise, other

Return JSON: {{"items": [...]}} with exactly {n} items, in the same order as the emails.

Emails:
{emails}
"""

CHECK = """Each line below must be safe to publish: no person name, no email, no phone,
no account or order ID, no quote of a customer sentence longer than 6 words.
Return JSON {{"unsafe": [indexes of lines that break any rule]}}.

{lines}
"""

PII = re.compile(r"@|https?://|\d{5,}|\[email\]|\[number\]|\[id\]|\[link\]")


def main(src: str, cache_dir: str, dest_path: str) -> None:
    mails = json.loads(Path(src).read_text())
    mails = [m for m in mails if (m.get("subject") or m.get("body"))]
    items = []
    for start in range(0, len(mails), 20):
        chunk = mails[start:start + 20]
        text = "\n\n".join(f"#{i}\nSubject: {m['subject']}\nBody: {m['body']}" for i, m in enumerate(chunk))
        answer = ask_json(PROMPT.format(steps=STEPS, n=len(chunk), emails=text), cache_dir=cache_dir)
        got = answer["items"]
        if len(got) != len(chunk):
            raise SystemExit(f"model returned {len(got)} items for {len(chunk)} emails")
        items.extend(got)

    for it in items:
        if it["step"] not in STEPS:
            it["step"] = "after_onboarding"
    lines = [it["issue"] for it in items]
    flagged = ask_json(CHECK.format(lines="\n".join(f"{i}: {line}" for i, line in enumerate(lines))),
                       cache_dir=cache_dir)
    flagged = flagged.get("unsafe", []) if isinstance(flagged, dict) else flagged
    unsafe = set()
    for x in flagged:
        try:
            unsafe.add(int(x))
        except (TypeError, ValueError):
            unsafe = set(range(len(lines)))      # an unreadable answer drops everything, never keeps it
            break
    unsafe |= {i for i, line in enumerate(lines) if PII.search(line)}
    kept = [it for i, it in enumerate(items) if i not in unsafe]

    out = {
        "week": "one week in November 2026",
        "source": "support mailbox, inbound messages only",
        "emails_read": len(mails),
        "dropped_as_possibly_personal": len(unsafe),
        "by_step": dict(Counter(it["step"] for it in items)),
        "by_kind": dict(Counter(it["kind"] for it in items)),
        "issues": [{"step": it["step"], "kind": it["kind"], "issue": it["issue"]}
                   for it in kept if it["step"] != "not_about_the_app"],
    }
    dest = Path(dest_path)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"wrote {dest}: {len(out['issues'])} issues, {len(unsafe)} dropped")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
