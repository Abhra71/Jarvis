"""A plan: the steps for one request, each with the check that proves it worked.

Three sources, cheapest first:
    code    every part of the request is a built-in ability ("snap left and maximise": 0 AI)
    memory  this exact request worked before as a plan (data/plans.json: 0 AI)
    ai      one AI call returns the whole plan as JSON (below), checked against the real tools here
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .. import abilities
from ..config import ROOT
from ..nlu import normalize
from ..skills import check_args, request_parts
from . import checks

log = logging.getLogger(__name__)

PLANS_FILE = ROOT / "data" / "plans.json"

# Tools that need a picture of the screen: plans are text-only, so these go to the old (seeing) loop.
EYES_TOOLS = {"look_at_screen", "click", "click_pair", "hover"}
# Not for plans: the AI's own helpers.
_HIDDEN = {"more_tools", "page_elements"} | EYES_TOOLS
MAX_STEPS = 12
# Not a tool: "now look at the new screen (as text) and plan the rest". For steps that depend on what a page
# or app shows next (search results, a site's menus): a person looks, then clicks.
LOOK_AGAIN = "look_again"


class PlanError(ValueError):
    """The AI's plan can't be used (bad JSON, unknown tool, bad args)."""


class NeedsEyes(Exception):
    """This request needs to see the screen as a picture: the old loop (with Gemini's eyes) handles it."""


@dataclass
class Step:
    tool: str
    args: dict
    check: checks.Check | None = None
    say: str = ""

    def label(self) -> str:
        if self.tool == "do":
            v = self.args.get("value")
            return f"{self.args.get('ability')}({v})" if v else str(self.args.get("ability"))
        args = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"{self.tool}({args})"

    def to_json(self) -> dict:
        d = {"do": self.tool, "args": self.args}
        if self.check:
            d["expect"] = str(self.check)
        if self.say:
            d["say"] = self.say
        return d


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    reply: str = ""   # what to say when every step is done (and checked)
    ask: str = ""     # a question for the user instead of acting
    source: str = "ai"


# ---- reading the AI's plan ------------------------------------------------------

def _json(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise PlanError(f"no JSON object in {text[:80]!r}")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as e:
        raise PlanError(f"bad JSON: {e}") from e


def _step(d: dict, tools: dict) -> Step:
    if not isinstance(d, dict):
        raise PlanError(f"a step must be an object, got {d!r}")
    name = str(d.get("do") or d.get("tool") or "").strip()
    args = d.get("args") or {}
    if not isinstance(args, dict):
        raise PlanError(f"args of {name} must be an object")
    if name in abilities.REGISTRY:  # {"do": "snap_left"} = the ability, through the do tool
        args = {"ability": name, **({"value": str(args.get("value"))} if args.get("value") else {})}
        name = "do"
    if name in EYES_TOOLS:
        raise NeedsEyes(name)
    if name in (LOOK_AGAIN, "look", "next", "replan"):
        return Step(LOOK_AGAIN, {})
    if name not in tools or name in _HIDDEN:
        raise PlanError(f"unknown tool {name!r}")
    clean, problem = check_args(tools[name], args)
    if problem:
        raise PlanError(f"{name}: {problem}")
    try:
        check = checks.parse(d.get("expect"))
    except checks.BadCheck as e:
        # 1 Oct replay: "expect: volume" threw away a good plan. A check we can't read is no check (the step
        # is then reported as done but not seen), not a reason to give up.
        log.info("Dropping an unreadable check on %s: %s", name, e)
        check = None
    return Step(name, clean, check, str(d.get("say") or "").strip())


# Abilities that act on the FRONT window: named with a window ("snap_left" + "Google Chrome"), that window is
# brought to the front first (30 Sep dry run: it would have snapped whatever was in front).
FRONT_WINDOW_ABILITIES = {"snap_left", "snap_right", "maximize_front", "minimize_front", "other_screen"}


def _expand(step: Step) -> list[Step]:
    target = step.args.get("value") if step.tool == "do" else None
    if target and step.args.get("ability") in FRONT_WINDOW_ABILITIES:
        focus = Step("window", {"app": str(target), "action": "focus"}, checks.Check("window", str(target)))
        return [focus, Step("do", {"ability": step.args["ability"]}, None, step.say)]
    return [step]


def parse(raw, tools: dict, source: str = "ai") -> Plan:
    """The AI's JSON -> a Plan whose every step names a real tool with valid args. Raises PlanError/NeedsEyes."""
    data = _json(raw)
    if data.get("need_eyes"):
        raise NeedsEyes("the planner asked to see the screen")
    steps = data.get("steps") or []
    if not isinstance(steps, list):
        raise PlanError("steps must be a list")
    if len(steps) > MAX_STEPS:
        raise PlanError(f"{len(steps)} steps is too many")
    plan = Plan([x for s in steps for x in _expand(_step(s, tools))], str(data.get("reply") or "").strip(),
                str(data.get("ask") or "").strip(), source)
    if not plan.steps and not plan.reply and not plan.ask:
        raise PlanError("empty plan")
    return plan


# ---- plans made in code --------------------------------------------------------

# "snap chrome left", "put vs code on the right", "maximize spotify", "minimise whatsapp"
_APP_WINDOW = re.compile(r"(?P<verb>snap|put|move|maximi[sz]e|minimi[sz]e) (?:the )?(?P<app>[a-z][a-z0-9 .]{1,30}?)"
                         r"(?: window)?(?: (?:to |on )?(?:the )?(?P<side>left|right)(?: side| half)?)?")
_WINDOW_VERBS = {("snap", "left"): "snap_left", ("snap", "right"): "snap_right", ("put", "left"): "snap_left",
                 ("put", "right"): "snap_right", ("move", "left"): "snap_left", ("move", "right"): "snap_right",
                 ("maximize", ""): "maximize_front", ("maximise", ""): "maximize_front",
                 ("minimize", ""): "minimize_front", ("minimise", ""): "minimize_front"}
_NOT_APPS = {"it", "this", "that", "this window", "the window", "window", "screen", "the screen", "this app",
             "left", "right", "it to", "this to", "browser", "all", "everything", "all windows", "them"}


_CLOSE_THIS = re.compile(r"close (?:this|it|this one|this 1|that|this page|the page|this tab|the current (?:one|tab|page))")
_BROWSER_APPS = {"chrome", "msedge", "brave", "firefox", "opera"}
_AS_WELL = re.compile(r"(?: as well| too| also)$")
_PW = re.compile(r"\b(pw|physics wallah)\b")
_NOT_PW = re.compile(r"\b(youtube|google|search|video|videos)\b")


def _mail_plan(text: str) -> list[Step] | None:
    """'email mom saying I'll be late': write it in Gmail (code), then send, which waits for the user's yes."""
    from ..skills.sites import gmail
    said = " ".join(text.split())  # the user's words as said: the email keeps their punctuation
    if not gmail.parse(said) or _NOT_PW.search(normalize(text)):
        return None
    return [Step("do", {"ability": "gmail_draft", "value": said}), Step("do", {"ability": "gmail_send"})]


def _pw_plan(text: str, front: str) -> list[Step] | None:
    """'Open Physics Wallah, my batch, chemistry' / 'open chemistry' with PW in front: the PW route in code."""
    from ..skills.sites import pw
    t = normalize(text)
    if _NOT_PW.search(t):
        return None
    named = bool(_PW.search(t))
    on_pw = "physics wallah" in (front or "").lower()
    if "khazana" in t:
        return [Step("do", {"ability": "pw_khazana", "value": t})]
    subject = pw.subject_in(t)
    if subject and (named or (on_pw and re.match(r"(open|go to|show|take me to)\b", t))):
        return [Step("do", {"ability": "pw_subject", "value": subject})]
    if named and re.fullmatch(r"(open|go to|show( me)?|take me to) (my )?(pw|physics wallah)( and)?,?( (my )?batch)?", t):
        return [Step("do", {"ability": "pw_batch"})]
    return None


def code_plan(text: str, front: str = "", unsure: bool = False) -> Plan | None:
    """'snap left and maximise', 'play lofi on YouTube and make it full screen', 'pause, back 30 seconds and
    subtitles on' -> steps done in code, no AI. Only when *every* part is an ability or a YouTube command."""
    from ..skills.sites import youtube

    pw_steps = _pw_plan(text, front)
    if pw_steps:
        return Plan(pw_steps, source="code")
    mail_steps = _mail_plan(text)
    if mail_steps:
        return Plan(mail_steps, source="code")
    parts = request_parts(text)
    if len(parts) < 2:
        # One part: the site packs and abilities.handle already had their chance, except a window move with an
        # app's name ("maximize Claude", 1 Oct replay: it went to the AI).
        m = _APP_WINDOW.fullmatch(parts[0]) if parts else None
        ability_name = m and _WINDOW_VERBS.get((m.group("verb"), m.group("side") or ""))
        if ability_name and m.group("app") not in _NOT_APPS and not m.group("app").startswith(("it ", "this ")):
            return Plan(_expand(Step("do", {"ability": ability_name, "value": m.group("app")})), source="code")
        browser, _, title = (front or "").partition(": ")
        if parts and _CLOSE_THIS.fullmatch(parts[0]) and browser.lower() in _BROWSER_APPS and title:
            # "Close this." in a browser = the tab (1 Oct replay: the AI closed the whole Chrome window).
            return Plan([Step("browser", {"action": "close_tab"}, checks.Check("window", title, True))],
                        source="code")
        return None
    on_youtube = "youtube" in normalize(text) or youtube.is_front(front)
    steps = []
    last_verb = ""
    browser, _, title = (front or "").partition(": ")
    in_browser = browser.lower() in _BROWSER_APPS
    for part in parts:
        part = _AS_WELL.sub("", part)
        if in_browser and _CLOSE_THIS.fullmatch(part):
            steps.append(Step("browser", {"action": "close_tab"}))
            continue
        m = _APP_WINDOW.fullmatch(part)
        if not m and last_verb:  # "snap chrome left and VS Code right": the verb is said once
            m = _APP_WINDOW.fullmatch(f"{last_verb} {part}")
        ability_name = m and _WINDOW_VERBS.get((m.group("verb"), m.group("side") or ""))
        if ability_name and m.group("app") not in _NOT_APPS:
            steps += _expand(Step("do", {"ability": ability_name, "value": m.group("app")}))
            last_verb = m.group("verb")
            continue
        last_verb = ""
        hit = abilities.match(part)
        if hit:
            ab, value = hit
            steps.append(Step("do", {"ability": ab.name, **({"value": value} if value else {})}))
        elif on_youtube and youtube.understands(part, unsure):
            steps.append(Step("youtube", {"command": part}))
        else:
            return None
    return Plan(steps, source="code")


# ---- remembered plans ------------------------------------------------------------

_CONTEXT_WORDS = re.compile(r"\b(it|this|that|these|those|here|there|them|him|her|again|same)\b")


class PlanMemory:
    """Requests that worked as a plan once: next time they run from here, with no AI. Checks still run,
    so a remembered plan that stops working is noticed, repaired, and replaced.

    Patterns (Phase 5): a plan that used a word of the request as a value ("search drone on amazon" ->
    web_search(query="drone", site="amazon")) is also kept as a pattern, "search {x} on amazon", so "search
    headphones on amazon" runs with no AI too."""

    def __init__(self, path: Path = PLANS_FILE):
        self.path = path
        self.lock = threading.Lock()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.patterns: dict[str, dict] = data.pop(_PATTERNS_KEY, {})
        self.plans: dict[str, dict] = data

    @staticmethod
    def key(text: str) -> str:
        return normalize(text)

    def get(self, text: str, tools: dict) -> Plan | None:
        hit, source = self.plans.get(self.key(text)), "memory"
        if not hit:
            hit, source = self._from_pattern(self.key(text)), "pattern"
        if not hit:
            return None
        try:
            return parse(hit, tools, source=source)
        except (PlanError, NeedsEyes):
            self.forget(text)  # a tool was renamed or removed since
            return None

    @staticmethod
    def worth_keeping(text: str, steps: list[Step]) -> bool:
        key = normalize(text)
        # "it"/"this"/"here" depend on what's on screen now, so the same words can mean something else later.
        # A request cut off mid-sentence ("maximize the", 1 Oct: remembered as "maximize Chrome") isn't one.
        return bool(steps) and 0 < len(key.split()) <= 16 and not _CONTEXT_WORDS.search(key) \
            and not _DANGLING.search(key)

    def learn(self, text: str, steps: list[Step], reply: str):
        if not self.worth_keeping(text, steps):
            return
        key = self.key(text)
        with self.lock:
            self.plans[key] = {"steps": [s.to_json() for s in steps], "reply": reply}
            pattern = _pattern(key, steps, reply)
            if pattern:
                self.patterns[pattern[0]] = pattern[1]
            self._save()
        log.info("Remembered a %d-step plan for %r%s", len(steps), key,
                 f" (and the pattern {pattern[0]!r})" if pattern else "")

    def forget(self, text: str):
        key = self.key(text)
        with self.lock:
            gone = self.plans.pop(key, None) is not None
            for p in [p for p in self.patterns if _pattern_regex(p).fullmatch(key)]:
                self.patterns.pop(p)
                gone = True
                log.info("Forgot the pattern %r", p)
            if gone:
                self._save()
                log.info("Forgot the remembered plan for %r", key)

    def _from_pattern(self, key: str) -> dict | None:
        for p, plan in self.patterns.items():
            m = _pattern_regex(p).fullmatch(key)
            if not m:
                continue
            x = m.group("x").strip()
            if not x or len(x.split()) > 8 or _CONTEXT_WORDS.search(x) or _MORE_PARTS.search(x):
                continue
            log.info("Pattern %r with x = %r", p, x)
            return _fill(plan, x)
        return None

    def _save(self):
        try:
            self.path.parent.mkdir(exist_ok=True)
            data = {**self.plans, **({_PATTERNS_KEY: self.patterns} if self.patterns else {})}
            self.path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        except OSError:
            log.warning("Couldn't save remembered plans", exc_info=True)


_PATTERNS_KEY = "__patterns__"
_MORE_PARTS = re.compile(r"\b(and|then|also)\b")  # "search boots and open youtube on amazon": not one value
_DANGLING = re.compile(r"\b(the|a|an|to|and|of|in|on|my|for|with|at|from)$")
_SLOT_STOP = {"the", "a", "an", "to", "and", "of", "in", "on", "my", "for", "with", "at", "it", "this", "that",
              "open", "search", "play", "close", "go", "find", "show", "me", "please", "new", "tab", "window"}
_URL_ARGS = ("url",)


def _pattern_regex(pattern: str) -> re.Pattern:
    before, _, after = pattern.partition("{x}")
    return re.compile(re.escape(before) + r"(?P<x>.+?)" + re.escape(after))


def _pattern(key: str, steps: list[Step], reply: str) -> tuple[str, dict] | None:
    """('search {x} on amazon', plan with {x} in its values) when a run of the request's words was used as a
    step's value; None otherwise. One slot, at least two fixed words around it, never a small word."""
    words = key.split()
    for n in range(min(6, len(words) - 2), 0, -1):  # longest slot first
        for i in range(len(words) - n + 1):
            slot = " ".join(words[i:i + n])
            if len(slot) < 3 or all(w in _SLOT_STOP for w in words[i:i + n]):
                continue
            rx = re.compile(r"(?<![\w])" + re.escape(slot).replace(r"\ ", r"[\s+_-]+") + r"(?![\w])", re.I)
            steps_json, used = [], False
            for s in steps:
                d = s.to_json()
                d["args"] = {k: _put_slot(rx, k, v) for k, v in s.args.items()}
                used |= d["args"] != s.args
                steps_json.append(d)
            if not used:
                continue  # 1 Oct: a slot must really be IN a value, or every request would get the same plan
            pattern = " ".join(words[:i] + ["{x}"] + words[i + n:])
            return pattern, {"steps": steps_json, "reply": rx.sub("{x}", reply or "")}
    return None


def _put_slot(rx: re.Pattern, key: str, value):
    """The value with the slot's words as {x}. In an address only the search part (after '?') counts: the site's
    own name is not a slot ("open chess com" must not turn into "https://www.{x}")."""
    if not isinstance(value, str):
        return value
    if key in _URL_ARGS:
        site, q, query = value.partition("?")
        return site + q + rx.sub("{x}", query) if q else value
    return rx.sub("{x}", value)


def _fill(plan: dict, x: str) -> dict:
    from urllib.parse import quote_plus
    steps = []
    for d in plan["steps"]:
        args = {k: (v.replace("{x}", quote_plus(x) if k in _URL_ARGS else x) if isinstance(v, str) else v)
                for k, v in (d.get("args") or {}).items()}
        steps.append({**d, "args": args, "expect": str(d.get("expect", "")).replace("{x}", x)})
    return {"steps": steps, "reply": str(plan.get("reply", "")).replace("{x}", x)}


# ---- the planner prompt -----------------------------------------------------------

# Which tools and abilities a request can need (1 Oct: every plan sent all 34 tools and 36 abilities, ~1,600
# tokens, most of them for other kinds of work). Areas not named by the request or the front window are left out
# of the first plan; a repair after a failure still sees everything.
_AREAS = {
    "code": re.compile(r"\b(code|coding|lines?|comment|uncomment|compile|run|class|bluej|blue j|blue jay|vs ?code|"
                       r"visual studio|java|c\+\+|cpp|program|method|function|editor)\b"),
    "files": re.compile(r"\b(files?|folders?|pdfs?|docs?|documents?|downloads?|desktop|pictures?|photos?|images?|"
                        r"screenshots?|copy|move|rename|upload|attach|newest|latest|txt|notes?|drive|zip|excel|"
                        r"word|ppt|presentation|resume|cv)\b"),
    "mail": re.compile(r"\b(e-?mails?|mail|gmail|inbox|send|reply|draft)\b"),
    "pw": re.compile(r"\b(pw|physics wallah|batch|khazana|lectures?|chemistry|physics|maths?|biology|botany|"
                     r"zoology|study|teacher|sir|victory)\b"),
    "games": re.compile(r"\b(games?|efootball|football|pes|gaming)\b"),
    "system": re.compile(r"\b(bluetooth|wi-?fi|internet|brightness|bright|dim|night light|airplane|flight mode|hotspot|"
                         r"battery saver|captions?|headphones?|earphones?|buds|rockerz|speaker|connect|disconnect|"
                         r"switch|turn (on|off))\b"),
    "youtube": re.compile(r"\b(youtube|videos?|songs?|music|play|pause|resume|watch|subtitles?|skip|ad|full ?screen|"
                          r"lofi|playlist)\b"),
}
_FRONT_AREAS = {"code": re.compile(r"visual studio code|bluej|^code:|^java", re.I),
                "files": re.compile(r"^explorer:", re.I), "mail": re.compile(r"gmail|inbox", re.I),
                "pw": re.compile(r"physics wallah|pw\.live|\bpw\b", re.I), "youtube": re.compile(r"youtube", re.I)}
_ABILITY_AREAS = {"code": "code", "files": "files", "upload": "files", "mail": "mail", "pw": "pw",
                  "games": "games", "system": "system"}   # jarvis/abilities/<module> -> area; others always
_TOOL_AREAS = {"youtube": "youtube", "find_files": "files", "list_folder": "files", "open_path": "files",
               "show_in_explorer": "files", "create_folder": "files", "copy_file": "files", "move_file": "files",
               "rename_file": "files", "read_text_file": "files", "write_text_file": "files"}


def areas_for(request: str, front: str = "") -> set[str]:
    """The areas this request (or the window in front) can need."""
    t = normalize(request)
    found = {a for a, rx in _AREAS.items() if rx.search(t)}
    found |= {a for a, rx in _FRONT_AREAS.items() if rx.search(front or "")}
    return found


def _area_of(ab) -> str:
    return _ABILITY_AREAS.get(ab.run.__module__.rsplit(".", 1)[-1], "")


def catalog(tools: dict, areas: set[str] | None = None) -> str:
    """The tools a plan may use, one short line each: 'open_app(name): Launch a desktop app.'
    With `areas`, tools and abilities for other kinds of work are left out (see _AREAS)."""
    lines = []
    for t in tools.values():
        if t.name in _HIDDEN or t.name == "do":
            continue
        if areas is not None and _TOOL_AREAS.get(t.name, "") not in areas | {""}:
            continue
        args = []
        for pname, (_, _, required, enum) in t.params.items():
            a = pname + ("" if required else "?")
            if enum and len(enum) <= 8:
                a += "=" + "|".join(map(str, enum))
            args.append(a)
        desc = t.description.split(". ")[0].rstrip(".")
        lines.append(f"{t.name}({', '.join(args)}): {desc}")
    shown = [a for a in abilities.REGISTRY.values() if areas is None or _area_of(a) in areas | {""}]
    ab = "; ".join(f"{a.name}{'(' + a.value_hint + ')' if a.value_hint else ''}" for a in shown)
    lines.append(f'Abilities (instant, exact; step {{"do": "<name>", "args": {{"value": ...}}}}): {ab}')
    return "\n".join(lines)


SYSTEM = """You plan actions for Jarvis, a voice assistant that runs the user's Windows PC like a fast, careful \
person. Answer with ONE JSON object and nothing else:
{"steps": [{"do": "<tool or ability>", "args": {...}, "expect": "<check>", "say": "<optional>"}], \
"reply": "<one short spoken sentence, true once every step worked>"}
Or {"reply": "..."} alone to just answer (questions, chat); {"ask": "<one short question>"} if the request is \
unclear or garbled; {"need_eyes": true} only if it needs to SEE pictures, video thumbnails, a game board or \
unnamed icons.
Rules:
- Fewest steps, fastest way: ability > youtube tool > shortcut (press_key) > direct URL / web_search / site_search > click_element by name. Never guess screen positions.
- Apps: open_app (installed desktop app, the default; don't ask "desktop or web?") or window focus if it's already open. Never click desktop or taskbar icons.
- click_element takes a name from "On screen" (or text read from the screen), or, right after opening something, the name you expect there. When the next clicks depend on a page that's still loading or changing (search results, a site's menus), put {"do": "look_again"} there: you'll see the new screen and plan the rest.
- Abilities that take a value need it: {"do": "open_settings", "args": {"value": "bluetooth"}}. snap_left/right, maximize_front, minimize_front, other_screen act on the front window; to act on another, give its name as value.
- web_search only to search the web. To open a site, or a page inside it, use open_website (its address), then look_again.
- A request that goes deeper than the first page ("PW, my batch, chemistry"): open it, then {"do": "look_again"}; you'll see the page and continue. Don't stop at the first page.
- If the tools can't finish it, do what they can and make "reply" say exactly what's done and what's left ("I opened Bluetooth settings; I can't connect headphones by myself yet.").
- To type into a box: focus it first (its shortcut, or click_element on the field), then type_text.
- "expect" = how to SEE that the step worked: something that changes because of it. "window: X" (front app/title), "open: X", "closed: X", "element: X" (a named item that appears), "not element: X" (one that goes away, e.g. a dialog's button after clicking it), "text: X", "focus: field", "url: X", "playing", "paused", "fullscreen", "not fullscreen", "not dialog". Never the item you just clicked, never a label you guess. "" when nothing visible changes (volume, timers, files); Jarvis then says it couldn't confirm.
- Do only what was asked. "It"/"that" = the recent context below.
- "Close this/it/this one" with a browser in front = the current TAB (press_key ctrl+w), never the whole window.
- Never guess a website from one unclear or odd word ("Playbots.", "video.com"): ask what they meant.
- Never invent text to type ("Your text here"): if they didn't say what to type, ask.
- The user thinking aloud or stating something ("only Gemini and Groq will be used") is not a request: answer with {"reply": ...} and do nothing.
- "reply": the result in the user's words ("Playing it in full screen."), only what the steps really do.
- "say" only on a slow first step the user will notice, 2-4 words ("Opening WhatsApp").
- Sending, posting, buying, deleting: include that step; Jarvis itself asks the user before doing it.
- Never type passwords or card numbers.
Tools:
"""


# Rules only some requests need (left out of the first plan when they can't apply, like the tools).
_FILES_RULE = ('- Files and folders: short paths work ("Downloads", "Desktop/Trips", "Documents/cv.pdf"); never guess '
               'full paths or %USERNAME%.\n')
_DIALOG_RULE = '- If "A DIALOG BOX IS OPEN", answer it first (click its button, or press esc) before anything else.\n'


def system_for(tools: dict, areas: set[str] | None, screen: str = "") -> str:
    """The planner's instructions and tools: everything for a repair (areas None); otherwise only the rules and
    tools that can apply to this request and screen."""
    extra = ""
    if areas is None or "files" in areas:
        extra += _FILES_RULE
    if areas is None or "DIALOG BOX IS OPEN" in screen:
        extra += _DIALOG_RULE
    head, tail = SYSTEM.rsplit("Tools:", 1)
    return head + extra + "Tools:" + tail + catalog(tools, areas)


def site_hints(request: str) -> str:
    """Addresses of the sites a request names ("physics wallah" -> https://www.pw.live), so the plan opens the
    site itself instead of searching Google for it (30 Sep)."""
    from ..skills.browser import SITES
    t = normalize(request)
    hits = {name: url for name, url in SITES.items() if re.search(rf"\b{re.escape(name)}\b", t)}
    return "; ".join(f"{name} = {url}" for name, url in hits.items())


def planning_prompt(request: str, tools: dict, screen: str, recent: str, shortcuts: str, unsure: bool,
                    front: str = "") -> tuple[str, str]:
    system = system_for(tools, areas_for(request + " " + recent[-200:], front), screen)
    user = [f"Request: {request}"]
    sites = site_hints(request)
    if sites:
        user.append(f"Sites named (open these addresses, then look_again for the pages inside): {sites}")
    if unsure:
        user.append("(Speech recognition was unsure of these words: if they don't clearly make sense, ask.)")
    if recent:
        # 30 Sep: after a stuck "pause", the next request ("open chess.com") was planned as the pause again.
        user.append("Earlier (only to know what 'it'/'that' means; those requests are over, even if they failed: "
                    f"never redo them unless this request asks):\n{recent}")
    user.append(f"Screen now:\n{screen}")
    if shortcuts:
        user.append(f"Shortcuts here: {shortcuts}")
    user.append(f"Plan ONLY this request: {request}")
    return system, "\n".join(user)


def continue_prompt(request: str, tools: dict, done: list[str], screen: str, shortcuts: str,
                    front: str = "") -> tuple[str, str]:
    """After a look_again: plan the rest from the screen as it is now."""
    system = system_for(tools, areas_for(request, front), screen)
    user = [f"Request: {request}",
            "Done so far (don't repeat): " + ("; ".join(done) or "nothing"),
            f"Screen now:\n{screen}"]
    if shortcuts:
        user.append(f"Shortcuts here: {shortcuts}")
    user.append('Return the REMAINING steps as {"steps": [...], "reply": "..."}; {"steps": [], "reply": "..."} if '
                'it\'s already done; or {"ask": "<one specific question>"}.')
    return system, "\n".join(user)


def repair_prompt(request: str, tools: dict, done: list[str], failed: str, why: str, screen: str,
                  shortcuts: str) -> tuple[str, str]:
    system = system_for(tools, None)
    user = [f"Request: {request}",
            "Done so far (don't repeat): " + ("; ".join(done) or "nothing"),
            f"This step failed: {failed}. {why}",
            f"Screen now:\n{screen}"]
    if shortcuts:
        user.append(f"Shortcuts here: {shortcuts}")
    user.append('Return the REMAINING steps as {"steps": [...], "reply": "..."} (another way, not the same step '
                'again), or {"ask": "<one specific question>"} if you can\'t tell what to do.')
    return system, "\n".join(user)
