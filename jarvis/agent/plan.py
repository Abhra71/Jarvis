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
        raise PlanError(str(e)) from e
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
             "left", "right", "it to", "this to"}


_PW = re.compile(r"\b(pw|physics wallah)\b")
_NOT_PW = re.compile(r"\b(youtube|google|search|video|videos)\b")


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
    parts = request_parts(text)
    if len(parts) < 2:
        return None  # one part: the site packs and abilities.handle already had their chance before the AI
    on_youtube = "youtube" in normalize(text) or youtube.is_front(front)
    steps = []
    last_verb = ""
    for part in parts:
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
    so a remembered plan that stops working is noticed, repaired, and replaced."""

    def __init__(self, path: Path = PLANS_FILE):
        self.path = path
        self.lock = threading.Lock()
        try:
            self.plans: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.plans = {}

    @staticmethod
    def key(text: str) -> str:
        return normalize(text)

    def get(self, text: str, tools: dict) -> Plan | None:
        hit = self.plans.get(self.key(text))
        if not hit:
            return None
        try:
            return parse(hit, tools, source="memory")
        except (PlanError, NeedsEyes):
            self.forget(text)  # a tool was renamed or removed since
            return None

    @staticmethod
    def worth_keeping(text: str, steps: list[Step]) -> bool:
        key = normalize(text)
        # "it"/"this"/"here" depend on what's on screen now, so the same words can mean something else later.
        return bool(steps) and 0 < len(key.split()) <= 16 and not _CONTEXT_WORDS.search(key)

    def learn(self, text: str, steps: list[Step], reply: str):
        if not self.worth_keeping(text, steps):
            return
        with self.lock:
            self.plans[self.key(text)] = {"steps": [s.to_json() for s in steps], "reply": reply}
            self._save()
        log.info("Remembered a %d-step plan for %r", len(steps), self.key(text))

    def forget(self, text: str):
        with self.lock:
            if self.plans.pop(self.key(text), None) is not None:
                self._save()
                log.info("Forgot the remembered plan for %r", self.key(text))

    def _save(self):
        try:
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(self.plans, indent=1, sort_keys=True), encoding="utf-8")
        except OSError:
            log.warning("Couldn't save remembered plans", exc_info=True)


# ---- the planner prompt -----------------------------------------------------------

def catalog(tools: dict) -> str:
    """Every tool a plan may use, one short line each: 'open_app(name): Launch a desktop app.'"""
    lines = []
    for t in tools.values():
        if t.name in _HIDDEN or t.name == "do":
            continue
        args = []
        for pname, (_, _, required, enum) in t.params.items():
            a = pname + ("" if required else "?")
            if enum and len(enum) <= 8:
                a += "=" + "|".join(map(str, enum))
            args.append(a)
        desc = t.description.split(". ")[0].rstrip(".")
        lines.append(f"{t.name}({', '.join(args)}): {desc}")
    ab = "; ".join(f"{a.name}{'(' + a.value_hint + ')' if a.value_hint else ''}" for a in abilities.REGISTRY.values())
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
- Files and folders: short paths work ("Downloads", "Desktop/Trips", "Documents/cv.pdf"); never guess full paths or %USERNAME%.
- web_search only to search the web. To open a site, or a page inside it, use open_website (its address), then look_again.
- A request that goes deeper than the first page ("PW, my batch, chemistry"): open it, then {"do": "look_again"}; you'll see the page and continue. Don't stop at the first page.
- If the tools can't finish it, do what they can and make "reply" say exactly what's done and what's left ("I opened Bluetooth settings; I can't connect headphones by myself yet.").
- To type into a box: focus it first (its shortcut, or click_element on the field), then type_text.
- If "A DIALOG BOX IS OPEN", answer it first (click its button, or press esc) before anything else.
- "expect" = how to SEE that the step worked: something that changes because of it. "window: X" (front app/title), "open: X", "closed: X", "element: X" (a named item that appears), "not element: X" (one that goes away, e.g. a dialog's button after clicking it), "text: X", "focus: field", "url: X", "playing", "paused", "fullscreen", "not fullscreen", "not dialog". Never the item you just clicked, never a label you guess. "" when nothing visible changes (volume, timers, files); Jarvis then says it couldn't confirm.
- Sending, posting, buying, deleting: include that step; Jarvis itself asks the user before doing it.
- Do only what was asked. "It"/"that" = the recent context below.
- "reply": the result in the user's words ("Playing it in full screen."), only what the steps really do.
- "say" only on a slow first step the user will notice, 2-4 words ("Opening WhatsApp").
- Never type passwords or card numbers.
Tools:
"""


def site_hints(request: str) -> str:
    """Addresses of the sites a request names ("physics wallah" -> https://www.pw.live), so the plan opens the
    site itself instead of searching Google for it (30 Sep)."""
    from ..skills.browser import SITES
    t = normalize(request)
    hits = {name: url for name, url in SITES.items() if re.search(rf"\b{re.escape(name)}\b", t)}
    return "; ".join(f"{name} = {url}" for name, url in hits.items())


def planning_prompt(request: str, tools: dict, screen: str, recent: str, shortcuts: str, unsure: bool) -> tuple[str, str]:
    system = SYSTEM + catalog(tools)
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


def continue_prompt(request: str, tools: dict, done: list[str], screen: str, shortcuts: str) -> tuple[str, str]:
    """After a look_again: plan the rest from the screen as it is now."""
    system = SYSTEM + catalog(tools)
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
    system = SYSTEM + catalog(tools)
    user = [f"Request: {request}",
            "Done so far (don't repeat): " + ("; ".join(done) or "nothing"),
            f"This step failed: {failed}. {why}",
            f"Screen now:\n{screen}"]
    if shortcuts:
        user.append(f"Shortcuts here: {shortcuts}")
    user.append('Return the REMAINING steps as {"steps": [...], "reply": "..."} (another way, not the same step '
                'again), or {"ask": "<one specific question>"} if you can\'t tell what to do.')
    return system, "\n".join(user)
