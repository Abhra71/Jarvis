"""Visible mouse control: the real cursor glides to the target and clicks, like a person would.

Positions come from the AI looking at a screenshot, given as x/y from 0 to 1000
(0,0 = top-left of the screen, 1000,1000 = bottom-right), so they don't depend on
the screenshot's size.

If you move the mouse yourself while Jarvis is working, it notices and stops.
"""

import ctypes
import logging
import time

log = logging.getLogger(__name__)

user32 = ctypes.windll.user32

MOVE_SECONDS = 0.12   # how long the glide to a target takes: quick, but still visible (was 0.35 s)
TAKEOVER_PIXELS = 40  # cursor moved further than this by someone else = you took over

_MOUSEEVENTF = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
_WHEEL = 0x0800


class UserTookOver(Exception):
    """The user moved the mouse during an action: stop everything."""


class Cancelled(Exception):
    """The user said "Hi Jarvis" while Jarvis was busy: stop at the next step."""


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_last_set: tuple[int, int] | None = None


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def cursor() -> tuple[int, int]:
    p = _Point()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def reset_takeover():
    """Called at the start of each request: wherever the mouse is now is fine."""
    global _last_set
    _last_set = None


def _check_takeover():
    if _last_set is None:
        return
    x, y = cursor()
    if abs(x - _last_set[0]) > TAKEOVER_PIXELS or abs(y - _last_set[1]) > TAKEOVER_PIXELS:
        raise UserTookOver()


def to_pixels(x: float, y: float) -> tuple[int, int]:
    w, h = screen_size()
    x, y = max(0.0, min(1000.0, float(x))), max(0.0, min(1000.0, float(y)))
    return round(x / 1000 * (w - 1)), round(y / 1000 * (h - 1))


def glide_to(px: int, py: int):
    """Move the real cursor smoothly so you can see where it's going."""
    global _last_set
    _check_takeover()
    sx, sy = cursor()
    steps = max(8, int(MOVE_SECONDS * 60))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)  # ease in/out
        user32.SetCursorPos(round(sx + (px - sx) * t), round(sy + (py - sy) * t))
        time.sleep(MOVE_SECONDS / steps)
    _last_set = (px, py)


def click(x: float, y: float, button: str = "left", double: bool = False) -> str:
    px, py = to_pixels(x, y)
    glide_to(px, py)
    time.sleep(0.03)
    down, up = _MOUSEEVENTF.get(button, _MOUSEEVENTF["left"])
    for _ in range(2 if double else 1):
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.06)
    log.info("%s%s-click at (%d, %d)", "double " if double else "", button, px, py)
    time.sleep(0.12)
    return f"{'Double-' if double else ''}{button.capitalize()}-clicked at screen position {x:.0f},{y:.0f}."


def scroll_at(x: float, y: float, direction: str = "down", amount: int = 3) -> str:
    px, py = to_pixels(x, y)
    glide_to(px, py)
    notches = max(1, min(int(amount or 3), 20))
    delta = -120 if direction == "down" else 120
    for _ in range(notches):
        _check_takeover()
        user32.mouse_event(_WHEEL, 0, 0, delta, 0)
        time.sleep(0.05)
    time.sleep(0.1)
    return f"Scrolled {direction}."


def hover(x: float, y: float) -> str:
    glide_to(*to_pixels(x, y))
    return "Moved the mouse there."


def click_pair(x1: float, y1: float, x2: float, y2: float, drag: bool = False) -> str:
    """Two spots from the same screenshot in one go: a chess move (piece, then square), or a drag.
    Saves a whole look-and-think round trip between the two clicks."""
    if drag:
        down, up = _MOUSEEVENTF["left"]
        glide_to(*to_pixels(x1, y1))
        time.sleep(0.08)
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.1)
        glide_to(*to_pixels(x2, y2))
        time.sleep(0.1)
        user32.mouse_event(up, 0, 0, 0, 0)
        log.info("Dragged from %s,%s to %s,%s", x1, y1, x2, y2)
        time.sleep(0.15)
        return f"Dragged from {x1:.0f},{y1:.0f} to {x2:.0f},{y2:.0f}."
    click(x1, y1)
    click(x2, y2)
    return f"Clicked {x1:.0f},{y1:.0f} then {x2:.0f},{y2:.0f}."
