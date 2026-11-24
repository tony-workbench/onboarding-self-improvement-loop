"""Safeguards: big moves pass, every way to delete a step, leave onboarding or pressure users is blocked.
No network, no keys."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rsi import safeguards
from rsi.experiments import SimulatedExperiments
from rsi.safeguards import Blocked, DataGateway, ScopedExperiments, check_config

BASE = {"choose_path": 0.76, "sign_in": 0.73, "adoption": 0.61, "home": 0.81, "finish": 0.65}
GOOD = {"waiting": {"show_progress": True, "show_time_estimate": True,
                    "body": "We are building your pet. You can keep using your desktop."}}
ORDER = ["story", "choose_path", "pick_friend", "upload_photos", "adoption_certificate", "waiting",
         "sign_in", "home_intro"]
NEW = [*ORDER[:-1], "new_more", "home_intro"]


def change(config, title="t"):
    return {"title": title, "target_step": "home", "type": "wait_info", "change": "x", "config": config}


def block_reason(cfg) -> str:
    try:
        check_config(cfg)
    except Blocked as exc:
        return str(exc)
    return ""


class AuditToTemp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(safeguards, "AUDIT", Path(tmp.name) / "audit.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)


class BigMovesPass(unittest.TestCase):
    def test_allowed(self):
        allowed = {
            "plain copy and info": GOOD,
            "sign in moved after adoption": {"_order": ORDER},
            "new screen placed": {"_order": [*ORDER[:6], "new_desk_tour", *ORDER[6:]],
                                  "new_desk_tour": {"headline": "Meet your desktop pet", "layout": "checklist"}},
            "desktop tour after the home intro": {"_order": [*ORDER, "new_desktop_tour"],
                                                  "new_desktop_tour": {"headline": "Your pet lives on your desktop"}},
            "new layout": {"pick_friend": {"layout": "split"}},
            "redesigned screen": {"pick_friend": {"layout": "carousel", "components": [
                {"type": "animation", "asset": "asset:pets/idle_wave"},
                {"type": "choice_cards", "label": "Pick one", "action": "choose"},
                {"type": "button", "label": "This one", "action": "choose"}]}},
            "whole new sub-flow": {
                "_order": ["story", "new_meet", "new_name", "choose_path", "pick_friend", "upload_photos",
                           "adoption_certificate", "waiting", "new_tour", "sign_in", "home_intro"],
                "new_meet": {"components": [{"type": "mascot", "asset": "asset:pets/hello"}]},
                "new_name": {"headline": "Name your friend",
                             "components": [{"type": "name_input", "label": "Your pet's name"}]},
                "new_tour": {"layout": "checklist", "body": "Three things your pet can do on your desktop."}},
            "stamp replaced by a better one": {"adoption_certificate": {"replace": {"official_stamp": [
                {"type": "animation", "role": "official_stamp", "asset": "asset:stamp/paw_seal"}]}}},
            "pet picker rebuilt": {"pick_friend": {"replace": {"pet_choices": [
                {"type": "choice_cards", "role": "pet_choices", "label": "Who will you take home?",
                 "action": "choose"}]}}},
            "path choice rebuilt": {"choose_path": {"replace": {"path_options": [
                {"type": "choice_cards", "role": "path_options", "label": "Adopt a friend", "action": "choose"},
                {"type": "choice_cards", "role": "path_options", "label": "Make your own", "action": "choose"}]}}},
            "real wait timer": {"waiting": {"components": [{"type": "timer", "text": "About 4 min left"}]}},
            "pet gallery of picture cards": {"pick_friend": {"replace": {"pet_choices": [
                {"type": "choice_cards", "role": "pet_choices", "asset": "asset:pets/gallery_cat", "action": "choose"}]}}},
            "sign-in rebuilt": {"sign_in": {"replace": {"sign_in_options": [
                {"type": "button", "role": "sign_in_options", "label": "Continue with Apple", "action": "sign_in"}]}}},
            "wait status rebuilt": {"waiting": {"replace": {"wait_status": [
                {"type": "progress", "role": "wait_status", "text": "Your friend is being drawn right now"}]}}},
        }
        for name, cfg in allowed.items():
            with self.subTest(name):
                self.assertEqual(block_reason(cfg), "")


class ScopeBlocks(unittest.TestCase):
    """Each case names the reason it must be blocked for, so one rule cannot hide a broken one."""

    def check(self, cases):
        for name, (cfg, reason) in cases.items():
            with self.subTest(name):
                self.assertRegex(block_reason(cfg), reason)

    def test_structure(self):
        self.check({
            "existing screens reordered": ({"_order": ["choose_path", "story", "pick_friend", "upload_photos",
                                                       "adoption_certificate", "waiting", "sign_in", "home_intro"]},
                                           "keep their order"),
            "sign in before the choice": ({"_order": ["story", "sign_in", "choose_path", *ORDER[2:6], "home_intro"]},
                                          "sign_in"),
            "four new screens in a row": ({"_order": [*ORDER[:-1], "new_a", "new_b", "new_c", "new_d", "home_intro"],
                                           **{f"new_{x}": {"headline": "Hello there"} for x in "abcd"}}, "in a row"),
            "button past sign-in": ({"sign_in": {"components": [{"type": "button", "label": "Let's go",
                                                                 "action": "next"}]}}, "lead past"),
            "image past sign-in": ({"sign_in": {"components": [{"type": "image", "asset": "asset:x",
                                                                "action": "next"}]}}, "lead past"),
            "choice card that goes back with another label": ({"story": {"components": [
                {"type": "choice_cards", "label": "Continue", "action": "back"}]}}, "back control"),
            "upgrade screen": ({"_order": [*ORDER, "new_upgrade"], "new_upgrade": {"headline": "Hello"}}, "not part of"),
            "sign-up screen": ({"_order": [*ORDER, "new_sign_up"], "new_sign_up": {"headline": "Hello"}}, "not part of"),
            "asset that sells": ({"story": {"components": [{"type": "image", "asset": "asset:paywall/price_50_off"}]}},
                                 "asset"),
            "long fake wait": ({"waiting": {"components": [{"type": "timer", "text": "About 99 min left"}]}}, "timer"),
            "screen outside onboarding": ({"settings": {"headline": "Hi"}}, "not part of onboarding"),
            "paywall screen": ({"paywall": {"headline": "Hi"}}, "not part of onboarding"),
            "new screen that looks like payment": (
                {"_order": [*ORDER, "new_paywall"], "new_paywall": {"headline": "Hello"}}, "not part of onboarding"),
            "new screen that looks like settings": (
                {"_order": [*ORDER, "new_mysettings"], "new_mysettings": {"headline": "Hello"}}, "not part of"),
            "unknown field": ({"waiting": {"price": 0}}, "not adjustable"),
            "skipping a step": ({"sign_in": {"skippable": True}}, "not adjustable"),
            "turning a screen off": ({"adoption_certificate": {"enabled": False}}, "not adjustable"),
            "order drops a step": ({"_order": [x for x in ORDER if x != "sign_in"]}, "leaves out"),
            "order repeats a step": ({"_order": [*ORDER, "story"]}, "twice"),
            "home before an existing screen": ({"_order": [*ORDER[:-2], "home_intro", "sign_in"]}, "home_intro"),
            "branch before its choice": ({"_order": ["story", "pick_friend", "choose_path", "upload_photos",
                                                     "adoption_certificate", "waiting", "sign_in", "home_intro"]},
                                         "keep their order"),
            "waiting before photos": ({"_order": ["story", "choose_path", "pick_friend", "waiting", "upload_photos",
                                                  "adoption_certificate", "sign_in", "home_intro"]}, "keep their order"),
            "new screen not placed": ({"new_tip": {"headline": "Hi"}}, "_order"),
            "new screen defined but left out": ({"_order": ORDER, "new_ghost": {"headline": "Hi"}}, "not placed"),
            "too many new screens": ({"_order": ORDER[:-1] + [f"new_{i}" for i in range(9)] + ["home_intro"],
                                      **{f"new_{i}": {"headline": "x"} for i in range(9)}}, "at most"),
            "layout that hides": ({"sign_in": {"layout": "hidden"}}, "layout"),
            "layout that skips": ({"sign_in": {"layout": "skip"}}, "layout"),
            "style that hides": ({"story": {"components": [{"type": "text", "text": "Hi", "style": "display_none"}]}},
                                 "style"),
            "removing a design": ({"adoption_certificate": {"remove_stamp": True}}, "not adjustable"),
            "unknown component": ({"story": {"components": [{"type": "iframe", "text": "x"}]}}, "type"),
            "button leaving onboarding": ({"story": {"components": [
                {"type": "button", "label": "Go", "action": "open_url"}]}}, "inside onboarding"),
            "outside asset": ({"story": {"components": [{"type": "image", "asset": "https://example.com/a.png"}]}},
                              "asset"),
            "too many components": ({"story": {"components": [{"type": "text", "text": "Hi"}] * 13}}, "more than"),
            "huge config": ({"story": {"body": "a"}, **{f"new_{i}": {"body": "b" * 230} for i in range(30)}},
                            "longer than"),
            "empty": ({}, "non-empty"),
            "not an object": ("show progress", "non-empty"),
        })

    def test_jobs(self):
        self.check({
            "welcome with no words": ({"home_intro": {"replace": {"home_welcome": [
                {"type": "text", "role": "home_welcome"}]}}}, "does not do the job"),
            "story image that is not a story asset": ({"story": {"replace": {"intro_story": [
                {"type": "image", "role": "intro_story", "asset": "asset:blank"}]}}}, "does not do the job"),
            "certificate placeholder asset": ({"adoption_certificate": {"replace": {"certificate": [
                {"type": "image", "role": "certificate", "asset": "asset:none"}]}}}, "does not do the job"),
            "pet picker with no label": ({"pick_friend": {"replace": {"pet_choices": [
                {"type": "choice_cards", "role": "pet_choices", "action": "choose"}]}}}, "does not do the job"),
            "bare progress bar": ({"waiting": {"replace": {"wait_status": [
                {"type": "progress", "role": "wait_status"}]}}}, "does not do the job"),
            "two identical path buttons": ({"choose_path": {"replace": {"path_options": [
                {"type": "button", "role": "path_options", "label": "OK", "action": "choose"},
                {"type": "button", "role": "path_options", "label": "OK", "action": "choose"}]}}}, "does not do the job"),
            "sign-in button that does not say so": ({"sign_in": {"replace": {"sign_in_options": [
                {"type": "button", "role": "sign_in_options", "label": "Hi", "action": "sign_in"}]}}},
                "does not do the job"),
            "replacing a part that does not exist": ({"adoption_certificate": {"replace": {"paywall": [
                {"type": "text", "role": "paywall", "text": "x"}]}}}, "no part called"),
            "replacing with nothing": ({"adoption_certificate": {"replace": {"official_stamp": []}}}, "needs"),
            "replacement for a different job": ({"adoption_certificate": {"replace": {"official_stamp": [
                {"type": "image", "role": "certificate", "asset": "asset:x"}]}}}, "must declare"),
            "stamp replaced by a sound": ({"adoption_certificate": {"replace": {"official_stamp": [
                {"type": "sound", "role": "official_stamp", "asset": "asset:stamp/x"}]}}}, "cannot do"),
            "certificate replaced by blank text": ({"adoption_certificate": {"replace": {"certificate": [
                {"type": "text", "role": "certificate", "text": " "}]}}}, "does not do the job"),
            "stamp replaced by a sound-free image with the wrong asset": ({"adoption_certificate": {"replace": {
                "official_stamp": [{"type": "image", "role": "official_stamp", "asset": "asset:x"}]}}},
                "does not do the job"),
            "sign-in replaced by empty text": ({"sign_in": {"replace": {"sign_in_options": [
                {"type": "text", "role": "sign_in_options", "text": ""}]}}}, "does not do the job"),
            "one path option only": ({"choose_path": {"replace": {"path_options": [
                {"type": "choice_cards", "role": "path_options", "label": "Adopt", "action": "choose"}]}}},
                "does not do the job"),
            "replacement list too long": ({"pick_friend": {"replace": {"pet_choices": [
                {"type": "choice_cards", "role": "pet_choices", "label": "Pick", "action": "choose"}] * 50}}},
                "at most 6"),
        })

    def test_text(self):
        def body(text):
            return {"story": {"body": text}}
        self.check({
            "price": (body("Second pet only $1.99"), "price|money|characters"),
            "full-width dollar": (body("Second pet only ＄1.99"), "price|money|characters"),
            "price in words": (body("It costs just two dollars"), "price|money"),
            "currency code": (body("Only 1.99 USD"), "price|money"),
            "half off": (body("Half off your second pet"), "price|money"),
            "percent off": (body("50 percent off today"), "price|money"),
            "on sale": (body("Pets are on sale"), "price|money"),
            "money back": (body("Get your money back"), "price|money"),
            "free pet": (body("Get a free pet now"), "price|money"),
            "subscription": (body("Start your subscription"), "price|money"),
            "complimentary": (body("Your first friend is complimentary"), "price|money"),
            "on the house": (body("This one's on the house"), "price|money"),
            "price alone": (body("Only 1.99"), "price|money"),
            "two for one": (body("Two for one this week"), "price|money"),
            "membership": (body("Become a member, cancel anytime"), "price|money"),
            "spaced free": (body("F R E E pet"), "price|money"),
            "finish later": (body("You can finish this later"), "skipping"),
            "jump ahead": (body("Jump ahead to the fun part"), "skipping"),
            "optional sign-in": ({"upload_photos": {"body": "Signing in is optional"}}, "skipping"),
            "act fast": (body("Act fast"), "urgency"),
            "while supplies last": (body("While supplies last"), "urgency"),
            "others viewing": (body("3 people are viewing this pet"), "urgency"),
            "guilt": (body("Your pet will cry"), "shames"),
            "handle": (body("What's your handle?"), "personal"),
            "where you live": (body("Where do you live?"), "personal"),
            "spelled email": (body("e m a i l us your info"), "personal"),
            "age ranges": ({"_order": NEW, "new_more": {"components": [
                {"type": "choice_cards", "label": "18 to 24", "action": "choose"}]}}, "personal"),
            "spelled link": (body("Visit evil dot com"), "link"),
            "dotted link": (body("Go to e.v.i.l.com"), "link"),
            "spaced link": (body("evil . com"), "link"),
            "ip address": (body("Go to 192.168.1.1/pets"), "link"),
            "mailto": (body("mailto:x"), "link"),
            "html entity": (body("&lt;b&gt;hi"), "link|markup"),
            "skip": ({"sign_in": {"hint": "You can skip this"}}, "skipping"),
            "skip with a digit": ({"sign_in": {"hint": "You can sk1p this"}}, "skipping|disguise"),
            "spaced skip": ({"sign_in": {"hint": "s k i p"}}, "skipping"),
            "zero-width skip": ({"sign_in": {"hint": "sk​ip"}}, "characters"),
            "cyrillic skip": ({"sign_in": {"hint": "skiр"}}, "characters"),
            "do this later": ({"sign_in": {"hint": "You can do this later"}}, "skipping"),
            "guest button": ({"sign_in": {"components": [
                {"type": "button", "label": "Continue as guest", "action": "next"}]}}, "skipping|lead past"),
            "full-width link": (body("ｈｔｔｐｓ：／／evil.example"), "disguise|link"),
            "bare domain": (body("Visit evil.example.com"), "link"),
            "markdown link": (body("[more](evil.example.com)"), "characters"),
            "markup": (body("<script>x</script>"), "characters"),
            "full-width markup": (body("＜script＞"), "characters"),
            "urgency": (body("Hurry, only 2 left today"), "urgency"),
            "urgency reworded": (body("Pets are going quickly - just 2 to go"), "urgency"),
            "today only": (body("Today only: adopt before midnight"), "urgency"),
            "few left": (body("Only a few left"), "urgency"),
            "clock countdown in text": ({"story": {"components": [{"type": "text", "text": "04:59"}]}}, "clock"),
            "fake countdown": ({"pick_friend": {"components": [{"type": "timer", "text": "Offer ends in 5"}]}},
                               "timer|urgency|money"),
            "pressure on the waiting timer": ({"waiting": {"components": [
                {"type": "timer", "text": "Adopt within 4 min or lose your pet"}]}}, "urgency|timer"),
            "confirmshaming": ({"sign_in": {"components": [
                {"type": "button", "label": "No thanks, I hate pets", "action": "back"}]}}, "shames|back control"),
            "confirmshaming reworded": (body("Nah, my pet can stay sad"), "shames"),
            "back button with a guilt label": ({"story": {"components": [
                {"type": "button", "label": "Leave your pet", "action": "back"}]}}, "back control"),
            "asking for an email": ({"_order": NEW, "new_more": {"components": [
                {"type": "name_input", "label": "Your email"}]}}, "personal"),
            "spaced email": ({"_order": NEW, "new_more": {"components": [
                {"type": "name_input", "label": "Your e mail"}]}}, "personal"),
            "age question": ({"pick_friend": {"components": [
                {"type": "choice_cards", "label": "How old are you?", "action": "choose"}]}}, "personal"),
            "full name input": ({"_order": NEW, "new_more": {"components": [
                {"type": "name_input", "label": "Full name"}]}}, "personal|pet's name"),
            "email request beside a pet-name field": ({"_order": NEW, "new_more": {
                "body": "Type your e-mail below", "components": [{"type": "name_input", "label": "Pet name"}]}},
                "personal"),
            "login look-alike": ({"_order": [*ORDER[:-1], "new_login", "home_intro"], "new_login": {
                "headline": "Log in to continue", "components": [{"type": "name_input", "label": "Username"}]}},
                "not part of|personal"),
            "card field": ({"_order": NEW, "new_more": {"components": [
                {"type": "name_input", "label": "Card number"}]}}, "personal|disguise|pet's name"),
        })


class OrdinaryCopyPasses(unittest.TestCase):
    """Normal onboarding copy must not be blocked by the word checks."""

    TEXTS = ["Meet your new best friend!", "Feel free to look around before you choose.", "No rush, take your time.",
             "You're in charge of your pet's name.", "Hold your phone steady while you take the photo.",
             "I don't have photos yet", "I have photos of my pet", "Check out your new companion!",
             "Pay attention to the little details in each photo.", "Only one step to go!",
             "Sign in to keep your pet safe across devices.", "Your pet is almost ready.",
             "100% of the photos stay on your device.", "We'll let you know when Biscuit is ready.",
             "Pick the pet that feels like yours.", "Every story has a happy ending.",
             "Add three clear photos of your pet's face.", "Your adoption certificate is official!",
             "Choose a cat, a dog, or a bunny.", "Zoe and Chlo\u00e9 can't wait to meet you.",
             "Tip: natural light works best.", "Great choice! \U0001f436", "Welcome home, little one.",
             "Photos from any age of your pet work.", "A walk in the country, a nap in the sun.",
             "Your pet will learn tricks over time.", "Your friend is being drawn right now.",
             "Big deal: you just adopted a friend!", "Next", "Continue with Apple", "Not sure? Try the quiz.",
             "Ski photos work too!", "Wait for it. Me too!", "Hello. Come back soon."]

    def test_ordinary_copy(self):
        for text in self.TEXTS:
            with self.subTest(text):
                self.assertEqual(block_reason({"story": {"body": text}}), "")


class TargetStep(unittest.TestCase):
    def test_change_stays_on_its_step(self):
        cfg = {"sign_in": {"hint": "Sign in to keep your pet"}, "waiting": {"show_progress": True}}
        with self.assertRaisesRegex(Blocked, "may only edit"):
            check_config(cfg, "sign_in")
        check_config({"sign_in": {"hint": "Sign in to keep your pet"}}, "sign_in")


class ExperimentScope(AuditToTemp):
    def setUp(self):
        super().setUp()
        self.sim = SimulatedExperiments(BASE, 6000, 1)
        self.exp = ScopedExperiments(self.sim, max_share=0.5, max_tests=2)

    def test_traffic_cap(self):
        self.exp.create(change(GOOD, "at cap"), share=0.5)
        for bad in (0.6, 0, -5, float("nan"), float("inf"), "0.1"):
            with self.subTest(bad), self.assertRaises(Blocked):
                self.exp.create(change(GOOD, "over"), share=bad)

    def test_share_reaches_the_backend(self):
        tid = self.exp.create(change(GOOD), share=0.3)
        self.assertEqual(self.sim.tests[tid]["share"], 0.3)

    def test_test_limit_counts_started_tests(self):
        tids = [self.exp.create(change(GOOD, f"a{i}"), share=0.5) for i in range(2)]
        for tid in tids:
            self.exp.start(tid)
        with self.assertRaises(Blocked):
            self.exp.create(change(GOOD, "a3"), share=0.5)
        self.exp.stop(tids[0])
        self.exp.start(self.exp.create(change(GOOD, "a3"), share=0.5))

    def test_start_also_checks_the_limit(self):
        exp = ScopedExperiments(SimulatedExperiments(BASE, 6000, 1), max_share=0.5, max_tests=1)
        a = exp.create(change(GOOD, "a"), share=0.5)
        b = exp.create(change(GOOD, "b"), share=0.5)
        exp.start(a)
        with self.assertRaises(Blocked):
            exp.start(b)

    def test_bad_config_or_text_never_reaches_backend(self):
        for ch in (change({"settings": {"headline": "x"}}),
                   {**change(GOOD), "title": "Second pet evil.example.com"},
                   {**change(GOOD), "change": "<script>"}):
            with self.subTest(ch["title"]), self.assertRaises(Blocked):
                self.exp.create(ch, share=0.1)
        self.assertEqual(self.sim.tests, {})

    def test_lifecycle(self):
        tid = self.exp.create(change(GOOD), share=0.5)
        with self.assertRaises(Blocked):
            self.exp.ship(tid)                       # never ran
        self.exp.start(tid)
        self.exp.stop(tid, "won")
        with self.assertRaises(Blocked):
            self.exp.start(tid)                      # no restart after stop
        self.exp.ship(tid)

    def test_only_a_winner_can_ship(self):
        for why in ("stopped early: sign_in worse", "rolled back: guardrail", "lost: worse", "decided"):
            tid = self.exp.create(change(GOOD, why[:10]), share=0.5)
            self.exp.start(tid)
            self.exp.stop(tid, why)
            with self.subTest(why), self.assertRaisesRegex(Blocked, "stopped as a winner"):
                self.exp.ship(tid)

    def test_cannot_touch_other_tests(self):
        for action in ("start", "stop", "read", "ship", "mark"):
            with self.subTest(action), self.assertRaises(Blocked):
                getattr(self.exp, action)("someone-elses-flag")

    def test_calls_off_the_allow_list(self):
        for name in ("delete", "update_flag", "set_rollout", "baseline", "mine", "backend"):
            with self.subTest(name), self.assertRaises(Blocked):
                getattr(self.exp, name)

    def test_every_call_is_logged(self):
        tid = self.exp.create(change(GOOD), share=0.5)
        self.exp.start(tid)
        with self.assertRaises(Blocked):
            self.exp.create(change(GOOD), share=0.9)
        entries = [json.loads(x) for x in safeguards.AUDIT.read_text().splitlines()]
        self.assertEqual([(e["action"], e["allowed"]) for e in entries],
                         [("create", True), ("start", True), ("create", False)])
        self.assertEqual(entries[0]["detail"]["test"], tid)


class DataScope(AuditToTemp):
    def test_onboarding_events_only(self):
        with self.assertRaises(Blocked):
            DataGateway().funnel(["purchase_completed"])

    def test_requested_events_filter_the_answer(self):
        steps = DataGateway().funnel(["sign_in_started"])["steps"]
        self.assertEqual([s["event"] for s in steps], ["sign_in_started"])

    def test_allowed_events_cannot_be_changed(self):
        with self.assertRaises(AttributeError):
            DataGateway.ALLOWED_EVENTS.add("purchase_completed")

    def test_no_user_level_or_raw_data(self):
        for name in ("users", "user_events", "raw_emails", "export", "query", "root"):
            with self.subTest(name), self.assertRaises(Blocked):
                getattr(DataGateway(), name)

    def test_published_data_is_aggregate_only(self):
        funnel = DataGateway().funnel()
        for step in funnel["steps"]:
            self.assertEqual(set(step), {"step", "event", "conversion_from_previous",
                                         "median_seconds_from_previous", "mean_seconds_from_previous"})
            self.assertLessEqual(step["conversion_from_previous"], 1)
        support = DataGateway().support_themes()
        self.assertTrue(all(set(t) == {"step", "kind", "theme", "count"} for t in support["themes"]))
        self.assertTrue(all(t["count"] >= 2 for t in support["themes"]), "single-person issues must be folded in")
        self.assertNotIn("@", json.dumps(support) + json.dumps(funnel))
        self.assertEqual(sum(t["count"] for t in support["themes"]) + support["by_step"]["not_about_the_app"],
                         support["emails_read"])


if __name__ == "__main__":
    unittest.main()
