"""Upload a file on a website: "upload my newest pdf", "upload the file called marksheet", "upload it".

Done like a person: if the page's file picker isn't open yet, click its upload / choose-file button; then in
Windows' "Open" window put the file's full path in the File name box and press Open, and check the window closed.
The file is found in code (Downloads, Documents, Desktop, Pictures), never guessed: nothing that matches means
"which file?". Secrets files are never picked. The site's own Submit / Send button stays the user's call.
"""

import re
import time

import win32gui

from . import ability
from .files import KINDS, _NEWEST, _plain, newest
from ..skills import desktop, elements, files

FOLDERS = ("Downloads", "Documents", "Desktop", "Pictures")
_UPLOAD_BUTTONS = re.compile(r"\b(upload|choose (a )?file|choose files|browse|select (a )?file|attach|add (a )?file)\b",
                             re.I)
_DIALOG_CLASS = "#32770"


def _file_dialog():
    """Windows' Open / File Upload window in front, or None."""
    hwnd = win32gui.GetForegroundWindow()
    if win32gui.GetClassName(hwnd) != _DIALOG_CLASS:
        return None
    title = win32gui.GetWindowText(hwnd).lower()
    return hwnd if any(w in title for w in ("open", "upload", "choose", "select", "file")) else None


def _wait_dialog(timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = _file_dialog()
        if hwnd:
            return hwnd
        time.sleep(0.2)
    return None


def find_file(said: str, folders=FOLDERS):
    """(the file meant, or None, why not). 'newest pdf' -> by kind and age; otherwise by name."""
    from pathlib import Path
    s = said.lower()
    p = Path(said.strip().strip('"'))
    if p.is_absolute() and p.is_file():
        return (None, "that file holds secrets") if files.is_secret(p.name) else (p, "")
    kind = re.search(rf"{_NEWEST} (\w+?)s?\b", s)
    if kind and kind.group(1) in KINDS:
        best = None
        for folder in folders:
            try:
                f = newest(folder, KINDS[kind.group(1)])
            except (OSError, PermissionError, ValueError):
                continue
            if f and (best is None or f.stat().st_mtime > best.stat().st_mtime):
                best = f
        return (best, "") if best else (None, f"there's no {kind.group(1)} in {', '.join(folders)}")
    want = _plain(re.sub(r"\b(my|the|a|file|called|named|document)\b", " ", s))
    if not want:
        return None, "which file?"
    from rapidfuzz import fuzz
    scored = []
    for folder in folders:
        try:
            base = files.resolve(folder)
            for f in base.iterdir():
                if f.is_file() and not f.name.startswith(("~$", ".")) and not files.is_secret(f.name):
                    scored.append((max(fuzz.token_set_ratio(want, _plain(f.name)), fuzz.ratio(want, _plain(f.name))), f))
        except (OSError, PermissionError, ValueError):
            continue
    scored.sort(key=lambda x: (-x[0], -x[1].stat().st_mtime))
    if not scored or scored[0][0] < 80:
        return None, f"I couldn't find a file called {want} in {', '.join(folders)}"
    return scored[0][1], ""


def _open_picker() -> int | None:
    """Click the page's upload / choose-file button and wait for Windows' Open window."""
    for el in elements.read_front():
        if el.kind in ("button", "link", "item") and _UPLOAD_BUTTONS.search(el.name):
            elements.click(el)
            return _wait_dialog(4.0)
    return None


def upload(path, hwnd: int | None = None) -> str:
    hwnd = hwnd or _file_dialog() or _open_picker()
    if not hwnd:
        return "Not done: no file picker is open, and I couldn't find an upload button on this page."
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd)
    box, deadline = None, time.monotonic() + 3.0
    while not box and time.monotonic() < deadline:  # the window builds its boxes a moment after it appears
        box = root.FindFirst(UIA.TreeScope_Descendants, uia.CreateAndCondition(
            uia.CreatePropertyCondition(UIA.UIA_AutomationIdPropertyId, "1148"),
            uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_EditControlTypeId)))
        if not box:
            time.sleep(0.2)
    if not box:
        return "Not done: the file window has no File name box."
    box.GetCurrentPattern(UIA.UIA_ValuePatternId).QueryInterface(UIA.IUIAutomationValuePattern).SetValue(str(path))
    time.sleep(0.2)
    open_btn = root.FindFirst(UIA.TreeScope_Children, uia.CreatePropertyCondition(UIA.UIA_AutomationIdPropertyId, "1"))
    if open_btn:
        open_btn.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
    else:
        from ..skills import keys
        keys.press("enter")
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return f"Chose {path.name} for upload."
    return f"Not done: the file window is still open (is {path.name} allowed here?)."


@ability("upload_file", "pick a file in a website's upload window (by name or 'newest pdf')",
         r"(?:upload|attach)(?: the| my| a)? (?:file )?(?:called |named )?(?P<value>.+?)"
         r"(?: here| to this (?:page|site|form))?",
         value="file")
def upload_file(said: str):
    front = desktop.front_window().lower()
    if not (_file_dialog() or front.startswith(("chrome", "msedge", "brave", "firefox"))):
        raise ValueError("no website or file window in front")
    f, why = find_file(said)
    if not f:
        return f"Not done: {why}. Say the file's name, or 'my newest PDF'."
    return upload(f)
