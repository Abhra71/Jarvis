"""Visible window control: bring to front, minimise, maximise, close, keystrokes, scrolling, media keys.

Everything happens on the real, visible windows, the same way you'd do it by hand.
"""

import ctypes
import logging
import time

import psutil
import win32con
import win32gui
from pywinauto import keyboard
from rapidfuzz import fuzz

from . import mouse as jmouse
from .apps import _allow_foreground

log = logging.getLogger(__name__)

BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe")
STEP_PAUSE = 0.25  # small gap so you can see each step happen

# Spoken name -> process name, for apps whose window title doesn't say what they are.
_EXE_ALIASES = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe", "edge": "msedge.exe", "browser": None,
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "vs code": "code.exe",
    "visual studio code": "code.exe", "word": "winword.exe", "excel": "excel.exe",
    "powerpoint": "powerpnt.exe", "terminal": "windowsterminal.exe", "command prompt": "cmd.exe",
}

_BROWSER_KEYS = {
    "new_tab": "^t",
    "close_tab": "^w",
    "reopen_closed_tab": "^+t",
    "next_tab": "^{TAB}",
    "previous_tab": "^+{TAB}",
    "back": "%{LEFT}",
    "forward": "%{RIGHT}",
    "reload": "{F5}",
    "fullscreen": "{F11}",
    "zoom_in": "^{+}",
    "zoom_out": "^-",
    "top": "{HOME}",
    "bottom": "{END}",
}
BROWSER_ACTIONS = sorted(list(_BROWSER_KEYS) + ["scroll_down", "scroll_up"])

# Spoken as-is when a simple request finishes without asking the AI for a reply sentence.
_BROWSER_DONE = {
    "new_tab": "Opened a new tab.", "close_tab": "Closed the tab.", "reopen_closed_tab": "Reopened the tab.",
    "next_tab": "Next tab.", "previous_tab": "Previous tab.", "back": "Went back.", "forward": "Went forward.",
    "reload": "Reloaded the page.", "fullscreen": "Toggled full screen.", "zoom_in": "Zoomed in.",
    "zoom_out": "Zoomed out.", "top": "Back to the top.", "bottom": "Jumped to the bottom.",
}

_MEDIA_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


# ---- finding windows ---------------------------------------------------------

def _process_name(hwnd) -> str:
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        return psutil.Process(pid.value).name().lower()
    except psutil.Error:
        return ""


def _app_windows() -> list[tuple[int, str, str]]:
    """Visible top-level windows as (hwnd, process name, title), front-most first."""
    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return
        if title in ("Program Manager", "Windows Input Experience") or win32gui.GetClassName(hwnd) == "Shell_TrayWnd":
            return
        found.append((hwnd, _process_name(hwnd), title))

    win32gui.EnumWindows(visit, None)
    return found


def find_window(app: str) -> tuple[int, str, str] | None:
    app = app.lower().strip()
    windows = _app_windows()
    if app in ("browser", "the browser", "web browser"):
        return next((w for w in windows if w[1] in BROWSERS), None)

    exe = _EXE_ALIASES.get(app)
    if exe:
        hit = next((w for w in windows if w[1] == exe), None)
        if hit:
            return hit

    best, best_score = None, 0
    for w in windows:
        stem = w[1].removesuffix(".exe")
        score = max(fuzz.WRatio(app, stem), fuzz.partial_ratio(app, w[2].lower()))
        if score > best_score:
            best, best_score = w, score
    return best if best_score >= 80 else None


def _focus(hwnd):
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    _allow_foreground()
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        # Fallback: briefly make it topmost so it at least appears in front.
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    time.sleep(STEP_PAUSE)


def _pretty(w) -> str:
    return w[1].removesuffix(".exe").capitalize() if w[1] else w[2]


# ---- window actions ----------------------------------------------------------

def window_action(app: str, action: str) -> str:
    """action: focus, minimize, maximize, restore, close, close_all (every window of that app)."""
    w = find_window(app)
    if not w:
        return f"I don't see {app} open."
    hwnd = w[0]
    name = _pretty(w)
    if action == "close_all":
        # "Close both of them": every top-level window of the same program, front-most first.
        same = [x for x in _app_windows() if x[1] == w[1]] if w[1] else [w]
        for x in same:
            _focus(x[0])
            win32gui.PostMessage(x[0], win32con.WM_CLOSE, 0, 0)
            time.sleep(STEP_PAUSE)
        return f"Closed {len(same)} {name} window{'s' if len(same) != 1 else ''}."
    if action == "close":
        _focus(hwnd)  # show it first so you see what's being closed
        # A normal close request: the app still asks "save changes?" if it needs to.
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return f"Closed {name}."
    if action == "minimize":
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return f"Minimised {name}."
    if action == "maximize":
        _focus(hwnd)
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return f"Maximised {name}."
    if action == "restore":
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        _focus(hwnd)
        return f"Restored {name}."
    _focus(hwnd)
    return f"Switched to {name}."


def list_open_windows(limit: int = 12) -> str:
    seen = []
    for _, exe, title in _app_windows():
        label = f"{exe.removesuffix('.exe')}: {title[:45]}"
        if label not in seen:
            seen.append(label)
    return "; ".join(seen[:limit]) or "No windows open."


# ---- browser and keyboard ------------------------------------------------------

def _front_browser() -> int | None:
    fg = win32gui.GetForegroundWindow()
    if _process_name(fg) in BROWSERS:
        return fg
    w = find_window("browser")
    if w:
        _focus(w[0])
        return w[0]
    return None


def browser_action(action: str, times: int = 1) -> str:
    hwnd = _front_browser()
    if not hwnd:
        return "No browser window is open."
    times = max(1, min(int(times or 1), 10))

    if action in ("scroll_down", "scroll_up"):
        # Same visible, stoppable mouse as every other mouse action: glide to the page's middle, then wheel.
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = jmouse.screen_size()
        x, y = (left + right) / 2 / w * 1000, (top + bottom) / 2 / h * 1000
        return jmouse.scroll_at(x, y, "down" if action == "scroll_down" else "up", 5 * times)

    keys = _BROWSER_KEYS.get(action)
    if not keys:
        return f"Unknown browser action {action}."
    for _ in range(times):
        keyboard.send_keys(keys, vk_packet=False)
        time.sleep(STEP_PAUSE)
    return _BROWSER_DONE.get(action, "Done.")


def address_bar(text: str) -> str:
    """Type into the current tab's address bar and press Enter: a URL goes there, words get searched."""
    if not _front_browser():
        return "No browser window is open."
    keyboard.send_keys("^l")
    time.sleep(STEP_PAUSE)
    type_text(text, press_enter=True)
    return f"Entered {text} in the address bar."


def find_on_page(text: str) -> str:
    """Ctrl+F in the front browser: the page jumps straight to the first match and highlights it.

    Much faster than scrolling and taking screenshots over and over to hunt for a word.
    """
    if not _front_browser():
        return "No browser window is open."
    keyboard.send_keys("^f")
    time.sleep(0.3)
    keyboard.send_keys("^a")
    type_text(text)
    keyboard.send_keys("{ENTER}")
    time.sleep(0.4)
    keyboard.send_keys("{ESC}")  # closes the find bar; the match stays highlighted and in view
    time.sleep(0.2)
    return (f"Searched this page for {text!r}; if it exists, the first match is now scrolled into view and "
            "highlighted. Use look_at_screen to see it before clicking.")


def _uia():
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA
    return UIA, comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)


def _browser_tabs() -> list[tuple[int, str, object]]:
    """Every tab of every open browser window as (window, tab title, tab element), front window first."""
    UIA, uia = _uia()
    is_tab = uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_TabItemControlTypeId)
    tabs = []
    for hwnd, proc, _ in _app_windows():
        if proc not in BROWSERS:
            continue
        found = uia.ElementFromHandle(hwnd).FindAll(UIA.TreeScope_Descendants, is_tab)
        for i in range(found.Length):
            el = found.GetElement(i)
            tabs.append((hwnd, el.CurrentName, el))
    return tabs


def close_tab(name: str) -> str:
    """Close the browser tab whose title matches `name`, in any browser window: it's clicked (so you see which
    one) and closed with Ctrl+W. On 26 Sep "close the chess tab" closed whichever tab was in front."""
    try:
        tabs = _browser_tabs()
    except Exception:
        log.debug("Couldn't list tabs", exc_info=True)
        return "I couldn't read the browser's tabs."
    if not tabs:
        return "No browser window is open."
    want = name.lower().removesuffix(" tab").strip()
    scored = sorted(((fuzz.partial_ratio(want, t[1].lower()), t) for t in tabs), key=lambda s: -s[0])
    best_score, (hwnd, title, el) = scored[0]
    if best_score < 75:
        return f"I don't see a {want} tab."
    close_matches = [t for s, t in scored if s >= best_score - 5]
    if len(close_matches) > 1:
        names = "; ".join(t[1][:40] for t in close_matches[:3])
        return f"More than one tab matches {want}: {names}. Ask which one."
    _focus(hwnd)
    r = el.CurrentBoundingRectangle
    w, h = jmouse.screen_size()
    jmouse.click((r.left + r.right) / 2 / w * 1000, (r.top + r.bottom) / 2 / h * 1000)
    keyboard.send_keys("^w")
    time.sleep(STEP_PAUSE)
    return f"Closed the {want} tab."


def current_url() -> str | None:
    """Read the front browser tab's address from Chrome/Edge's address bar (via Windows UI Automation)."""
    hwnd = _front_browser()
    if not hwnd:
        return None
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA

        uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
        edit = uia.ElementFromHandle(hwnd).FindFirst(
            UIA.TreeScope_Descendants,
            uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_EditControlTypeId))
        if not edit:
            return None
        value = edit.GetCurrentPattern(UIA.UIA_ValuePatternId).QueryInterface(UIA.IUIAutomationValuePattern)
        url = value.CurrentValue
        return url if "://" in url else f"https://{url}"
    except Exception:
        log.debug("Couldn't read the address bar", exc_info=True)
        return None


def site_search(query: str, search_urls: dict[str, str]) -> str:
    """Search inside the website that's open in the front tab.

    For sites we know (YouTube, Amazon, GitHub, …) the site's own search URL is typed into the
    address bar, which always works and you still see it happen. For other sites the AI is told
    to click the site's search box itself.
    """
    from urllib.parse import quote_plus, urlparse

    url = current_url()
    if not url:
        return "No browser tab is open in front."
    host = urlparse(url).netloc.lower().removeprefix("www.").removeprefix("m.")
    for site, template in search_urls.items():
        if urlparse(template).netloc.lower().removeprefix("www.") == host or host.startswith(f"{site}."):
            address_bar(template.format(q=quote_plus(query)))
            return f"Searched {site} for {query} in this tab."
    return (f"I don't know {host}'s search address. Use look_at_screen, click the site's search box, "
            f"then type_text {query!r} with press_enter.")


def front_window() -> str:
    hwnd = win32gui.GetForegroundWindow()
    return f"{_process_name(hwnd).removesuffix('.exe')}: {win32gui.GetWindowText(hwnd)}"


def screenshot_jpeg(max_width: int = 1100) -> bytes:
    """What's on screen right now, scaled down so it's quick to send and cheap for the AI.
    1100px wide still leaves video titles and buttons readable."""
    import io

    from PIL import Image, ImageGrab

    time.sleep(0.3)  # let the last click/scroll finish drawing
    img = ImageGrab.grab()
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=70)
    return buf.getvalue()


def _escape(text: str) -> str:
    return "".join("{" + c + "}" if c in "{}+^%~()[]" else c for c in text)


PASTE_OVER = 30  # characters: longer text is pasted in one go instead of typed key by key


def _paste(text: str) -> bool:
    """Put the text on the clipboard, Ctrl+V, then give the user's clipboard back. Only when the clipboard
    holds text or nothing (an image or files can't be put back faithfully, so then we type instead)."""
    import win32clipboard as cb
    try:
        cb.OpenClipboard()
        try:
            formats, fmt = [], cb.EnumClipboardFormats(0)
            while fmt:
                formats.append(fmt)
                fmt = cb.EnumClipboardFormats(fmt)
            if formats and not set(formats) <= {cb.CF_UNICODETEXT, cb.CF_TEXT, cb.CF_OEMTEXT, cb.CF_LOCALE}:
                return False
            old = cb.GetClipboardData(cb.CF_UNICODETEXT) if cb.CF_UNICODETEXT in formats else None
            cb.EmptyClipboard()
            cb.SetClipboardText(text, cb.CF_UNICODETEXT)
        finally:
            cb.CloseClipboard()
        keyboard.send_keys("^v")
        time.sleep(0.15)  # let the app take it before the clipboard changes back
        cb.OpenClipboard()
        try:
            cb.EmptyClipboard()
            if old is not None:
                cb.SetClipboardText(old, cb.CF_UNICODETEXT)
        finally:
            cb.CloseClipboard()
        return True
    except Exception:
        log.debug("Paste failed; typing instead", exc_info=True)
        return False


def type_text(text: str, press_enter: bool = False) -> str:
    if len(text) <= PASTE_OVER or not _paste(text):
        # Short text is typed so you can see it. (Pasting is also safer for several lines: typed new lines
        # would be Enter presses, which send a message in a chat app.)
        keyboard.send_keys(_escape(text), with_spaces=True, with_newlines=False, pause=0.01)
    if press_enter:
        time.sleep(STEP_PAUSE)
        keyboard.send_keys("{ENTER}")
    return "Typed it."


def media(action: str) -> str:
    vk = _MEDIA_VK.get(action)
    if vk is None:
        return f"Unknown media action {action}."
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    return {"play_pause": "Done.", "next": "Next track.", "previous": "Previous track.", "stop": "Stopped."}[action]
