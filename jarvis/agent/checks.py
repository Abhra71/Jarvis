"""'Did that step work?': a check the plan attaches to a step, tested in code against a fresh snapshot.

Written the way the AI writes them in a plan, "kind: value", optionally "not kind: value":
    window: WhatsApp          the front window's app or title has "WhatsApp"
    open: Visual Studio Code  some open window has it
    closed: YouTube           no open window has it
    element: Search           a named item (button/link/field…) is on screen
    text: Mom                 visible anywhere: item names, the title, or the OCR text
    focus: field              the keyboard focus is in something you can type into
    url: youtube.com/watch    the front tab's address has it
Text only, never a screenshot. Apps take a moment to open, so run.py polls a check for a short while.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..skills import elements
from .context import Snapshot

KINDS = ("window", "open", "closed", "element", "text", "focus", "url")
_ALIASES = {"title": "window", "front": "window", "app": "window", "item": "element", "button": "element",
            "link": "element", "field": "element", "visible": "text", "shows": "text", "address": "url",
            "gone": "closed"}
_TYPABLE = {"field", "document", "dropdown"}


class BadCheck(ValueError):
    pass


@dataclass(frozen=True)
class Check:
    kind: str
    value: str
    negate: bool = False

    def __str__(self):
        return f"{'not ' if self.negate else ''}{self.kind}: {self.value}"


def parse(expect) -> Check | None:
    """'window: WhatsApp' / {'window': 'WhatsApp'} / '' -> Check or None. Raises BadCheck."""
    if expect is None or expect == "" or expect == {}:
        return None
    if isinstance(expect, dict):
        if len(expect) != 1:
            raise BadCheck(f"one check per step, got {expect}")
        (kind, value), = expect.items()
        expect = f"{kind}: {value}"
    m = re.fullmatch(r"\s*(not\s+)?([a-z_ ]+?)\s*[:=]\s*(.+?)\s*", str(expect), re.I | re.S)
    if not m:
        raise BadCheck(f"checks look like 'window: WhatsApp', got {expect!r}")
    kind = m.group(2).lower().strip()
    kind = _ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise BadCheck(f"unknown check {kind!r}; use one of {', '.join(KINDS)}")
    value = m.group(3).strip().strip("\"'")
    if not value:
        raise BadCheck("a check needs a value")
    return Check(kind, value, bool(m.group(1)))


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


def _window_has(w: str, value: str) -> bool:
    """'code: main.cpp - Visual Studio Code' has 'vs code', 'visual studio code' and 'code'."""
    aliases = {"vs code": "visual studio code", "file explorer": "explorer", "explorer": "file explorer",
               "chrome": "google chrome", "edge": "microsoft edge"}
    return _has(w, value) or (value.lower() in aliases and _has(w, aliases[value.lower()]))


def _holds(c: Check, snap: Snapshot) -> bool:
    v = c.value
    if c.kind == "window":
        return _window_has(snap.front, v)
    if c.kind in ("open", "closed"):
        found = any(_window_has(w, v) for w in snap.windows)
        return found if c.kind == "open" else not found
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
        return _has(snap.url or "", v)
    return False


def holds(c: Check, snap: Snapshot) -> bool:
    return _holds(c, snap) != c.negate


def explain(c: Check, snap: Snapshot) -> str:
    """Why it failed, in plain words: spoken to the user when stuck, and given to the repair call."""
    v = c.value
    front = (snap.front or "nothing").split(":", 1)[0]
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
