"""Pop-up forms a site throws over the page ("Student Feedback Form" on PW, surveys, newsletters): found and
closed in code, no AI, no screenshot.

A pop-up is spotted by its heading (read through UI Automation, ~0.05 s). Its close button often has no
name (PW's X is an unnamed picture), so it's found through the page's structure: the smallest box around
the heading that also holds a small unnamed or "Close" control above/level with the heading, on its right.
Esc is the fallback. Closing is always checked: the heading must be gone afterwards.

Filling in or submitting a form is never done here: that's the user's call (the agent asks them).
"""

import logging
import re
import time
from dataclasses import dataclass

import win32gui
from _ctypes import COMError

from . import desktop
from . import mouse as jmouse

log = logging.getLogger(__name__)

# Headings that mean "a site's pop-up form", not the page's own content.
TITLES = re.compile(r"\b(feedback form|feedback|survey|rate (?:us|your)|how (?:was|would you rate)|newsletter|"
                    r"subscribe to|sign up for|your opinion)\b", re.I)
_CLOSE_NAMES = re.compile(r"^(|x|×|✕|close|close dialog|close modal|dismiss|skip|not now|no thanks|maybe later|cancel)$",
                          re.I)
# Notices that only get in the way (PW's "Milestone Achieved" streak screen, 30 Sep): closed without asking.
NOTICES = re.compile(r"^(milestone achieved|a fresh streak is blooming.*|you'?re on a \d+.day streak.*|what'?s new)$", re.I)
MAX_BUTTON = 64   # px: a close button is small
MAX_LEVELS = 8    # how far up from the heading to look for the box around it


@dataclass
class Popup:
    title: str
    rect: tuple[int, int, int, int]
    element: object = None


def _rect(e) -> tuple[int, int, int, int]:
    r = e.CurrentBoundingRectangle
    return r.left, r.top, r.right, r.bottom


def is_notice(title: str) -> bool:
    """A notice (close it, no need to ask), not a form (the user decides)."""
    return bool(NOTICES.match(title or ""))


def find(hwnd: int | None = None) -> Popup | None:
    """The pop-up open in the front window, or None: a form's heading, or a notice's text (~0.03 s)."""
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd or win32gui.GetForegroundWindow())
    texts = root.FindAll(UIA.TreeScope_Descendants,
                         uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_TextControlTypeId))
    first_form = None
    for i in range(texts.Length):
        try:
            e = texts.GetElement(i)
            name = " ".join((e.CurrentName or "").split())
            if not name or len(name) > 80:
                continue
            notice = NOTICES.match(name)
            form = TITLES.search(name) and e.CurrentLocalizedControlType == "heading"
            if (form or notice) and not e.CurrentIsOffscreen:
                l, t, r, b = _rect(e)
                if r - l > 4 and b - t > 4:
                    if notice:
                        # 3 Oct: PW's streak screen sat on top of the feedback form; the form was "closed"
                        # (its X is under the notice) and failed. A notice is on top: it goes first.
                        return Popup(name, (l, t, r, b), e)
                    first_form = first_form or Popup(name, (l, t, r, b), e)
        except COMError:
            continue  # the page changed while it was read (the pop-up just closed)
    return first_form


def title() -> str:
    """For the agent's snapshot: the pop-up's heading, or ""."""
    p = find()
    return p.title if p else ""


def _close_button(popup: Popup):
    UIA, uia = desktop._uia()
    walker = uia.ControlViewWalker
    kinds = [UIA.UIA_ButtonControlTypeId, UIA.UIA_ImageControlTypeId, UIA.UIA_HyperlinkControlTypeId]
    cond = None
    for k in kinds:
        c = uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, k)
        cond = c if cond is None else uia.CreateOrCondition(cond, c)
    hl, ht, hr, hb = popup.rect
    box = popup.element
    for _ in range(MAX_LEVELS):
        box = walker.GetParentElement(box)
        if not box:
            return None
        found = box.FindAll(UIA.TreeScope_Descendants, cond)
        best = None
        for i in range(found.Length):
            try:
                e = found.GetElement(i)
                if e.CurrentIsOffscreen:
                    continue
                l, t, r, b = _rect(e)
                name = " ".join((e.CurrentName or "").split())
            except COMError:
                continue
            if not (4 <= r - l <= MAX_BUTTON and 4 <= b - t <= MAX_BUTTON) or not _CLOSE_NAMES.match(name):
                continue
            # Above or level with the heading, and to the right of its middle: where an X sits.
            if t < hb and (l + r) / 2 > (hl + hr) / 2:
                score = r - t  # the top-right-most
                if best is None or score > best[0]:
                    best = (score, (l, t, r, b), name)
        if best:
            return best[1], best[2]
    return None


def _gone(want: str, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            p = find()
        except COMError:
            p = Popup(want, (0, 0, 0, 0))  # mid-change: look again
        if not p or p.title != want:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def close() -> str:
    popup = find()
    if not popup:
        return "The pop-up is already closed."  # nothing to do is not a failure (30 Sep: a plan closed it twice)
    button = _close_button(popup)
    if button:
        (l, t, r, b), name = button
        sw, sh = jmouse.screen_size()
        x, y = (l + r) // 2, (t + b) // 2
        log.info("Closing pop-up %r with its close button %r at %s", popup.title, name, (x, y))
        jmouse.click(x / (sw - 1) * 1000, y / (sh - 1) * 1000, "left", False)
        if _gone(popup.title):
            return f"Closed the {popup.title}."
    from . import keys
    log.info("Closing pop-up %r with Esc", popup.title)
    keys.press("esc")
    if _gone(popup.title, 1.5):
        return f"Closed the {popup.title}."
    return f"Not done: the {popup.title} is still open. I couldn't find its close button."
