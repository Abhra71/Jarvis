"""'Did that step work?': a check attached to a step, tested in code against a fresh snapshot.

Written the way the AI writes them in a plan, "kind: value", optionally "not kind: value":
    window: WhatsApp          the front window's app or title has "WhatsApp"
    open: Visual Studio Code  some open window has it
    closed: YouTube           a window with it closed (fewer than before, or none left)
    element: Search           a named item (button/link/field…) is on screen
    text: Mom                 visible anywhere: item names, the title, or the OCR text
    focus: field              the keyboard focus is in something you can type into
    url: youtube.com/watch    the front tab's address has it
    playing / paused          media (any app's video or music) is playing / paused
    fullscreen / not fullscreen
    dialog / not dialog       a dialog box is open in front
Text only, never a screenshot. Apps take a moment to open, so run.py polls a check for a short while.

A check proves a step worked only if it CHANGED because of the step. One that was already true before
(29 Sep: "press F" checked "window: PW Video Player", true before and after) proves nothing, so the
step counts as unconfirmed and Jarvis doesn't claim it worked. Some steps get a better check from code
than the AI's guess (auto_check): keys that toggle full screen or play/pause, closing windows.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..skills import elements
from .context import Snapshot

KINDS = ("window", "open", "closed", "element", "text", "focus", "url", "playing", "paused", "fullscreen",
         "dialog")
_NO_VALUE = ("playing", "paused", "fullscreen", "dialog")
_ALIASES = {"title": "window", "front": "window", "app": "window", "item": "element", "button": "element",
            "link": "element", "field": "element", "visible": "text", "shows": "text", "address": "url",
            "gone": "closed", "full screen": "fullscreen", "full_screen": "fullscreen", "play": "playing",
            "pause": "paused", "media": "playing"}
_TYPABLE = {"field", "document", "dropdown"}


def _bare_url(u: str) -> str:
    """'https://www.chess.com/' -> 'chess.com': the parts a site adds or drops on its own."""
    return re.sub(r"^(https?:)?/*(www\.)?", "", u.strip()).rstrip("/")


class BadCheck(ValueError):
    pass


@dataclass(frozen=True)
class Check:
    kind: str
    value: str = ""
    negate: bool = False

    def __str__(self):
        v = f": {self.value}" if self.value else ""
        return f"{'not ' if self.negate else ''}{self.kind}{v}"


def parse(expect) -> Check | None:
    """'window: WhatsApp' / {'window': 'WhatsApp'} / 'playing' / '' -> Check or None. Raises BadCheck."""
    if expect is None or expect == "" or expect == {}:
        return None
    if isinstance(expect, dict):
        if len(expect) != 1:
            raise BadCheck(f"one check per step, got {expect}")
        (kind, value), = expect.items()
        expect = f"{kind}: {value}" if value not in (True, None, "") else kind
    text = str(expect).strip()
    m = re.fullmatch(r"(not\s+)?([a-z_ ]+?)(?:\s*[:=]\s*(.*?))?\s*", text, re.I | re.S)
    if not m:
        raise BadCheck(f"checks look like 'window: WhatsApp', got {expect!r}")
    kind = m.group(2).lower().strip()
    kind = _ALIASES.get(kind, kind)
    negate = bool(m.group(1))
    if kind not in KINDS:
        raise BadCheck(f"unknown check {kind!r}; use one of {', '.join(KINDS)}")
    value = (m.group(3) or "").strip().strip("\"'")
    if kind in _NO_VALUE:
        if kind == "paused":
            kind, negate = "playing", not negate
        return Check(kind, "", negate)
    if not value:
        raise BadCheck("a check needs a value")
    return Check(kind, value, negate)


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _has(haystack: str, needle: str) -> bool:
    """Case-insensitive 'contains', forgiving small spelling differences ("Whatsapp" vs "WhatsApp Beta")."""
    h, n = _norm(haystack), _norm(needle)
    if not n:
        return False
    if n in h or n.replace(" ", "") in h.replace(" ", ""):
        return True
    return len(n) >= 4 and fuzz.partial_ratio(n, h) >= 88


_WINDOW_ALIASES = {"vs code": "visual studio code", "file explorer": "explorer", "explorer": "file explorer",
                   "chrome": "google chrome", "edge": "microsoft edge"}


def _window_has(w: str, value: str) -> bool:
    """'code: main.cpp - Visual Studio Code' has 'vs code', 'visual studio code' and 'code'."""
    alias = _WINDOW_ALIASES.get(value.lower())
    return _has(w, value) or bool(alias and _has(w, alias))


def _count(snap: Snapshot, value: str) -> int:
    return sum(_window_has(w, value) for w in snap.windows)


def _holds(c: Check, snap: Snapshot, before: Snapshot | None) -> bool:
    v = c.value
    if c.kind == "window":
        return _window_has(snap.front, v)
    if c.kind == "open":
        return _count(snap, v) > 0
    if c.kind == "closed":
        now = _count(snap, v)
        # "Close it" with two Chrome windows open closes one: that's success (29 Sep it said "stuck").
        return now == 0 or (before is not None and now < _count(before, v))
    if c.kind == "element":
        el, why = elements.match(snap.items, v)
        return el is not None or why.startswith("More than one")
    if c.kind == "text":
        if _has(snap.front, v) or any(_has(el.name, v) for el in snap.items):
            return True
        return any(_has(line, v) for line in snap.ocr)  # pixels last: only when the names don't have it
    if c.kind == "focus":
        want = _norm(v)
        return snap.focus in _TYPABLE if want in ("field", "edit", "text box", "typable", "input") else snap.focus == want
    if c.kind == "url":
        return _has(_bare_url(snap.url or ""), _bare_url(v))
    if c.kind == "playing":
        return snap.playing is True
    if c.kind == "fullscreen":
        return snap.fullscreen
    if c.kind == "dialog":
        return bool(snap.dialog)
    return False


def holds(c: Check, snap: Snapshot, before: Snapshot | None = None) -> bool:
    if c.kind == "closed" and c.negate:
        return not _holds(Check("closed", c.value), snap, None)
    return _holds(c, snap, before) != c.negate


def proves_nothing(c: Check, before: Snapshot) -> bool:
    """Was it already true before the step? Then it can't show that the step did anything."""
    if c.kind == "closed" and not c.negate:
        return _count(before, c.value) == 0  # nothing to close in the first place
    return holds(c, before)


# ---- better checks from code -----------------------------------------------------------

_SELF_CHECKED_ABILITIES = {"snap_left", "snap_right", "maximize_front", "minimize_front"}
_FULLSCREEN_KEYS = {"f", "f11"}
_PLAY_KEYS = {"k", "space", "spacebar", "playpause", "play_pause"}


def too_vague(c: Check) -> bool:
    """A check almost anything passes can't prove a step worked (30 Sep: "url: https://" after a Google
    search let the plan claim a Physics Wallah page was open)."""
    v = _norm(c.value)
    if c.kind == "url":
        v = re.sub(r"^(https?:)?/*(www\.)?", "", v).strip("/. ")
        return len(v) < 3
    if c.kind in ("text", "element", "window", "open", "closed"):
        return len(v) < 2
    return False


def auto_check(tool: str, args: dict, check: Check | None, before: Snapshot) -> Check | None:
    """The check to use for this step: code knows better than the AI for some steps, and some AI checks
    can never prove anything (checking for the very item just clicked, guessing a label after a key)."""
    key = str(args.get("key", "")).strip().lower() if tool == "press_key" else ""
    yt = _norm(args.get("command", "")) if tool == "youtube" else ""
    media = str(args.get("action", "")) if tool == "media" else ""
    # The YouTube pack treats these as goals ("be in full screen", "be paused"): it does nothing if already so.
    if re.search(r"\bfull ?screen\b", yt):
        return Check("fullscreen", "", bool(re.search(r"\b(exit|leave|close)\b", yt)))
    m = re.fullmatch(r"(pause|stop|play|resume|unpause|continue)( (it|this|the video|video|youtube))?", yt or "-")
    if m:
        return Check("playing", "", m.group(1) in ("pause", "stop"))
    # A bare key or media button flips the state.
    if key in _FULLSCREEN_KEYS:
        return Check("fullscreen", "", before.fullscreen)
    if (key in _PLAY_KEYS or media == "play_pause") and before.playing is not None:
        return Check("playing", "", bool(before.playing))  # playing -> paused, paused -> playing
    if tool == "window" and args.get("action") in ("close", "close_all") and args.get("app"):
        return Check("closed", str(args["app"]))
    if tool == "youtube" or (tool == "do" and args.get("ability") in _SELF_CHECKED_ABILITIES):
        # These check their own result in code (the pack reads the player; snapping checks where the window
        # went). An AI guess on top only adds false failures (30 Sep: "text: Chrome snapped left").
        return None
    if check is None or too_vague(check):
        return None
    if tool == "web_search" and check.kind == "url" and "search" not in check.value.lower():
        return None  # a guessed site (30 Sep: "www.clawedgame.com" after a Google search): proves nothing
    if tool == "click_element" and check.kind == "element" and not check.negate \
            and _norm(check.value) == _norm(args.get("name", "")):
        return None  # "click Cancel, expect Cancel" (29 Sep): the thing clicked isn't the result
    if tool in ("press_key", "type_text") and check.kind in ("text", "element") and not check.negate:
        return None  # a guessed label ("text: Playing", "text: commented") after keys: not evidence
    if tool in ("scroll", "find_on_page") and check.kind in ("text", "element") and not check.negate:
        try:
            if holds(check, before):
                # 3 Oct: "Scroll down" checked "text: CH - 04 Sound", the item clicked just before: scrolling moved
                # it off screen, so a scroll that worked was called stuck. Something already in view proves nothing.
                return None
        except Exception:
            return None
    return check


def explain(c: Check, snap: Snapshot) -> str:
    """Why it failed, in plain words: spoken to the user when stuck, and given to the repair call."""
    v = c.value
    front = (snap.front or "nothing").split(":", 1)[0]
    if c.kind == "playing":
        return "the media is still playing." if c.negate else "nothing started playing."
    if c.kind == "fullscreen":
        return "it's still in full screen." if c.negate else "it didn't go full screen."
    if c.kind == "dialog":
        return f"the dialog box {snap.dialog!r} is still open." if c.negate else "no dialog box opened."
    if c.negate:
        return f"{v} is still there."
    return {
        "window": f"{v} isn't in front; {front} is.",
        "open": f"{v} didn't open.",
        "closed": f"{v} is still open.",
        "element": f"I can't see {v} on screen in {front}.",
        "text": f"I can't see {v} on screen in {front}.",
        "focus": "the cursor isn't in a text box.",
        "url": f"the page isn't {v}; it's {snap.url or 'not a web page'}.",
    }.get(c.kind, f"{c} didn't come true.")
