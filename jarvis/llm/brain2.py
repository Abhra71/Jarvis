"""The new brain, end to end: understand the sentence (the proven model chain), do it (the executor and the
existing hands), and answer like a person. Built next to the old brain; switched on in Phase 1's live check.

    brain = NewBrain(skills)
    route, reply = brain.handle("close all the youtube tabs")

- act: the steps run in order; the reply is the brain's short "say" when every step happened, else the hands' own
  reason in plain words. A step that needs the user's yes (delete, send, buy, post) is asked about, and done after
  "yes" (kept for one answer only).
- ask / chat / refuse: the brain's sentence is the reply.
- ignore: no reply at all (None): room talk, songs and noise get silence.
- control: stop/yes/no/cancel; coding_on/off are reported so the assistant switches mode.
- code: handed back to the assistant (route "code"), which runs the coding expert on the open editor.
"""

import logging

from ..skills import desktop, elements
from . import act
from . import understand as U
from .router import Router

log = logging.getLogger(__name__)

_FALLBACK_CHAIN = {"understand": ["groq:qwen/qwen3.8-27b", "gemini:gemini-3.5-flash-lite",
                                  "nvidia:nvidia/nemotron-3-super-120b-a12b"]}


def screen_text(max_items: int = 30) -> str:
    """The screen as the brain reads it: the front window and its named items (nothing while a secrets file is in
    front)."""
    front = desktop.front_window()
    from ..skills import files
    if files.is_secret(front):
        return f"front: {front} (a secrets file: its contents are not read)"
    try:
        items = "; ".join(e.label() for e in elements.read_front()[:max_items])
    except Exception:
        items = ""
    return f"front: {front}" + (f". Items: {items}" if items else "")


class NewBrain:
    def __init__(self, skills, router: Router | None = None, profile: str = "", screen=screen_text):
        self.skills = skills
        self.router = router or Router()
        if not self.router.chains.get("understand"):
            self.router.chains.update(_FALLBACK_CHAIN)
        self.profile = profile
        self.screen = screen
        self.history: list[str] = []
        self.pending: list[dict] | None = None   # steps waiting for the user's yes
        self.pending_what = ""
        self.last_meaning: dict | None = None

    def handle(self, text: str, unsure: bool = False, coding: bool = False) -> tuple[str, str | None]:
        screen = self.screen()
        meaning, replies = self.router.run(
            "understand", lambda model: U.understand(model, text, screen, self.history[-2:], unsure, self.profile,
                                                     coding, timeout=8.0))
        self.history.append(text)
        self.last_meaning = meaning
        if meaning is None:
            why = replies[-1].error if replies else "no model available"
            log.warning("Nobody understood %r (%s)", text, why)
            return "brain2", "Sorry, I couldn't think just now. Please say that again."
        kind = meaning.get("kind")
        log.info("Understood %r as %s via %s", text, U.as_text(meaning)[:200],
                 [f"{r.model}:{r.error or 'ok'}" for r in replies])
        if kind == "control":
            return self._control(meaning.get("control", ""))
        if self.pending is not None:
            self.pending = None  # anything else than yes/no drops the waiting action
        if kind == "ignore":
            return "ignored", None
        if kind in ("ask", "chat", "refuse"):
            return "brain2", str(meaning.get("say") or "Sorry?")
        if kind == "code":
            return "code", str(meaning.get("code") or text)
        if kind == "act":
            return self._act(meaning.get("steps") or [], str(meaning.get("say") or "Done."))
        return "brain2", "Sorry, I didn't get that."

    def _act(self, steps: list[dict], say: str) -> tuple[str, str]:
        ok, said = act.run(steps, self.skills, desktop.front_window())
        if ok:
            return "brain2", say
        last = said[-1] if said else "That didn't happen."
        if last.startswith("Needs confirmation"):
            self.pending = steps
            what = last.split("this would", 1)[-1].split(".")[0].strip() or "do that"
            self.pending_what = what
            return "brain2", f"Should I {what}? Say yes to go ahead."
        return "brain2", _plain(last)

    def _control(self, control: str) -> tuple[str, str | None]:
        if control == "yes" and self.pending:
            steps, self.pending = self.pending, None
            self.skills.confirmed = True
            try:
                ok, said = act.run(steps, self.skills, desktop.front_window())
            finally:
                self.skills.confirmed = False
            return "brain2", "Done." if ok else _plain(said[-1] if said else "That didn't happen.")
        if control in ("no", "cancel") and self.pending:
            self.pending = None
            return "brain2", "Okay, I left it."
        if control in ("coding_on", "coding_off", "stop", "undo", "redo", "yes", "no", "cancel"):
            return "control", control
        return "brain2", "Okay."


def _plain(text: str) -> str:
    """The hands' reason as a sentence for the user ('Not clicked: Nothing called X is on screen.' ->
    'I couldn't find X on the screen.')."""
    t = text.strip()
    for prefix in ("Not done: ", "Not clicked: "):
        if t.startswith(prefix):
            t = t[len(prefix):]
    if t.startswith("Nothing called "):
        name = t[len("Nothing called "):].split(" is on screen")[0].strip("'\"")
        return f"I couldn't find {name} on the screen."
    return t[0].upper() + t[1:] if t else "That didn't happen."
