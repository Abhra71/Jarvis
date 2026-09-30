"""Any key or shortcut, the way a person presses them: "ctrl+shift+t", "alt+tab", "win+d", "f5",
or a chord like "ctrl+k ctrl+s" (pressed one after the other).

Shortcuts are the fastest way to do most things (no looking, no mouse), so the AI is told to use
them whenever one exists. A few combinations can't be taken back; those are refused or need the
user's yes (see check()).
"""

import re

from pywinauto import keyboard

_MODS = {"ctrl": "^", "control": "^", "ctl": "^", "shift": "+", "alt": "%", "option": "%"}
_WIN = {"win", "windows", "super", "meta", "start", "cmd"}
_NAMED = {
    "enter": "{ENTER}", "return": "{ENTER}", "esc": "{ESC}", "escape": "{ESC}", "tab": "{TAB}", "space": " ",
    "spacebar": " ", "backspace": "{BACKSPACE}", "delete": "{DELETE}", "del": "{DELETE}", "insert": "{INSERT}",
    "ins": "{INSERT}", "home": "{HOME}", "end": "{END}", "pageup": "{PGUP}", "pgup": "{PGUP}",
    "page_up": "{PGUP}", "pagedown": "{PGDN}", "pgdn": "{PGDN}", "page_down": "{PGDN}", "up": "{UP}",
    "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}", "printscreen": "{PRTSC}", "prtsc": "{PRTSC}",
    "capslock": "{CAPSLOCK}", "menu": "{APPS}", "apps": "{APPS}",
    "plus": "{+}", "minus": "-", "equals": "=", "comma": ",", "period": ".", "dot": ".", "slash": "/",
    "backslash": "\\", "semicolon": ";", "quote": "'", "backtick": "`", "tilde": "{~}",
    "leftbracket": "[", "rightbracket": "]",
}
_ESCAPE = {"+": "{+}", "^": "{^}", "%": "{%}", "~": "{~}", "(": "{(}", ")": "{)}", "{": "{{}", "}": "{}}"}

# The old fixed key names still work ("select_all", "switch_window"…).
ALIASES = {
    "select_all": "ctrl+a", "copy": "ctrl+c", "cut": "ctrl+x", "paste": "ctrl+v", "undo": "ctrl+z",
    "redo": "ctrl+y", "save": "ctrl+s", "find": "ctrl+f", "new_window": "ctrl+n", "close_window": "alt+f4",
    "switch_window": "alt+tab", "show_desktop": "win+d",
}


class BadKeys(ValueError):
    pass


def _one(combo: str) -> str:
    """'ctrl+shift+t' -> '^+t' (pywinauto's notation); 'win+d' -> '{VK_LWIN down}d{VK_LWIN up}'."""
    raw = combo.strip().lower()
    if raw in ALIASES:
        raw = ALIASES[raw]
    parts = [p for p in re.split(r"\s*\+\s*", raw) if p] if raw != "+" else ["+"]
    if raw.endswith("++"):  # "ctrl++" = ctrl and the plus key
        parts = [p for p in raw[:-2].split("+") if p] + ["+"]
    mods, win, key = "", False, None
    for p in parts:
        if p in _MODS:
            mods += _MODS[p]
        elif p in _WIN:
            win = True
        elif key is None:
            key = p
        else:
            raise BadKeys(f"'{combo}' has two main keys ({key}, {p}); use a space between separate presses")
    if key is None:
        if win:
            return "{VK_LWIN}"
        raise BadKeys(f"'{combo}' has no main key")
    if key in _NAMED:
        k = _NAMED[key]
    elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key):
        k = "{" + key.upper() + "}"
    elif len(key) == 1:
        k = _ESCAPE.get(key, key)
    else:
        raise BadKeys(f"unknown key '{key}'")
    keys = mods + k
    return "{VK_LWIN down}" + keys + "{VK_LWIN up}" if win else keys


def parse(keys: str) -> list[str]:
    """'ctrl+k ctrl+s' -> ['^k', '^s']. Raises BadKeys with a sentence the AI can act on."""
    joined = re.sub(r"\s*\+\s*", "+", (keys or "").strip())  # "ctrl + shift + t" -> "ctrl+shift+t"
    presses = [p for p in re.split(r"[\s,]+", joined) if p]
    if not presses:
        raise BadKeys("no keys given")
    return [_one(p) for p in presses]


# ---- safety -------------------------------------------------------------------

_BLOCKED = {  # can't be undone, or not Jarvis's business
    "+{DELETE}": "Shift+Delete deletes permanently",
    "^%{DELETE}": "Ctrl+Alt+Delete is for the user",
}
_FILE_DELETE = {"{DELETE}", "^d"}  # in File Explorer these send files to the recycle bin
_CHAT_APPS = ("whatsapp", "telegram", "discord", "slack", "messenger", "instagram", "gmail", "outlook", "teams",
              "signal", "mail")


def check(keys: str, front: str) -> tuple[str | None, str | None]:
    """(refusal, needs_yes): why these keys are refused, or what they'd do that needs a spoken yes."""
    presses = parse(keys)
    front = (front or "").lower()
    for k in presses:
        if k in _BLOCKED:
            return f"{_BLOCKED[k]}; I never do that.", None
        if k in _FILE_DELETE and front.startswith("explorer"):
            return "that would delete files, and deleting is turned off.", None
    if any(k.endswith("{ENTER}") for k in presses) and any(app in front for app in _CHAT_APPS):
        return None, "press Enter in a chat or mail window, which sends the message"
    if any(k == "{VK_LWIN down}l{VK_LWIN up}" for k in presses):
        return None, "lock the PC"
    return None, None


def press(keys: str, times: int = 1) -> str:
    presses = parse(keys)
    for _ in range(max(1, min(int(times or 1), 30))):
        for k in presses:
            keyboard.send_keys(k, with_spaces=True, vk_packet=False)
    return f"Pressed {keys}" + (f" {times} times." if times and times > 1 else ".")
