"""The screen as text: what's clickable in the front window, read through Windows UI Automation.

Instead of a screenshot (4–6 s round trips, pixel guesses), the AI gets a short list like
    [1] button "No thanks"   [2] link "Play Bots"   [3] field "Search"
and clicks by id or name. Reading takes ~0.03–0.2 s and costs a few hundred tokens.

Chrome only builds this tree while it's in front, and right after a page load it can come
back empty or half-built, so an empty read is retried once.
"""

import logging
import time
from dataclasses import dataclass

import win32gui
from rapidfuzz import fuzz

from . import desktop
from . import mouse as jmouse

log = logging.getLogger(__name__)

MAX_ITEMS = 60
MAX_NAME = 70


@dataclass
class Element:
    kind: str
    name: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom in screen pixels

    @property
    def centre(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return (l + r) // 2, (t + b) // 2

    def label(self) -> str:
        name = self.name if len(self.name) <= MAX_NAME else self.name[:MAX_NAME - 1] + "…"
        return f'{self.kind} "{name}"'


_KINDS = {  # UIA control type name -> short word the AI sees
    "Button": "button", "Hyperlink": "link", "Edit": "field", "CheckBox": "checkbox", "RadioButton": "option",
    "ComboBox": "dropdown", "MenuItem": "menu item", "TabItem": "tab", "ListItem": "list item",
    "SplitButton": "button", "Slider": "slider",
}

_last: list[Element] = []  # the list the AI was last shown, so it can click by id


def _read(hwnd: int) -> list[Element]:
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd)
    cache = uia.CreateCacheRequest()
    for pid in (UIA.UIA_NamePropertyId, UIA.UIA_ControlTypePropertyId, UIA.UIA_BoundingRectanglePropertyId,
                UIA.UIA_IsOffscreenPropertyId):
        cache.AddProperty(pid)
    # In a browser, only the web page: tabs and the address bar have their own tools.
    doc = root.FindFirst(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_DocumentControlTypeId))
    if not doc and desktop._process_name(hwnd) in desktop.BROWSERS:
        return []  # the page isn't there yet: Chrome's own buttons ("Tab search") aren't the page (30 Sep)
    scope = doc or root
    ids = {getattr(UIA, f"UIA_{k}ControlTypeId"): v for k, v in _KINDS.items()}
    cond = None
    for type_id in ids:
        c = uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, type_id)
        cond = c if cond is None else uia.CreateOrCondition(cond, c)
    found = scope.FindAllBuildCache(UIA.TreeScope_Descendants, cond, cache)

    wl, wt, wr, wb = win32gui.GetWindowRect(hwnd)
    sw, sh = jmouse.screen_size()
    out, seen = [], set()
    for i in range(found.Length):
        e = found.GetElement(i)
        name = " ".join((e.CachedName or "").split())
        if not name or e.CachedIsOffscreen or (len(name) == 1 and not name.isdigit()):
            continue  # unnamed, hidden, or an icon-font glyph like "ġ"
        r = e.CachedBoundingRectangle
        l, t, rr, b = max(r.left, wl, 0), max(r.top, wt, 0), min(r.right, wr, sw), min(r.bottom, wb, sh)
        if rr - l < 4 or b - t < 4:
            continue  # hidden, collapsed, or outside the window
        kind = ids.get(e.CachedControlType, "item")
        if (kind, name) in seen:
            continue  # the same link twice (thumbnail + title): once is enough
        seen.add((kind, name))
        out.append(Element(kind, name, (l, t, rr, b)))
    out.sort(key=lambda el: (el.rect[1] // 12, el.rect[0]))  # reading order: rows top to bottom, then left to right
    return out


def read_front() -> list[Element]:
    hwnd = win32gui.GetForegroundWindow()
    items = _read(hwnd)
    if not items and desktop._process_name(hwnd) in desktop.BROWSERS:
        time.sleep(0.4)  # page still loading, or Chrome just switched its accessibility tree on
        items = _read(hwnd)
    return items


def describe(items: list[Element]) -> str:
    if not items:
        return ("No named items found in the front window (it may be a picture, a game board or still loading). "
                "Use look_at_screen.")
    shown = items[:MAX_ITEMS]
    text = "; ".join(f"[{i}] {el.label()}" for i, el in enumerate(shown, 1))
    if len(items) > MAX_ITEMS:
        text += f"; (+{len(items) - MAX_ITEMS} more further down: scroll or find_on_page)"
    return text


def page_elements() -> str:
    """The clickable items in the front window, numbered, for the AI."""
    global _last
    t0 = time.monotonic()
    try:
        _last = read_front()
    except Exception:
        log.debug("Couldn't read the window's items", exc_info=True)
        _last = []
        return "I couldn't read the items in this window. Use look_at_screen."
    log.info("Read %d on-screen items in %.2fs", len(_last), time.monotonic() - t0)
    return describe(_last)


def match(items: list[Element], name: str) -> tuple[Element | None, str]:
    """The item a spoken/typed name means, or (None, why not)."""
    want = " ".join(name.lower().split()).strip("\"' ")
    if not want:
        return None, "No name given."
    exact = [el for el in items if el.name.lower() == want]
    if len(exact) == 1:
        return exact[0], ""
    scored = sorted(((max(fuzz.ratio(want, el.name.lower()), fuzz.partial_ratio(want, el.name.lower()) - 5), el)
                     for el in (exact or items)), key=lambda s: -s[0])
    if not scored or scored[0][0] < 70:
        return None, f"Nothing called {name!r} is on screen."
    best = scored[0][0]
    close = [el for s, el in scored if s >= best - 3]
    if len(close) > 1 and not exact:
        names = "; ".join(el.label() for el in close[:4])
        return None, f"More than one item matches {name!r}: {names}. Use the id, or ask the user which."
    return close[0], ""


def resolve(id: int | None = None, name: str | None = None) -> tuple[Element | None, str]:
    """Find the item to click on the screen as it is NOW (the list the AI saw may be out of date)."""
    wanted = None
    if id is not None:
        if not 1 <= id <= len(_last):
            return None, f"There's no item [{id}] in the last list. Call page_elements again."
        wanted = _last[id - 1]
    fresh = read_front()
    if wanted:
        same = [el for el in fresh if el.kind == wanted.kind and el.name == wanted.name]
        if not same:
            return None, f"{wanted.label()} isn't on screen any more. Current items: {describe(fresh)}"
        # the one nearest to where it was, if the name appears more than once
        return min(same, key=lambda el: abs(el.rect[1] - wanted.rect[1]) + abs(el.rect[0] - wanted.rect[0])), ""
    return match(fresh, name or "")


def click(el: Element, double: bool = False) -> str:
    x, y = el.centre
    sw, sh = jmouse.screen_size()
    jmouse.click(x / (sw - 1) * 1000, y / (sh - 1) * 1000, "left", double)
    return f"Clicked the {el.name[:MAX_NAME]} {el.kind}."


def focused_kind() -> str:
    """What has the keyboard focus: 'field' (you can type), 'document', 'button'… (for the agent's checks)."""
    UIA, uia = desktop._uia()
    el = uia.GetFocusedElement()
    if not el:
        return "none"
    ids = {getattr(UIA, f"UIA_{k}ControlTypeId"): v for k, v in _KINDS.items()}
    ids[UIA.UIA_DocumentControlTypeId] = "document"
    return ids.get(el.CurrentControlType, "other")


_DIALOG_BUTTONS = {"ok", "cancel", "leave", "stay", "allow", "block", "yes", "no", "don't save", "save",
                   "close", "continue", "reload", "not now", "dismiss"}


def open_dialog(hwnd: int | None = None) -> str:
    """The name of a dialog box open in the front window ("Leave site?", a page's alert…), or "".
    While one is open, keys and clicks meant for the page go to the dialog instead."""
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd or win32gui.GetForegroundWindow())
    cond = uia.CreateOrCondition(
        uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_WindowControlTypeId),
        uia.CreatePropertyCondition(UIA.UIA_LocalizedControlTypePropertyId, "dialog"))
    found = root.FindAll(UIA.TreeScope_Descendants, cond)
    button = uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_ButtonControlTypeId)
    for i in range(min(found.Length, 5)):
        dlg = found.GetElement(i)
        # Only a real dialog: it has the buttons dialogs have (apps nest ordinary windows too).
        buttons = dlg.FindAll(UIA.TreeScope_Descendants, button)
        names = {" ".join((buttons.GetElement(j).CurrentName or "").lower().split()) for j in range(buttons.Length)}
        if names & _DIALOG_BUTTONS:
            return " ".join((dlg.CurrentName or "a dialog box").split())[:80]
    return ""


def is_fullscreen() -> bool:
    """Does the front window cover its whole monitor (a video or browser in full screen)? A maximized
    window leaves the taskbar showing, so it doesn't count."""
    import win32api
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or win32gui.GetClassName(hwnd) in ("Progman", "WorkerW"):
        return False
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    ml, mt, mr, mb = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))["Monitor"]
    return l <= ml and t <= mt and r >= mr and b >= mb


def front_is_browser() -> bool:
    try:
        return desktop._process_name(win32gui.GetForegroundWindow()) in desktop.BROWSERS
    except Exception:
        return False


def mentions(thing: str) -> bool:
    """Does the last list read have an item called (roughly) this? Ambiguous counts as yes."""
    el, why = match(_last, thing)
    return el is not None or why.startswith("More than one")
