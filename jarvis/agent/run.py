"""The agent loop for one request: plan → do a step → check it → next; one repair; then one clear question.

Every step goes through Skills.call, so all the existing safety holds: the action budget covers the whole
plan, VMware and secrets files are off-limits, and send/buy/delete need a spoken yes. When a step needs
that yes, the plan pauses there, Jarvis asks, and a "yes" resumes it from that step.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from ..skills import LAUNCHES, request_parts, shortcuts
from . import checks
from .context import Memory, Readers, take
from .plan import (LOOK_AGAIN, NeedsEyes, Plan, PlanError, PlanMemory, Step, code_plan, continue_prompt, parse, site_hints,
                   planning_prompt, repair_prompt)

log = logging.getLogger(__name__)

# How long a check may take to come true: apps and pages need a moment to appear.
WAIT_LAUNCH = 5.0
WAIT_STEP = 1.5
POLL = 0.25
SETTLE = 0.6      # before a look_again: let the page finish changing
MAX_LOOKS = 3     # look_agains per request (each is one quick AI call)
PENDING_MINUTES = 5

_FAILURE_STARTS = ("error", "not allowed", "not done", "not clicked", "unknown", "no ", "i couldn't", "i don't",
                   "sorry", "i can only")
_FAILURE_WORDS = ("doesn't exist", "isn't a", "couldn't find", "won't overwrite", "already exists", "don't see",
                  "may not have worked", "isn't on screen", "nothing called")
# Their own result sentence doesn't prove anything happened on screen: without a real check they're unconfirmed.
_UNCHECKABLE = {"press_key", "type_text", "click_element", "media", "browser", "find_on_page"}
_KEYS_TO_PAGE = {"press_key", "type_text", "youtube", "media", "browser", "find_on_page"}
_ARG_OBJECTS = ("name", "app", "path", "url", "query", "source")  # what "it" means after a step


def looks_failed(result: str) -> bool:
    r = str(result).strip().lower()
    return r.startswith(_FAILURE_STARTS) or any(w in r for w in _FAILURE_WORDS)


@dataclass
class Pending:
    """A plan paused before a step that needs the user's yes."""
    request: str
    steps: list[Step]
    reply: str
    when: float = field(default_factory=time.monotonic)


@dataclass
class Outcome:
    """One line per task in the log (and for the task suite): what happened, how fast, how many AI calls."""
    request: str
    source: str = ""
    steps: int = 0
    ai_calls: int = 0
    seconds: float = 0.0
    result: str = ""   # done | asked | needs_yes | stuck | fallback
    detail: str = ""

    def line(self) -> str:
        return (f"Agent task: {self.result} | {self.request!r} | plan by {self.source or '-'} | {self.steps} steps | "
                f"{self.ai_calls} AI calls | {self.seconds:.1f}s{' | ' + self.detail if self.detail else ''}")


def out_t0(out) -> float:
    return getattr(out, "t0", 0.0)


def _ask_for_yes(result: str) -> str:
    """'Needs confirmation: this would click 'Send'. …' -> 'Shall I click Send?'"""
    m = re.search(r"this would (.+?)\. Nothing was done", result)
    risk = m.group(1) if m else "do that"
    if "sends the message" in risk:
        return "Your message is ready. Shall I send it?"
    click = re.match(r"click '(.+)'", risk)
    if click:
        return f"Shall I click {click.group(1)}?"
    return f"Shall I {risk}?"


class Agent:
    def __init__(self, skills, think: Callable[[str, str], str] | None, narrate: Callable[[str], None] = None,
                 readers: Readers | None = None, memory: PlanMemory | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.skills = skills
        self.think = think              # think(system, user) -> the AI's text (JSON); raises if no AI
        self.narrate = narrate or (lambda text: None)
        self.readers = readers
        self.memory = memory if memory is not None else PlanMemory()
        self.sleep, self.clock = sleep, clock
        self.context = Memory()
        self.pending: Pending | None = None
        self.last: Outcome | None = None

    @property
    def tools(self) -> dict:
        return self.skills.tools

    def _snap(self):
        return take(self.readers)

    def _think(self, out: Outcome, system: str, user: str) -> str:
        out.ai_calls += 1
        return self.think(system, user)

    # ---- one request -----------------------------------------------------------

    def run(self, text: str, unsure: bool = False) -> str | None:
        """The spoken reply, or None to let the old (seeing) loop handle this request."""
        out = Outcome(text)
        t0 = out.t0 = self.clock()
        try:
            reply = self._run(text, unsure, out)
        finally:
            out.seconds = self.clock() - t0
            self.last = out
            log.info(out.line())
        return reply

    def _run(self, text: str, unsure: bool, out: Outcome) -> str | None:
        snap = self._snap()
        plan = code_plan(text, snap.front, unsure) or (None if unsure else self.memory.get(text, self.tools))
        log.info("Plan from %s ready after %.2fs", plan.source if plan else "the AI (asking)", self.clock() - out_t0(out))
        if not plan:
            if not self.think:
                out.result = "fallback"
                return None
            system, user = planning_prompt(text, self.tools, snap.text(), self.context.text(),
                                           shortcuts.for_window(snap.front, text), unsure)
            try:
                plan = self._plan(out, system, user)
            except NeedsEyes as e:
                out.result, out.detail = "fallback", f"needs eyes ({e})"
                return None
            except PlanError as e:
                out.result, out.detail = "fallback", f"no usable plan ({e})"
                return None
        out.source = plan.source
        if plan.source in ("ai", "memory") and plan.steps and plan.steps[-1].tool in ("open_website", "open_app", "address_bar") \
                and site_hints(text) and len(request_parts(text)) > 1:
            # "Open PW, my batch, chemistry": the AI tends to stop at the front door (30 Sep); look and go on.
            plan.steps.append(Step(LOOK_AGAIN, {}))
        if not plan.steps:
            out.result = "asked" if plan.ask else "done"
            return plan.ask or plan.reply
        return self._execute(text, plan, out, unsure=unsure)

    def _plan(self, out: Outcome, system: str, user: str) -> Plan:
        raw = self._think(out, system, user)
        try:
            return parse(raw, self.tools)
        except PlanError as e:
            # A slip in the JSON or a wrong tool name: one more try, with the reason.
            log.info("Plan not usable (%s); asking once more", e)
            raw = self._think(out, system, f"{user}\n(Your last answer wasn't usable: {e}. Answer again, JSON only, "
                                               "with tools from the list.)")
            return parse(raw, self.tools)

    # ---- doing and checking ----------------------------------------------------------

    def _execute(self, request: str, plan: Plan, out: Outcome, repaired: bool = False,
                 remember: bool = True, unsure: bool = False) -> str:
        steps, done, executed, results, narrated, looks, i = list(plan.steps), [], [], [], 0, 0, 0
        unconfirmed: list[str] = []  # what was done but couldn't be checked: never claimed as a success
        last_seen = False            # the last step's result was SEEN on screen (a check that changed)
        reply = plan.reply
        while i < len(steps):
            step = steps[i]
            if step.tool == LOOK_AGAIN:
                # Like a person: the page changed, so look (as text) and decide the next clicks from what's there.
                looks += 1
                if looks > MAX_LOOKS or not self.think:
                    return self._stuck(out, executed, "it's taking too many steps to find the way.")
                snap = self._settled()
                system, user = continue_prompt(request, self.tools, done, snap.text(),
                                               shortcuts.for_window(snap.front, request))
                try:
                    more = parse(self._think(out, system, user), self.tools)
                except NeedsEyes:
                    return self._stuck(out, executed, "the next part needs me to see pictures on the screen.")
                except PlanError as e:
                    return self._stuck(out, executed, "I couldn't work out the next step.", str(e))
                if more.ask and not more.steps:
                    out.steps, out.result = len(executed), "asked"
                    return more.ask
                steps = steps[:i] + more.steps
                reply = more.reply or reply
                continue
            if step.say and len(steps) > 1 and narrated < 2:
                narrated += 1
                self.narrate(step.say)
            t_step = self.clock()
            before = self._snap()
            why = self._blocked_by_dialog(step, before)
            # Decide the check and read what it needs NOW, before the step changes the screen.
            check = checks.auto_check(step.tool, step.args, step.check, before)
            already = check is not None and checks.proves_nothing(check, before)
            result = ""
            if why is None:
                result = self.skills.call(step.tool, step.args)
                if isinstance(result, dict):
                    result = result.get("text", "")
                result = str(result)
                if result.startswith("Needs confirmation"):
                    self.pending = Pending(request, steps[i:], reply)
                    out.steps, out.result = len(executed), "needs_yes"
                    return _ask_for_yes(result)
                if looks_failed(result):
                    why = result
                else:
                    why, confirmed = self._verify(step, check, already, before)
                    if why is None and not confirmed:
                        unconfirmed.append(result)
                    last_seen = why is None and check is not None and not already
            log.info("Step %d: %s -> %s (%.2fs%s)", len(executed) + 1, step.label(), (result or why or "")[:80],
                     self.clock() - t_step, "" if why is None else ", FAILED")
            if why is None:
                executed.append(step)
                results.append(result)
                done.append(f"{step.label()} -> {result}")
                self._note_object(step)
                i += 1
                continue
            log.info("Step %s failed: %s", step.label(), why)
            if plan.source == "memory":
                self.memory.forget(request)  # it worked before but not now: re-learned below if the repair works
            if repaired or not self.think:
                return self._stuck(out, executed, why)
            repaired = True
            snap = self._snap()
            system, user = repair_prompt(request, self.tools, done, step.label(), why, snap.text(),
                                         shortcuts.for_window(snap.front, request))
            try:
                fix = parse(self._think(out, system, user), self.tools)
            except (PlanError, NeedsEyes) as e:
                return self._stuck(out, executed, why, f"repair: {e}")
            # The same failed step again is not a repair (29 Sep: "click Google Chrome" twice).
            while fix.steps and fix.steps[0].tool == step.tool and fix.steps[0].args == step.args:
                fix.steps.pop(0)
            if not fix.steps:
                out.steps, out.result, out.detail = len(executed), "asked", why
                return fix.ask or self._stuck(out, executed, why)
            steps = steps[:i] + fix.steps
            reply = fix.reply or reply
        out.steps = len(executed)
        if unconfirmed:
            # Done, but not seen to work: say what was done, not what the plan hoped for (29 Sep: "Video resumed
            # in fullscreen" was said after two unchecked key presses, and neither had worked).
            out.result, out.detail = "unconfirmed", "; ".join(unconfirmed)
            said = " ".join(r if r.endswith((".", "!", "?")) else r + "." for r in unconfirmed[-2:])
            return f"{said} I couldn't confirm it worked on screen."
        out.result = "done"
        if remember and not unsure and last_seen and plan.source != "code" and (plan.source == "ai" or repaired):
            self.memory.learn(request, executed, reply)
        # Code plans have no written reply: say what each step reported ("Playing Lofi Girl. Full screen.").
        # (Leaving out "Switched to Chrome." when it was only on the way to something else.)
        said = [r for s, r in zip(executed, results) if not (s.tool == "window" and s.args.get("action") == "focus")]
        facts = " ".join((said or results)[-3:]) or "Done."
        if reply and not last_seen and plan.source != "code":
            # The AI's summary is a claim about the goal; say it only when the last step was seen to work.
            # 30 Sep: after a Google search it said "Opened the Physics Wallah chemistry batch page."
            log.info("Not saying the plan's reply %r: the last step wasn't seen to work", reply)
            return facts
        return reply or facts

    def _settled(self, max_wait: float = 6.0):
        """The screen once the page has loaded and stopped changing: named items there, and the same ones twice
        in a row. 30 Sep: a look right after opening PW saw only Chrome's toolbar and clicked "Tab search"."""
        self.sleep(SETTLE)
        deadline = self.clock() + max_wait
        snap, last = self._snap(), None
        while self.clock() < deadline:
            names = [el.name for el in snap.items]
            if names and names == last:
                break
            last = names
            self.sleep(0.4)
            snap = self._snap()
        return snap

    def _blocked_by_dialog(self, step: Step, before) -> str | None:
        """Keys typed while a dialog box is open go to the dialog, not the page (29 Sep: F and Space were
        pressed behind a site's pop-up, and nothing happened)."""
        if step.tool not in _KEYS_TO_PAGE:
            return None
        key = str(step.args.get("key", "")).lower()
        if step.tool == "press_key" and key in ("enter", "esc", "escape", "tab", "shift+tab", "alt+f4"):
            return None  # answering the dialog itself
        if before.dialog:
            return f"A dialog box is open in front ({before.dialog}); it has to be answered first."
        return None

    def _verify(self, step: Step, check, already: bool, before) -> tuple[str | None, bool]:
        """(why it failed or None, confirmed). Confirmed only if the check came true BECAUSE of the step."""
        if check is None:
            return None, step.tool not in _UNCHECKABLE
        if already:
            # Already true before the step: it can't show the step did anything.
            return None, step.tool not in _UNCHECKABLE
        wait = WAIT_LAUNCH if step.tool in LAUNCHES or step.tool in ("web_search", "address_bar", "site_search")             else WAIT_STEP
        deadline = self.clock() + wait
        while True:
            snap = self._snap()
            if checks.holds(check, snap, before):
                return None, True
            if self.clock() >= deadline:
                return checks.explain(check, snap), False
            self.sleep(POLL)

    def _stuck(self, out: Outcome, executed: list, why: str, extra: str = "") -> str:
        out.steps, out.result, out.detail = len(executed), "stuck", why + (f" / {extra}" if extra else "")
        return f"I'm stuck: {self._spoken(why)} What should I do?"

    @staticmethod
    def _spoken(why: str) -> str:
        why = re.sub(r"^(Not done|Not clicked|Not allowed|Error):\s*", "", why.strip())
        why = why.split(" Current items:")[0]  # never read out a whole list of screen items
        return why if why.endswith((".", "?", "!")) else why + "."

    def _note_object(self, step: Step):
        for key in _ARG_OBJECTS:
            if step.args.get(key):
                self.context.it = str(step.args[key])
                return

    # ---- the yes/no after a paused plan ----------------------------------------------

    def has_pending(self) -> bool:
        if self.pending and self.clock() - self.pending.when > PENDING_MINUTES * 60:
            self.pending = None
        return self.pending is not None

    def resume(self) -> str:
        """The user said yes: carry on from the paused step (Skills.confirmed is set for this turn)."""
        p, self.pending = self.pending, None
        out = Outcome(p.request + " (yes)", source="resumed")
        t0 = self.clock()
        try:
            return self._execute(p.request, Plan(p.steps, p.reply, source="resumed"), out, repaired=True,
                                 remember=False)
        finally:
            out.seconds = self.clock() - t0
            self.last = out
            log.info(out.line())

    def drop_pending(self):
        self.pending = None

    def heard(self, said: str, reply: str):
        """Every exchange, whoever handled it, so "it" and "that" make sense in the next request."""
        self.context.add(said, reply)
