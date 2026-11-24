"""Safeguards enforced in code, outside the model.

The model may make big changes inside onboarding. It may not delete a step or a
job a screen does, reach outside onboarding, touch price, link out, or use an
unfair design. It never holds keys and never calls a service directly: every
proposal passes check_config, every experiment call goes through
ScopedExperiments, and every data read goes through DataGateway. Anything
outside the allow-lists raises Blocked, and every call is written to the audit log.

Design follows OWASP LLM06 (Excessive Agency): minimal tools, minimal
permissions, authorization in code rather than in the model, audit logging,
and automatic rollback on guardrail metrics. Text is checked against a
character allow-list after Unicode normalisation, so look-alike characters,
full-width forms and invisible characters cannot hide a blocked word.
"""
import json
import math
import os
import re
import itertools
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / os.environ.get("RSI_RUNS_DIR", "runs") / "audit.jsonl"


class Blocked(Exception):
    """An action outside the allowed scope."""


_SEQ = itertools.count(1)


def audit(action: str, allowed: bool, detail) -> None:
    """Append one action to the run's log. Entries are numbered, not timestamped, so a replay writes the same log."""
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a") as f:
        f.write(json.dumps({"n": next(_SEQ), "action": action, "allowed": allowed,
                            "detail": detail}, ensure_ascii=False) + "\n")


# 1. Text ----------------------------------------------------------------------
#
# Code checks what code can check reliably: characters, links, markup, and a short list of phrases
# that are never fine in onboarding copy (prices, skipping, pressure, shaming, personal-data
# questions). Subtler wording is judged by a separate fairness review (see rsi/loop.py), because
# broad word lists both miss rewordings and block ordinary copy such as "feel free to look around".

PUNCT = set(" .,!?'\"-:;()&/+%")
QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        "…": "..."})
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a"})


def _allowed_char(ch: str) -> bool:
    if ch.isascii():
        return ch.isalnum() or ch in PUNCT
    cat = unicodedata.category(ch)
    if cat.startswith("L"):
        return unicodedata.name(ch, "").startswith("LATIN")      # accented Latin letters, not look-alikes
    return cat == "So"                                             # emoji and pictographs


def _forms(where: str, value: str) -> tuple[str, str]:
    """Normalise text; return (words, words with digit look-alikes mapped)."""
    text = unicodedata.normalize("NFKC", value).translate(QUOTES)
    bad = sorted({ch for ch in text if not _allowed_char(ch)})
    if bad:
        raise Blocked(f"text in '{where}' has characters outside the allowed set: {bad!r}")
    low = unicodedata.normalize("NFKD", text.lower())
    low = "".join(ch for ch in low if not unicodedata.combining(ch))
    words = " " + re.sub(r"[^a-z0-9%./]+", " ", low).strip() + " "
    leet = " " + re.sub(r"[^a-z]+", " ", low.translate(LEET)).strip() + " "
    return words, leet


def _phrases(*items: str) -> re.Pattern:
    return re.compile(r"(?<![a-z])(" + "|".join(items) + r")(?![a-z])")


MONEY = _phrases(
    r"usd|eur|gbp|dollars?|bucks|cents|euros?|pounds? sterling|\d+ (euros?|pounds|yen)", r"\d+[.,]\d\d",
    r"\d+ ?% ?off|percent off|half off|on sale|two for one|2 for 1|buy one", r"free (trial|pet|pets|gift|item|items|treat|treats)",
    r"for free|free of charge|no charge|complimentary|gratis|on the house|on us|freebie",
    r"per month|/ ?month|monthly plan|subscription|subscribe|premium|upgrade to|unlock vip|vip pets|membership",
    r"discount|coupon|promo code|refund|money back|cheaper|bargain|donate|tip jar|card needed|price|pricing",
    r"save \d+|\d+ percent|cancel anytime|become a member|f[ ._-]r[ ._-]e[ ._-]e")
SKIPPING = _phrases(
    r"skip\w*", r"s[ ._-]k[ ._-]i[ ._-]p", r"bypass\w*", r"guest", r"without (signing|an account|account|logging)",
    r"(sign in|signing in|log in|logging in) is optional", r"no need to (sign|log) in", r"not now", r"maybe later",
    r"(do|finish|sign in|log in) (this |it |that )?later", r"jump ahead", r"go straight to",
    r"come back to (this|it) (later|whenever)", r"pass on this", r"fast forward")
URGENCY = _phrases(
    r"hurry|act now|act fast|last chance|limited time|today only|only today|while (supplies|stocks?) last",
    r"selling (fast|out)|almost gone|going (fast|quickly)|final hours|closing soon|expires?|expiring|countdown",
    r"\d+ (people|others|users) (are )?(viewing|looking)", r"only (\d+|a few|few) (left|remaining|to go)", r"few left",
    r"before (it is|it s|its) gone|don t miss|dont miss|now or never|lose your pet",
    r"won t last|others are adopting|before someone else")
SHAMING = _phrases(
    r"no thanks,? i|nah|nope|heartless|cruel|will cry|(leave|leaving) \w+ behind|abandon\w*|i hate",
    r"i don t care|i like being alone|lonely forever|my pet can stay sad")
PERSONAL = _phrases(
    r"e ?-?mail|e[ ._-]m[ ._-]a[ ._-]i[ ._-]l|contact (info|details)|your digits|your neighbou?rhood|which street|phone number|mobile number|password|passcode|card number|credit card|debit card|cvv|ssn",
    r"social security|bank (account|details)|date of birth|when were you born|how old are you|where do you live",
    r"where s home for you|what s your name|your (address|birthday|age|gender|school|workplace|instagram|socials|"
    r"handle|location|real name|full name|last name|surname)")
TLDS = r"net|org|io|co|app|me|ai|dev|info|xyz|shop|store|link|ly|gg|uk|us|de|cn|ru"
LINK = re.compile(
    r"(\.|\(\.\)|\[\.\]|\bdot\b)\s*c\s*o\s*m\b"                     # .com, (.)com, dot com, . c o m
    rf"|[a-z0-9]\.({TLDS})\b|\bdot\s+({TLDS})\b"                     # other domains, written or spelled out
    r"|\b\d{1,3}(\.\d{1,3}){3}\b"                                       # IP addresses
    r"|\b(https?|mailto|tel|ftp|file|javascript|data|sms)\s*:|\bwww\s*\."    # schemes
    r"|&#?\w+;|\bdotcom\b|\bh[ ._-]t[ ._-]t[ ._-]p", re.I)                                                  # HTML entities
CLOCK = re.compile(r"\d{1,2}:\d{2}")
AGE_RANGE = re.compile(r"^\s*\d{1,3}\s*(to|-|–)\s*\d{1,3}\s*\+?\s*$|^\s*\d{1,3}\s*\+\s*$")


def check_text(where: str, value: str, limit: int) -> None:
    if len(value) > limit:
        raise Blocked(f"text in '{where}' is longer than {limit}")
    words, leet = _forms(where, value)
    normal = unicodedata.normalize("NFKC", value)
    if LINK.search(normal) or LINK.search(words):
        raise Blocked(f"text in '{where}' contains a link, an address or markup")
    if CLOCK.search(normal):
        raise Blocked(f"text in '{where}' contains a clock-style countdown")
    for form in (words, leet):
        if MONEY.search(form):
            raise Blocked(f"text in '{where}' talks about price or money")
        if SKIPPING.search(form):
            raise Blocked(f"text in '{where}' suggests skipping a step")
        if URGENCY.search(form):
            raise Blocked(f"text in '{where}' creates false urgency or scarcity")
        if SHAMING.search(form):
            raise Blocked(f"text in '{where}' shames people who decline")
        if PERSONAL.search(form):
            raise Blocked(f"text in '{where}' asks for or mentions personal data")


PLAIN_CHARS = re.compile(r"^[\x20-\x7e]*$")


def check_plain(where: str, value: str, limit: int) -> None:
    """For titles and descriptions sent to the experiment platform: plain ASCII, no links or markup."""
    if not isinstance(value, str) or len(value) > limit:
        raise Blocked(f"'{where}' must be text up to {limit} characters")
    text = unicodedata.normalize("NFKC", value).translate(QUOTES)
    if not PLAIN_CHARS.match(text) or re.search(r"[<>`]", text) or LINK.search(text):
        raise Blocked(f"'{where}' has markup, a link or characters outside plain ASCII")


# 2. What a change may touch -----------------------------------------------------

SCREENS = ["story", "choose_path", "sign_in", "pick_friend", "upload_photos",
           "adoption_certificate", "waiting", "home_intro"]          # the current order
STEP_SCREENS = {"choose_path": {"story", "choose_path"}, "sign_in": {"sign_in"},
                "adoption": {"pick_friend", "upload_photos", "adoption_certificate"},
                "home": {"waiting"}, "finish": {"home_intro"}}     # the screens each funnel step covers
NEW_SCREEN = re.compile(r"^new_[a-z0-9_]{1,30}$")                    # screens the model adds
NEW_SCREEN_BANNED = ["pay", "bill", "checkout", "cart", "basket", "subscri", "premium", "wall", "setting", "account",
                     "login", "log_in", "signin", "sign_in", "signup", "sign_up", "register", "password", "card",
                     "shop", "store", "purchase", "price", "offer", "deal", "promo", "trial", "bank", "wallet",
                     "coin", "gem", "admin", "profile", "upgrade", "vip", "member", "unlock", "donate", "privacy",
                     "permission", "preference", "consent", "tip_jar", "gold"]
MAX_NEW_SCREENS = 8
MAX_NEW_IN_A_ROW = 3
MAX_COMPONENTS = 12
MAX_CONFIG_CHARS = 6000
MAX_WAIT_MINUTES = 30
LAYOUTS = {"default", "compact", "split", "full_bleed", "card", "checklist", "carousel", "stage", "grid", "list",
           "centered", "two_column", "story_scroll", "spotlight"}
STYLES = {"plain", "emphasis", "subtle", "large", "small", "playful", "calm", "highlight", "rounded"}
COMPONENT_TYPES = {"text", "image", "animation", "video", "button", "checklist", "progress", "timer",
                   "choice_cards", "name_input", "photo_picker", "tip_carousel", "mascot", "sound", "badge", "preview"}
COMPONENT_KEYS = {"type": 30, "role": 30, "text": 240, "label": 40, "asset": 60, "style": 30, "action": 20}
ACTIONS = {"next", "back", "choose", "play", "open_tip", "replay"}
ROLE_ONLY_ACTIONS = {"sign_in": "sign_in_options", "open_settings": "settings_entry"}
SIGN_IN_SCREEN_ACTIONS = {"sign_in", "back", "play", "open_tip", "replay", "open_settings"}   # no way past it
BACK_LABELS = {"back", "go back", "previous"}
PET_NAME = re.compile(r"^((your|give your|name your) )?(new )?(pet|friend|companion|buddy)('s)? name$|^(pet )?name$")
TIMER_TEXT = re.compile(r"^(about )?(\d{1,2}) (min|mins|minutes|sec|seconds) (left|to go)$")
FIELDS = {
    "headline": (str, 80), "body": (str, 240), "hint": (str, 160), "button_label": (str, 30),
    "layout": (str, None), "show_progress": (bool, None), "show_time_estimate": (bool, None),
    "notify_when_ready": (bool, None), "show_step_counter": (bool, None),
    "tip_delay_seconds": (int, 60), "components": (list, MAX_COMPONENTS), "replace": (dict, None),
}
ORDER_KEY = "_order"

# What each existing screen is for. Any part may be replaced by something better that does the same job:
# the replacement must use components that can do that job, with real content.
ROLES = {
    "story": ["intro_story"],
    "choose_path": ["path_options"],
    "sign_in": ["sign_in_options"],
    "pick_friend": ["pet_choices"],
    "upload_photos": ["photo_upload"],
    "adoption_certificate": ["certificate", "official_stamp"],
    "waiting": ["wait_status"],
    "home_intro": ["home_welcome"],
}
COMMON_ROLES = ["settings_entry"]                     # the Setting gear on every screen
# role: (allowed types, types that can do the job, how many needed, asset prefix required, words required)
ROLE_RULES = {
    "intro_story": ({"video", "animation", "image", "text", "mascot", "button"},
                    {"video", "animation", "image", "mascot"}, 1, "asset:story/", False),
    "path_options": ({"choice_cards", "button", "text", "image", "animation"}, {"choice_cards", "button"}, 2, None, True),
    "sign_in_options": ({"button", "choice_cards", "text", "image"}, {"button", "choice_cards"}, 1, None, True),
    "pet_choices": ({"choice_cards", "preview", "image", "animation", "text", "button"}, {"choice_cards"}, 1, None, True),
    "photo_upload": ({"photo_picker", "text", "image", "checklist", "button"}, {"photo_picker"}, 1, None, True),
    "certificate": ({"image", "animation", "preview", "text", "badge"}, {"image", "animation", "preview"}, 1,
                    "asset:certificate/", False),
    "official_stamp": ({"image", "animation", "badge"}, {"image", "animation", "badge"}, 1, "asset:stamp/", False),
    "wait_status": ({"progress", "timer", "animation", "text", "mascot", "preview", "tip_carousel"},
                    {"progress", "timer", "preview"}, 1, None, False),
    "home_welcome": ({"text", "animation", "mascot", "image", "button", "checklist"},
                     {"text", "animation", "mascot", "image"}, 1, None, True),
    "settings_entry": ({"button"}, {"button"}, 1, None, True),
}
ROLE_ACTIONS = {"path_options": "choose", "pet_choices": "choose", "sign_in_options": "sign_in",
                "settings_entry": "open_settings"}
ADOPT_WORDS = re.compile(r"\b(adopt\w*|pick|choose|friend|meet)\b", re.I)
CREATE_WORDS = re.compile(r"\b(make|create|own|photos?|design|build)\b", re.I)
SIGN_IN_WORDS = re.compile(r"\b(sign in|sign-in|log in|continue with|connect with)\b", re.I)
PICTURE_OK = {"pet_choices"}                          # a card showing the pet is as good as one naming it
ROLE_TEXT_NEEDED = {"wait_status"}                    # a bare progress bar does not say what is happening


def _words_in(comp) -> str:
    return " ".join(str(comp.get(k, "")) for k in ("text", "label")).strip()


def _meaningful(text: str) -> bool:
    return len(re.findall(r"[A-Za-z]", text)) >= 3 and any(len(w) >= 3 for w in re.findall(r"[A-Za-z]+", text))


def touched_screens(config: dict) -> set:
    """Existing screens a change edits, plus the order if it moves screens."""
    return {k for k in config if k in SCREENS} | ({ORDER_KEY} if ORDER_KEY in config else set())


def _check_component(screen, where, comp, role=None):
    if not isinstance(comp, dict) or comp.get("type") not in COMPONENT_TYPES:
        raise Blocked(f"'{where}' must have a type from {sorted(COMPONENT_TYPES)}")
    for key, value in comp.items():
        if key not in COMPONENT_KEYS:
            raise Blocked(f"'{where}.{key}' is not a component field")
        if type(value) is not str or len(value) > COMPONENT_KEYS[key]:
            raise Blocked(f"'{where}.{key}' must be text up to {COMPONENT_KEYS[key]} characters")
    kind = comp["type"]
    action = comp.get("action")
    if "style" in comp and comp["style"] not in STYLES:
        raise Blocked(f"'{where}.style' must be one of {sorted(STYLES)}")
    if action is not None:
        if action in ROLE_ONLY_ACTIONS:
            if role != ROLE_ONLY_ACTIONS[action]:
                raise Blocked(f"'{where}': action '{action}' belongs only to the {ROLE_ONLY_ACTIONS[action]} job")
        elif action not in ACTIONS:
            raise Blocked(f"'{where}.action' must stay inside onboarding: one of {sorted(ACTIONS)}")
        if screen == "sign_in" and action not in SIGN_IN_SCREEN_ACTIONS:
            raise Blocked(f"'{where}': nothing on the sign-in screen may lead past it without signing in")
        if action == "back" and comp.get("label", "").strip().lower() not in BACK_LABELS:
            raise Blocked(f"'{where}': a back control may only say {sorted(BACK_LABELS)}")
    if "asset" in comp:
        asset = comp["asset"]
        if not re.match(r"^asset:[a-z0-9_-]+(/[a-z0-9_-]+)*$", asset) \
                or any(term in asset for term in NEW_SCREEN_BANNED + ["sale", "off", "discount", "free"]):
            raise Blocked(f"'{where}.asset' must be a bundled onboarding asset id (asset:...)")
    for key in ("text", "label"):
        if key in comp:
            check_text(f"{where}.{key}", comp[key], COMPONENT_KEYS[key])
    if kind == "choice_cards" and AGE_RANGE.match(comp.get("label", "")):
        raise Blocked(f"'{where}': choices that are number ranges ask for personal data")
    if kind == "timer":
        if screen != "waiting":
            raise Blocked(f"'{where}': a timer may only count a real wait (the waiting screen)")
        text = comp.get("text", "").strip().lower()
        m = TIMER_TEXT.match(text)
        if text and (not m or (m.group(3).startswith("min") and int(m.group(2)) > MAX_WAIT_MINUTES)):
            raise Blocked(f"'{where}': timer text must read like 'About 4 min left' (at most {MAX_WAIT_MINUTES} min)")
    if kind == "name_input" and not PET_NAME.match(comp.get("label", "").strip().lower()):
        raise Blocked(f"'{where}': inputs may only ask for the pet's name")
    if kind == "photo_picker" and screen != "upload_photos":
        raise Blocked(f"'{where}': photo pickers belong only on upload_photos")


def _check_role(screen, role, comps):
    allowed = ROLES[screen] + COMMON_ROLES
    if role not in allowed:
        raise Blocked(f"'{screen}' has no part called '{role}' (parts: {allowed})")
    if not isinstance(comps, list) or not comps:
        raise Blocked(f"replacing '{screen}.{role}' needs components that do the same job")
    if len(comps) > 6:
        raise Blocked(f"replacing '{screen}.{role}' allows at most 6 components")
    types, required, need, prefix, need_words = ROLE_RULES[role]
    for i, comp in enumerate(comps):
        where = f"{screen}.replace.{role}[{i}]"
        if not isinstance(comp, dict) or comp.get("role") != role:
            raise Blocked(f"every replacement for '{screen}.{role}' must declare role '{role}'")
        if comp.get("type") not in types:
            raise Blocked(f"'{where}': a {comp.get('type')} cannot do the {role} job (use {sorted(types)})")
        _check_component(screen, where, comp, role=role)
    doers = [c for c in comps if c["type"] in required
             and (prefix is None or str(c.get("asset", "")).startswith(prefix))
             and (not need_words or _meaningful(_words_in(c))
                  or (role in PICTURE_OK and str(c.get("asset", "")).startswith("asset:")))]
    if role in ROLE_ACTIONS:
        doers = [c for c in doers if c.get("action") == ROLE_ACTIONS[role]]
    if role == "path_options":
        labels = [_words_in(c) for c in doers]
        if not (any(ADOPT_WORDS.search(t) for t in labels) and any(CREATE_WORDS.search(t) for t in labels)) \
                or len({t.lower() for t in labels}) < 2:
            doers = []
    if role == "sign_in_options":
        doers = [c for c in doers if SIGN_IN_WORDS.search(_words_in(c))]
    if role in ROLE_TEXT_NEEDED and not any(_meaningful(_words_in(c)) for c in comps):
        doers = []
    if len(doers) < need:
        detail = {"path_options": " (two distinct choices: adopting a friend and making your own)",
                  "sign_in_options": " (a sign-in button that says so)"}.get(role, "")
        raise Blocked(f"replacement for '{screen}.{role}' does not do the job{detail}: needs {need} of {sorted(required)}"
                      + (f" with an {prefix} asset" if prefix else "") + (" with real words" if need_words else ""))


def _check_fields(screen, fields, new=False):
    if not isinstance(fields, dict) or not fields:
        raise Blocked(f"screen '{screen}' must map to an object of fields")
    total = 0
    for name, value in fields.items():
        if name not in FIELDS:
            raise Blocked(f"field '{screen}.{name}' is not adjustable")
        kind, limit = FIELDS[name]
        if type(value) is not kind:
            raise Blocked(f"field '{screen}.{name}' must be {kind.__name__}")
        if name == "layout":
            if value not in LAYOUTS:
                raise Blocked(f"layout '{value}' must be one of {sorted(LAYOUTS)}")
        elif name == "components":
            if len(value) > limit:
                raise Blocked(f"'{screen}.components' has more than {limit} items")
            total += len(value)
            for i, comp in enumerate(value):
                if isinstance(comp, dict) and "role" in comp:
                    raise Blocked(f"'{screen}.components[{i}]': only replacements carry a role")
                _check_component(screen, f"{screen}.components[{i}]", comp)
        elif name == "replace":
            if new:
                raise Blocked(f"'{screen}' is new: there is nothing to replace")
            if not value:
                raise Blocked(f"'{screen}.replace' is empty")
            for role, comps in value.items():
                _check_role(screen, role, comps)
                total += len(comps)
        elif kind is str:
            check_text(f"{screen}.{name}", value, limit)
        elif kind is int and not 0 <= value <= limit:
            raise Blocked(f"'{screen}.{name}' must be between 0 and {limit}")
    if total > MAX_COMPONENTS + 6:
        raise Blocked(f"'{screen}' has too many components")
    if new and not ({"headline", "body", "components"} & set(fields)):
        raise Blocked(f"new screen '{screen}' needs a headline, body or components")


def _check_order(order, new_screens):
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise Blocked("_order must be a list of screen names")
    if len(order) != len(set(order)):
        raise Blocked("_order lists a screen twice")
    missing = [x for x in SCREENS if x not in order]
    if missing:
        raise Blocked(f"_order leaves out existing screens {missing}: no step may be removed")
    unknown = [x for x in order if x not in SCREENS and x not in new_screens]
    if unknown:
        raise Blocked(f"_order names screens that are neither onboarding screens nor defined here: {unknown}")
    unplaced = [x for x in new_screens if x not in order]
    if unplaced:
        raise Blocked(f"new screens {unplaced} are defined but not placed in _order")
    existing = [x for x in order if x in SCREENS and x != "sign_in"]
    if existing != [x for x in SCREENS if x != "sign_in"]:
        raise Blocked("existing screens must keep their order; only sign_in may move")
    if order.index("sign_in") < order.index("choose_path"):
        raise Blocked("sign_in may move later, not before choose_path")
    if order.index("sign_in") > order.index("home_intro"):
        raise Blocked("home_intro must come after every existing screen, sign_in included")
    run = 0
    for x in order:
        run = run + 1 if x not in SCREENS else 0
        if run > MAX_NEW_IN_A_ROW:
            raise Blocked(f"at most {MAX_NEW_IN_A_ROW} new screens in a row")


def check_config(config, target_step: str | None = None) -> None:
    """Raise Blocked unless the change is a valid onboarding config that keeps every step and job.

    With target_step, the change may only edit the existing screens of that funnel step (plus new
    screens and the order), so tests that run together never edit the same screen.
    """
    if not isinstance(config, dict) or not config:
        raise Blocked("config must be a non-empty object of onboarding screens")
    if len(json.dumps(config, ensure_ascii=False)) > MAX_CONFIG_CHARS:
        raise Blocked(f"config is longer than {MAX_CONFIG_CHARS} characters")
    new_screens = [k for k in config if k != ORDER_KEY and k not in SCREENS]
    for screen in new_screens:
        if not isinstance(screen, str) or not NEW_SCREEN.match(screen) \
                or any(term in screen for term in NEW_SCREEN_BANNED):
            raise Blocked(f"screen '{screen}' is not part of onboarding (new screens are named new_..., "
                          "and may not look like payment, account, sign-up or settings screens)")
    if len(new_screens) > MAX_NEW_SCREENS:
        raise Blocked(f"at most {MAX_NEW_SCREENS} new screens per change")
    if new_screens and ORDER_KEY not in config:
        raise Blocked("new screens need an _order that places them")
    if target_step is not None:
        outside = touched_screens(config) - STEP_SCREENS.get(target_step, set()) - {ORDER_KEY}
        if outside:
            raise Blocked(f"a {target_step} change may only edit {sorted(STEP_SCREENS.get(target_step, []))}, "
                          f"not {sorted(outside)}")
    for screen, fields in config.items():
        if screen == ORDER_KEY:
            _check_order(fields, new_screens)
        else:
            _check_fields(screen, fields, new=screen in new_screens)


# 3. What the loop may do with experiments ---------------------------------------

class ScopedExperiments:
    """Wraps a backend. Only onboarding tests, only up to the traffic cap and test limit, only these calls."""

    __slots__ = ("__b", "__cap", "__limit", "__mine", "__live", "__closed", "__started", "__harmed")

    def __init__(self, backend, max_share: float, max_tests: int):
        self.__b = backend
        self.__cap = float(max_share)
        self.__limit = int(max_tests)
        self.__mine = set()
        self.__live = set()
        self.__closed = set()
        self.__started = set()
        self.__harmed = set()

    def create(self, change: dict, share: float) -> str:
        try:
            if not isinstance(share, (int, float)) or not math.isfinite(share) or not 0 < share <= self.__cap:
                raise Blocked(f"traffic share must be above 0 and at most {self.__cap:.0%}")
            if len(self.__live) >= self.__limit:
                raise Blocked("too many tests running")
            if len(self.__mine - self.__closed) >= 2 * self.__limit:
                raise Blocked("too many tests created and not yet closed")
            check_plain("title", change.get("title"), 120)
            check_plain("change", change.get("change"), 600)
            check_config(change.get("config"), change.get("target_step"))
        except Blocked as exc:
            audit("create", False, {"title": str(change.get("title"))[:120], "why": str(exc)})
            raise
        tid = self.__b.create(change, share)
        self.__mine.add(tid)
        audit("create", True, {"test": tid, "title": change["title"], "share": share, "config": change["config"]})
        return tid

    def _own(self, tid, action):
        if tid not in self.__mine:
            audit(action, False, {"test": tid, "why": "not a test this loop created"})
            raise Blocked(f"{action} on '{tid}': not an onboarding test this loop created")

    def start(self, tid):
        self._own(tid, "start")
        if tid in self.__closed:
            audit("start", False, {"test": tid, "why": "a stopped test cannot be restarted"})
            raise Blocked("a stopped test cannot be restarted")
        if tid not in self.__live and len(self.__live) >= self.__limit:
            audit("start", False, {"test": tid, "why": "too many tests running"})
            raise Blocked("too many tests running")
        audit("start", True, {"test": tid})
        self.__live.add(tid)
        self.__started.add(tid)
        self.__b.start(tid)

    def stop(self, tid, why="decided"):
        self._own(tid, "stop")
        audit("stop", True, {"test": tid, "why": why})
        if not str(why).startswith("won"):
            self.__harmed.add(tid)               # only a test stopped as a winner may ship
        self.__live.discard(tid)
        self.__closed.add(tid)
        self.__b.stop(tid)

    def read(self, tid):
        self._own(tid, "read")
        return self.__b.read(tid)

    def mark(self, tid):
        self._own(tid, "mark")
        return self.__b.mark(tid)

    def read_since(self, tid, token):
        self._own(tid, "read")
        return self.__b.read_since(tid, token)

    def ship(self, tid):
        self._own(tid, "ship")
        if tid not in self.__started:
            audit("ship", False, {"test": tid, "why": "never tested"})
            raise Blocked("only a test that ran can be shipped")
        if tid in self.__harmed:
            audit("ship", False, {"test": tid, "why": "not stopped as a winner"})
            raise Blocked("only a test stopped as a winner can be shipped")
        audit("ship", True, {"test": tid})
        self.__b.ship(tid)

    def __getattr__(self, name):
        audit(name, False, {"why": "call not on the allow-list"})
        raise Blocked(f"'{name}' is not an allowed experiment call")


# 4. What data the loop may read -------------------------------------------------

class DataGateway:
    """Read-only, aggregate-only access to the two prepared data files."""

    __slots__ = ("__root",)
    ALLOWED_EVENTS = frozenset({"onboarding_started", "path_chosen", "sign_in_started", "adoption_confirmed",
                                "home_first_seen", "onboarding_finished"})

    def __init__(self, root: Path = ROOT):
        self.__root = Path(root)

    def funnel(self, events=None):
        events = list(events or [])
        bad = [e for e in events if e not in self.ALLOWED_EVENTS]
        if bad:
            audit("read_funnel", False, {"events": bad})
            raise Blocked(f"events outside onboarding: {bad}")
        audit("read_funnel", True, {"events": events or "all onboarding steps"})
        data = json.loads((self.__root / "data" / "funnel_week0.json").read_text())
        if events:
            data["steps"] = [s for s in data["steps"] if s["event"] in events]
        return data

    def support_themes(self):
        audit("read_support_themes", True, {})
        return json.loads((self.__root / "data" / "support_week0.json").read_text())

    def __getattr__(self, name):
        audit(name, False, {"why": "data call not on the allow-list"})
        raise Blocked(f"'{name}' is not an allowed data call (user-level and raw data are never available)")
