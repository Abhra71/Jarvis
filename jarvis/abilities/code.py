"""Voice coding in VS Code: "go to line 40", "comment line 40", "comment lines 10 to 15", "uncomment this",
"select line 12", "open file main.cpp", "save the file". Keys, like a person, and every edit is checked.

VS Code doesn't show its editor to UI Automation, so checks read the line itself: with nothing selected, Ctrl+C
copies the whole current line (VS Code's default), and the user's clipboard is put back afterwards.
"""

import re
import time

import win32clipboard as cb

from . import ability
from ..skills import desktop, keys

_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
            "fifty": 50, "hundred": 100}


def _in_vscode() -> bool:
    return desktop.front_window().lower().startswith("code:")


def _num(s: str) -> int:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    total = 0
    for w in s.replace("-", " ").split():
        if w not in _NUMBERS:
            raise ValueError(f"not a line number: {s!r}")
        total += _NUMBERS[w]
    return total


def _clip_get():
    try:
        cb.OpenClipboard()
        try:
            return cb.GetClipboardData(cb.CF_UNICODETEXT) if cb.IsClipboardFormatAvailable(cb.CF_UNICODETEXT) else None
        finally:
            cb.CloseClipboard()
    except Exception:
        return None


def _clip_set(text):
    for _ in range(4):
        try:
            cb.OpenClipboard()
            try:
                cb.EmptyClipboard()
                if text is not None:
                    cb.SetClipboardText(text, cb.CF_UNICODETEXT)
            finally:
                cb.CloseClipboard()
            return
        except Exception:
            time.sleep(0.1)


def _copied() -> str:
    """The selection, or the current line when nothing is selected; the clipboard is given back.
    Waits for Windows to say the clipboard changed (30 Sep: VS Code writes it late, and an early read saw an
    older line)."""
    before = _clip_get()
    seq = cb.GetClipboardSequenceNumber()
    keys.press("ctrl+c")
    deadline = time.monotonic() + 1.5
    while cb.GetClipboardSequenceNumber() == seq and time.monotonic() < deadline:
        time.sleep(0.03)
    time.sleep(0.05)
    text = _clip_get() or "" if cb.GetClipboardSequenceNumber() != seq else ""
    _clip_set(before)
    return text


def _go(line: int):
    keys.press("ctrl+g")
    time.sleep(0.25)
    desktop.type_text(str(line))
    keys.press("enter")
    time.sleep(0.2)


def _select(first: int, last: int):
    _go(first)
    keys.press("home")
    keys.press("home")  # to column 1 (the first Home stops at the indent)
    if last > first:
        keys.press("shift+down", last - first)
    keys.press("shift+end")


def _need_vscode():
    if not _in_vscode():
        raise ValueError("VS Code isn't in front")


def _is_comment(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and all(re.match(r"\s*(//|#|--|/\*)", ln) for ln in lines)


@ability("code_go_to_line", "VS Code: go to a line",
         r"(?:go|jump|move|take me) to line (?:number )?(?P<value>[\w -]+)", value="n")
def go_to_line(value: str):
    _need_vscode()
    n = _num(value)
    _go(n)
    return f"On line {n}."


_LINES = r"(?:lines? (?:number )?(?P<value>[\w -]+?(?: (?:to|through|till|until) [\w -]+)?)|(?P<here>this|it|this line|that))"


def _range(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    parts = re.split(r" (?:to|through|till|until) ", value)
    first = _num(parts[0])
    last = _num(parts[1]) if len(parts) > 1 else first
    return (first, last) if last >= first else (last, first)


def _none_commented(text: str) -> bool:
    return not any(re.match(r"\s*(//|#|--|/\*)", ln) for ln in text.splitlines() if ln.strip())


def _toggle_comment(value: str | None, want: bool) -> str:
    """Add or remove line comments: VS Code's explicit commands (Ctrl+K Ctrl+C / Ctrl+K Ctrl+U), not the toggle,
    so lines that are partly commented end up all one way (30 Sep: the toggle on 10-12 with 11 plain went wrong)."""
    _need_vscode()
    span = _range(value)
    if span:
        _select(*span)
    many = bool(span and span[1] > span[0])
    where = (f"line {span[0]}" if not many else f"lines {span[0]} to {span[1]}") if span else "the line"
    done = _is_comment if want else _none_commented
    now = _copied()
    if done(now):
        keys.press("escape")
        return f"{where[0].upper() + where[1:]} {'are' if many else 'is'} already {'commented' if want else 'not commented'}."
    if want and not _none_commented(now):
        keys.press("ctrl+k ctrl+u")  # some already commented: clear first, so none end up "// //"
        time.sleep(0.2)
    keys.press("ctrl+k ctrl+c" if want else "ctrl+k ctrl+u")
    deadline = time.monotonic() + 1.2
    while True:  # VS Code applies it a moment later (30 Sep: a check at 0.25 s saw the old line)
        time.sleep(0.2)
        if done(_copied()):
            break
        if time.monotonic() >= deadline:
            return f"Not done: {where} didn't change. Is it a code file?"
    keys.press("escape")  # drop the selection
    return f"{'Commented' if want else 'Uncommented'} {where}."


@ability("code_comment", "VS Code: comment out a line or lines",
         rf"comment(?: out)? {_LINES}(?: out)?", value="n or n to m")
def comment(value: str | None = None):
    return _toggle_comment(None if value in ("this", "it", "this line", "that") else value, True)


@ability("code_uncomment", "VS Code: uncomment a line or lines",
         rf"un ?comment {_LINES}", value="n or n to m")
def uncomment(value: str | None = None):
    return _toggle_comment(None if value in ("this", "it", "this line", "that") else value, False)


@ability("code_select_lines", "VS Code: select a line or lines",
         r"select lines? (?:number )?(?P<value>[\w -]+?(?: (?:to|through|till|until) [\w -]+)?)", value="n or n to m")
def select_lines(value: str):
    _need_vscode()
    first, last = _range(value)
    _select(first, last)
    return f"Selected line {first}." if first == last else f"Selected lines {first} to {last}."


@ability("code_open_file", "VS Code: open a file of the project by name",
         r"open (?:the )?file (?!called |named )(?P<value>[\w .-]+?)(?: in (?:vs )?code)?", value="name")
def open_file(value: str):
    _need_vscode()
    name = re.sub(r" dot ", ".", value.strip())
    name = re.sub(r" (cpp|c|h|hpp|py|java|js|ts|txt|md|html|css|json)$", r".", name)  # "main cpp" -> main.cpp
    keys.press("ctrl+p")
    time.sleep(0.3)
    desktop.type_text(name)
    time.sleep(0.6)
    keys.press("enter")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if name.split(".")[0].lower() in desktop.front_window().lower():
            return f"Opened {name}."
    return f"Not done: there's no file like {name} in this project."
