"""Windows, virtual desktops and Settings pages: all instant, all by Windows' own shortcuts or URIs."""

import os
import time

import win32api
import win32gui

from . import ability
from ..skills import desktop, elements, keys

_THIS = r"(?:(?:this|the|current|my) )?(?:window|app|screen)?"


def _press(combo: str, reply: str) -> str:
    keys.press(combo)
    return reply


# ---- checked window moves (30 Sep live test: "snap left" on a full-screen video did nothing, yet was reported
# done, and Windows' Snap Assist picker was left open). Each move now checks where the window really went.

def _front() -> int:
    return win32gui.GetForegroundWindow()


def _rect(hwnd) -> tuple[int, int, int, int]:
    return win32gui.GetWindowRect(hwnd)


def _work_area(hwnd) -> tuple[int, int, int, int]:
    return win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))["Work"]


def _until(test, seconds: float = 1.2) -> bool:
    deadline = time.monotonic() + seconds
    while not test():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def _leave_fullscreen():
    """A video or browser in full screen ignores snapping: leave it first (Esc for a video, F11 for the browser)."""
    if not elements.is_fullscreen():
        return
    keys.press("esc")
    if not _until(lambda: not elements.is_fullscreen(), 0.8):
        keys.press("f11")
        _until(lambda: not elements.is_fullscreen(), 0.8)


def _snap_assist_open() -> bool:
    return any(title == "Snap Assist" for _, _, title in desktop._app_windows())


def _close_snap_assist():
    """After a snap, Windows offers the other windows for the other half; the user didn't ask for that.
    It appears a moment after the snap, so wait for it, then Esc and check it went (30 Sep: it stayed)."""
    if not _until(_snap_assist_open, 0.8):
        return
    for _ in range(2):
        keys.press("esc")
        if _until(lambda: not _snap_assist_open(), 0.6):
            return


def _on_half(hwnd, side: str) -> bool:
    l, t, r, b = _rect(hwnd)
    wl, wt, wr, wb = _work_area(hwnd)
    mid, slack = (wl + wr) // 2, 40
    if side == "left":
        return abs(l - wl) <= slack and abs(r - mid) <= slack
    return abs(l - mid) <= slack and abs(r - wr) <= slack


def _snap(side: str) -> str:
    _leave_fullscreen()
    hwnd = _front()
    if _on_half(hwnd, side):
        # Already there. Pressing again would wrap it round to the other side on one monitor (30 Sep).
        return f"It's already on the {side}."
    keys.press(f"win+{side}")
    ok = _until(lambda: _on_half(hwnd, side), 0.7)
    if not ok:  # from the other half, the first press only brings it back to the middle
        keys.press(f"win+{side}")
        ok = _until(lambda: _on_half(hwnd, side))
    _close_snap_assist()
    return f"Snapped {side}." if ok else f"Not done: the window didn't move to the {side} half."


@ability("snap_left", "snap the front window to the left half",
         rf"snap {_THIS}\s*(?:to (?:the )?)?left", r"move (?:this|the) window (?:to the )?left( half)?")
def snap_left():
    return _snap("left")


@ability("snap_right", "snap the front window to the right half",
         rf"snap {_THIS}\s*(?:to (?:the )?)?right", r"move (?:this|the) window (?:to the )?right( half)?")
def snap_right():
    return _snap("right")


@ability("maximize_front", "maximize the front window",
         r"maximi[sz]e(?: (?:this|it|the window|this window|the screen|screen))?", r"make (?:it|this) (?:full|bigger)")
def maximize_front():
    hwnd = _front()
    if win32gui.IsZoomed(hwnd):
        return "It's already maximised."
    keys.press("win+up")
    return "Maximised." if _until(lambda: win32gui.IsZoomed(hwnd)) else "Not done: the window didn't maximise."


@ability("minimize_front", "minimize the front window",
         r"minimi[sz]e(?: (?:this|it|the window|this window))?", r"hide (?:this|it)")
def minimize_front():
    hwnd = _front()
    keys.press("win+down win+down")
    return "Minimised." if _until(lambda: win32gui.IsIconic(hwnd)) else "Not done: the window didn't minimise."


@ability("other_screen", "move the front window to the other monitor",
         r"move (?:this|it|the window|this window) to (?:the )?(?:other|second|next) (?:screen|monitor|display)",
         r"(?:send|throw) (?:this|it) to (?:the )?other (?:screen|monitor)")
def other_screen():
    return _press("win+shift+right", "Moved it to the other screen.")


@ability("task_view", "show all open windows (task view)",
         r"(?:show|open) (?:all )?(?:my )?(?:open )?windows", r"task view", r"show everything")
def task_view():
    return _press("win+tab", "Here are your windows.")


@ability("new_desktop", "create a new virtual desktop",
         r"(?:new|create a|make a|add a) (?:virtual )?desktop")
def new_desktop():
    return _press("win+ctrl+d", "New desktop.")


@ability("next_desktop", "switch to the next virtual desktop",
         r"(?:next|right) desktop", r"(?:switch|go) to (?:the )?next desktop")
def next_desktop():
    return _press("win+ctrl+right", "Next desktop.")


@ability("previous_desktop", "switch to the previous virtual desktop",
         r"(?:previous|left|last) desktop", r"(?:switch|go) (?:back )?to (?:the )?previous desktop")
def previous_desktop():
    return _press("win+ctrl+left", "Previous desktop.")


@ability("close_desktop", "close the current virtual desktop (its windows move to the next one)",
         r"close (?:this |the )?(?:virtual )?desktop")
def close_desktop():
    return _press("win+ctrl+f4", "Closed this desktop.")


# Settings pages, opened directly (no clicking through menus).
SETTINGS = {
    "bluetooth": "bluetooth", "devices": "bluetooth", "wi fi": "network-wifi", "wifi": "network-wifi",
    "network": "network", "internet": "network", "display": "display", "screen": "display",
    "brightness": "display", "night light": "nightlight", "sound": "sound", "audio": "sound",
    "volume": "apps-volume", "notifications": "notifications", "focus": "focus", "battery": "batterysaver",
    "power": "powersleep", "storage": "storagesense", "apps": "appsfeatures", "default apps": "defaultapps",
    "startup": "startupapps", "personalization": "personalization", "background": "personalization-background",
    "wallpaper": "personalization-background", "colors": "colors", "dark mode": "colors",
    "themes": "themes", "lock screen": "lockscreen", "taskbar": "taskbar", "mouse": "mousetouchpad",
    "touchpad": "devices-touchpad", "keyboard": "keyboard", "typing": "typing", "language": "regionlanguage",
    "time": "dateandtime", "date": "dateandtime", "privacy": "privacy", "microphone": "privacy-microphone",
    "camera": "privacy-webcam", "updates": "windowsupdate", "windows update": "windowsupdate",
    "accounts": "yourinfo", "vpn": "network-vpn", "hotspot": "network-mobilehotspot", "airplane mode":
    "network-airplanemode", "printers": "printers", "clipboard": "clipboard", "about": "about",
    "multitasking": "multitasking", "projection": "project", "accessibility": "easeofaccess",
}


@ability("open_settings", "open a Windows Settings page",
         r"(?:open|show|go to) (?:the |my )?(?P<value>.+?) settings",
         r"(?:open|show) settings for (?P<value>.+)",
         r"(?:open |show )?(?:windows )?settings",
         value="page, e.g. display")
def open_settings(value: str | None = None):
    page = (value or "").strip().lower()
    if page and page not in SETTINGS:
        page = next((k for k in SETTINGS if k in page or page in k), "")
        if not page:
            raise ValueError(f"no Settings page called {value!r}")
    os.startfile(f"ms-settings:{SETTINGS[page]}" if page else "ms-settings:")
    return f"Opened {page} settings." if page else "Opened Settings."
