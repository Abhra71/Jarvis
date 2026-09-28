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
    plan = Plan([_step(s, tools) for s in steps], str(data.get("reply") or "").strip(),
                str(data.get("ask") or "").strip(), source)
    if not plan.steps and not plan.reply and not plan.ask:
        raise PlanError("empty plan")
    return plan


# ---- plans made in code --------------------------------------------------------

def code_plan(text: str) -> Plan | None:
    """'snap left and maximise' -> two abilities, no AI. Only when *every* part is an ability."""
    parts = request_parts(text)
    if len(parts) < 2:
        return None  # one part: abilities.handle already had its chance before the AI
    steps = []
    for part in parts:
        hit = abilities.match(part)
        if not hit:
            return None
        ab, value = hit
        steps.append(Step("do", {"ability": ab.name, **({"value": value} if value else {})}))
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
- Fewest steps, fastest way: ability > shortcut (press_key) > direct URL / web_search / site_search > \
click_element by name. Never guess screen positions.
- click_element uses a name from "On screen", or, right after opening something, the name you expect there; \
the check after each step verifies it.
- To type into a box: focus it first (its shortcut, or click_element on the field), then type_text.
- "expect" after every step that changes the screen: "window: X" (front app/title), "open: X", "closed: X", \
"element: X" (a named button/link/field), "text: X" (visible), "focus: field", "url: X". "" when the tool's own \
result is enough (volume, media, timers, files).
- Sending, posting, buying, deleting: include that step; Jarvis itself asks the user before doing it.
- Do only what was asked. "It"/"that" = the recent context below.
- "say" only on a slow first step the user will notice, 2-4 words ("Opening WhatsApp").
- Never type passwords or card numbers.
Tools:
"""


def planning_prompt(request: str, tools: dict, screen: str, recent: str, shortcuts: str, unsure: bool) -> tuple[str, str]:
    system = SYSTEM + catalog(tools)
    user = [f"Request: {request}"]
    if unsure:
        user.append("(Speech recognition was unsure of these words: if they don't clearly make sense, ask.)")
    if recent:
        user.append(f"Recent:\n{recent}")
    user.append(f"Screen now:\n{screen}")
    if shortcuts:
        user.append(f"Shortcuts here: {shortcuts}")
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
