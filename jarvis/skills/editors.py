"""The code editor in front, as one interface: BlueJ (Java) and VS Code (C++ and anything else).

Mapped live on 30 Sep:
  BlueJ   the editor window is "<Class> - <project>" (javaw). Its text box shows the WHOLE code to UI Automation
          (TextPattern), so every edit is checked by reading the code back. Ctrl+L = go to line (a small
          "Go to line" window), F8 = comment, F7 = uncomment, the "Compile" button compiles and a status line says
          "Class compiled - no syntax errors" (or the error). The project window "BlueJ:  <project>" shows each class
          as a button "<Class> Class: Compiled"; double-click it to open its editor; its right-click menu has
          "void main(String[] args)" (then OK) to run, and the output appears in "BlueJ: Terminal Window - …".
          That menu also has "Delete": never clicked (29 Sep, a misaimed double-click opened its confirmation).
  VS Code the editor isn't shown to UI Automation; checks read the current line by copying it (Ctrl+C with nothing
          selected copies the whole line), and the user's clipboard is put back. Ctrl+G = go to line,
          Ctrl+K Ctrl+C / Ctrl+K Ctrl+U = add / remove line comment.
Code is put in by pasting (typing "{" would make the editor add its own "}"), with the line's indentation.
"""

import logging
import re
import time

import win32clipboard as cb
import win32gui

from . import desktop, keys

log = logging.getLogger(__name__)

CURSOR = "‸"  # where the cursor goes after inserting a block ("for …{ ‸ }")


# ---- clipboard (VS Code's line checks) ----------------------------------------------------------------------

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
    """The selection, or the current line when nothing is selected (VS Code). Waits for Windows to say the
    clipboard changed (30 Sep: VS Code writes it late); the user's clipboard is given back."""
    before = _clip_get()
    seq = cb.GetClipboardSequenceNumber()
    keys.press("ctrl+c")
    deadline = time.monotonic() + 1.5
    while cb.GetClipboardSequenceNumber() == seq and time.monotonic() < deadline:
        time.sleep(0.03)
    time.sleep(0.05)
    text = (_clip_get() or "") if cb.GetClipboardSequenceNumber() != seq else ""
    _clip_set(before)
    return text


def _paste(text: str) -> bool:
    before = _clip_get()
    _clip_set(text)
    seq = cb.GetClipboardSequenceNumber()
    keys.press("ctrl+v")
    time.sleep(0.25)
    _clip_set(before)
    return cb.GetClipboardSequenceNumber() != seq


def _is_comment(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and all(re.match(r"\s*(//|#|--|/\*)", ln) for ln in lines)


def _none_commented(text: str) -> bool:
    return not any(re.match(r"\s*(//|#|--|/\*)", ln) for ln in text.splitlines() if ln.strip())


def _indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


# ---- the editors ---------------------------------------------------------------------------------------------

class Editor:
    name = "editor"
    lang = "java"

    def go_to_line(self, n: int) -> str: raise NotImplementedError
    def line(self) -> str: raise NotImplementedError             # the current line's text
    def text(self) -> str | None: return None                     # the whole code, when it can be read
    def compile(self) -> str: return "Not done: compiling isn't set up for this editor."
    def run(self) -> str: return "Not done: running isn't set up for this editor."

    def select_lines(self, first: int, last: int):
        self.go_to_line(first)
        keys.press("home")
        keys.press("home")  # to column 1 (the first Home stops at the indent)
        if last > first:
            keys.press("shift+down", last - first)
        keys.press("shift+end")

    def comment(self, span: tuple[int, int] | None, want: bool) -> str:
        if span:
            self.select_lines(*span)
        many = bool(span and span[1] > span[0])
        where = (f"line {span[0]}" if not many else f"lines {span[0]} to {span[1]}") if span else "the line"
        done = _is_comment if want else _none_commented
        now = self._selected_text(span)
        if done(now):
            self._drop_selection()
            return (f"{where[0].upper() + where[1:]} {'are' if many else 'is'} already "
                    f"{'commented' if want else 'not commented'}.")
        self._comment_keys(want, mixed=want and not _none_commented(now))
        deadline = time.monotonic() + 1.5
        while True:  # the editor applies it a moment later
            time.sleep(0.2)
            if done(self._selected_text(span)):
                break
            if time.monotonic() >= deadline:
                return f"Not done: {where} didn't change. Is it a code file?"
        self._drop_selection()
        return f"{'Commented' if want else 'Uncommented'} {where}."

    def insert(self, code: str) -> str:
        """Put code in at the cursor's line: on it if it's blank, else on a new line below; each line gets the
        indentation there. A CURSOR mark says where the cursor ends up (inside a new block)."""
        current = self.line()
        if current.strip():
            keys.press("end")
            keys.press("enter")
            time.sleep(0.15)
            current = self.line()
        indent = _indent_of(current.rstrip("\r\n"))
        keys.press("end")
        lines = code.split("\n")
        text = lines[0] + "".join("\n" + (indent + ln if ln.strip() or CURSOR in ln else "") for ln in lines[1:])
        up = 0
        if CURSOR in text:
            after = text.split(CURSOR, 1)[1]
            up = after.count("\n")
            text = text.replace(CURSOR, "")
        # the blank line may hold stray spaces: select from the indent to the end and replace it
        keys.press("home")
        keys.press("shift+end")
        if not _paste(indent + text):
            return "Not done: I couldn't put the code in (the clipboard is busy)."
        time.sleep(0.2)
        if up:
            keys.press("up", up)
            keys.press("end")
        return "ok"

    def move_into(self, name: str) -> str:
        """Put the cursor inside a method/function/loop ("move the cursor inside the main method"): at the end of
        the line with its opening brace, so the next code goes on the line below, inside it."""
        text = self.text()
        if text is not None:  # BlueJ: find it in the code
            lines = text.split("\n")
            pat = re.compile(rf"\b{re.escape(name)}\s*\(" if name not in ("for", "while", "if") else rf"\b{name}\s*\(")
            for i, ln in enumerate(lines):
                if pat.search(ln):
                    for j in range(i, min(i + 3, len(lines))):
                        if "{" in lines[j]:
                            self.go_to_line(j + 1)
                            keys.press("end")
                            return "ok"
            return f"Not done: there's no {name} in this code."
        # VS Code: its own find box, then to the end of that line
        keys.press("ctrl+f")
        time.sleep(0.3)
        keys.press("ctrl+a")
        desktop.type_text(f"{name}(")
        keys.press("enter")
        time.sleep(0.2)
        keys.press("escape")
        keys.press("end")
        return "ok"

    def exit_block(self) -> str:
        """Put the cursor after the closing brace of the block it's in ("come out of the loop")."""
        here = self.line().rstrip("\r\n")
        depth = len(_indent_of(here)) if here.strip() else len(here)
        for _ in range(60):
            keys.press("down")
            time.sleep(0.03)
            ln = self.line().rstrip("\r\n")
            if ln.strip().startswith("}") and len(_indent_of(ln)) < depth:
                keys.press("end")
                return "ok"
        return "Not done: I couldn't find the end of this block."

    # per editor
    def _selected_text(self, span) -> str: raise NotImplementedError
    def _comment_keys(self, want: bool, mixed: bool): raise NotImplementedError
    def _drop_selection(self): keys.press("escape")


class VSCode(Editor):
    name = "VS Code"

    def __init__(self, title: str):
        self.title = title
        self.lang = "java" if ".java" in title.lower() else ("python" if ".py " in title.lower() + " " else "cpp")

    def go_to_line(self, n: int) -> str:
        keys.press("ctrl+g")
        time.sleep(0.25)
        desktop.type_text(str(n))
        keys.press("enter")
        time.sleep(0.2)
        return f"On line {n}."

    def line(self) -> str:
        keys.press("escape")  # nothing selected: Ctrl+C copies the whole line
        return _copied()

    def _selected_text(self, span) -> str:
        return _copied()

    def _comment_keys(self, want: bool, mixed: bool):
        if mixed:
            keys.press("ctrl+k ctrl+u")  # some already commented: clear first, so none end up "// //"
            time.sleep(0.2)
        keys.press("ctrl+k ctrl+c" if want else "ctrl+k ctrl+u")


class BlueJ(Editor):
    name = "BlueJ"
    lang = "java"

    def __init__(self, title: str):
        self.title = title
        self.cls, _, self.project = title.partition(" - ")

    def _tp(self):
        UIA, uia = desktop._uia()
        el = uia.GetFocusedElement()
        p = el.GetCurrentPattern(UIA.UIA_TextPatternId) if el else None
        return (UIA, p.QueryInterface(UIA.IUIAutomationTextPattern)) if p else (UIA, None)

    def text(self) -> str | None:
        _, tp = self._tp()
        return tp.DocumentRange.GetText(-1) if tp else None

    def caret_line(self) -> int | None:
        UIA, tp = self._tp()
        if not tp:
            return None
        caret = tp.GetSelection().GetElement(0)
        before = tp.DocumentRange.Clone()
        before.MoveEndpointByRange(UIA.TextPatternRangeEndpoint_End, caret, UIA.TextPatternRangeEndpoint_Start)
        return before.GetText(-1).count("\n") + 1

    def line(self) -> str:
        text, n = self.text(), self.caret_line()
        if text is None or n is None:
            return ""
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else ""

    def go_to_line(self, n: int) -> str:
        keys.press("ctrl+l")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            time.sleep(0.15)
            if win32gui.GetWindowText(win32gui.GetForegroundWindow()) == "Go to line":
                break
        else:
            return "Not done: BlueJ's Go to line box didn't open."
        desktop.type_text(str(n))
        keys.press("enter")
        time.sleep(0.4)
        now = self.caret_line()
        return f"On line {n}." if now == n else f"Not done: the cursor is on line {now}."

    def _selected_text(self, span) -> str:
        text = self.text() or ""
        lines = text.split("\n")
        if span:
            return "\n".join(lines[span[0] - 1:span[1]])
        n = self.caret_line() or 1
        return lines[n - 1] if n <= len(lines) else ""

    def _comment_keys(self, want: bool, mixed: bool):
        if mixed:
            keys.press("f7")
            time.sleep(0.2)
        keys.press("f8" if want else "f7")

    def _drop_selection(self):
        keys.press("end")  # drop the selection, staying on the line (Right moved to the next line; Escape can close things)

    def _status(self) -> list[str]:
        UIA, uia = desktop._uia()
        root = uia.ElementFromHandle(win32gui.GetForegroundWindow())
        f = root.FindAll(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
            UIA.UIA_ControlTypePropertyId, UIA.UIA_TextControlTypeId))
        return [f.GetElement(i).CurrentName or "" for i in range(f.Length)]

    def compile(self) -> str:
        UIA, uia = desktop._uia()
        root = uia.ElementFromHandle(win32gui.GetForegroundWindow())
        btn = root.FindFirst(UIA.TreeScope_Descendants, uia.CreateAndCondition(
            uia.CreatePropertyCondition(UIA.UIA_NamePropertyId, "Compile"),
            uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_ButtonControlTypeId)))
        if not btn:
            return "Not done: there's no Compile button here."
        old = set(self._status())
        btn.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            time.sleep(0.4)
            for t in self._status():
                low = t.lower()
                if "compiled - no syntax errors" in low and (t not in old or time.monotonic() > deadline - 13):
                    return f"{self.cls} compiled with no errors."
                if ("error" in low or "expected" in low or "cannot find" in low) and "no syntax errors" not in low:
                    return f"{self.cls} has an error: {t[:160]}"
        return "Not done: I couldn't see the compile result."

    def run(self) -> str:
        """Compile first (BlueJ only offers main for a compiled class), then run main."""
        compiled = self.compile()
        if not compiled.endswith("compiled with no errors."):
            return compiled if compiled.startswith("Not done") else f"Not run: {compiled}"
        return run_main(self.cls, self.project)


# ---- BlueJ's project window: open a class, run main ------------------------------------------------------------

def _project_window(project: str | None = None):
    for hwnd, proc, title in desktop._app_windows():
        if proc.startswith("java") and title.startswith("BlueJ:") and "Terminal" not in title and \
                (not project or title.split(":", 1)[1].strip() == project.strip()):
            return hwnd, title.split(":", 1)[1].strip()
    return None, None


def _class_buttons(hwnd):
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd)
    btns = root.FindAll(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_ButtonControlTypeId))
    out = []
    for i in range(btns.Length):
        e = btns.GetElement(i)
        m = re.match(r"^(\w+) Class", e.CurrentName or "")
        if m:
            out.append((m.group(1), e))
    return out


def _find_class(hwnd, said: str):
    from rapidfuzz import fuzz
    want = re.sub(r"[^a-z0-9]", "", said.lower())
    best, score = None, 0
    for name, el in _class_buttons(hwnd):
        s = fuzz.ratio(want, name.lower())
        if s > score:
            best, score = (name, el), s
    return best if score >= 75 else None


def _centre_click(el, button="left", double=False):
    from . import mouse
    r = el.CurrentBoundingRectangle
    sw, sh = mouse.screen_size()
    mouse.click((r.left + r.right) / 2 / (sw - 1) * 1000, (r.top + r.bottom) / 2 / (sh - 1) * 1000, button, double)


def open_class(said: str) -> str:
    hwnd, project = _project_window()
    if not hwnd:
        return "Not done: no BlueJ project is open."
    desktop._focus(hwnd)
    time.sleep(0.4)
    hit = _find_class(hwnd, said)
    if not hit:
        names = ", ".join(n for n, _ in _class_buttons(hwnd)) or "none"
        return f"Not done: there's no class like {said} in {project}. Classes: {names}."
    name, el = hit
    _centre_click(el, double=True)  # exactly on the class's own box (29 Sep: a guessed spot hit the menu)
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        time.sleep(0.25)
        if desktop.front_window().startswith(f"javaw: {name} - "):
            return f"Opened {name}."
    return f"Not done: {name}'s editor didn't open."


def class_name(said: str) -> str | None:
    """'motivation' -> 'Motivation', 'digit sum check' -> 'DigitSumCheck'; None if it can't be a Java class name."""
    words = re.findall(r"[A-Za-z0-9]+", said)
    name = "".join(w[:1].upper() + w[1:] for w in words)
    return name if re.fullmatch(r"[A-Z][A-Za-z0-9]{0,40}", name or "") else None


def new_class(said: str) -> str:
    """BlueJ: New Class..., type the name, OK, and check the class box appears (30 Sep: the agent couldn't type
    into the dialog, and the user was stuck four times)."""
    name = class_name(said)
    if not name:
        return f"Not done: {said!r} can't be a class name. Say a name like Motivation."
    hwnd, project = _project_window()
    if not hwnd:
        return "Not done: no BlueJ project is open."
    if any(n == name for n, _ in _class_buttons(hwnd)):
        return f"There's already a class called {name} in {project}."
    desktop._focus(hwnd)
    time.sleep(0.4)
    UIA, uia = desktop._uia()
    found = uia.ElementFromHandle(hwnd).FindAll(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
        UIA.UIA_NamePropertyId, "New Class..."))
    if not found.Length:
        return "Not done: I can't find BlueJ's New Class button."
    _centre_click(found.GetElement(0))
    deadline = time.monotonic() + 3
    dialog = None
    while time.monotonic() < deadline:
        time.sleep(0.2)
        front = win32gui.GetForegroundWindow()
        if front != hwnd and any(h == front and p.startswith("java") for h, p, _ in desktop._app_windows()):
            dialog = front
            break
    if not dialog:
        return "Not done: BlueJ's New Class box didn't open."
    time.sleep(0.3)  # its name box takes the cursor as it opens
    if win32gui.GetForegroundWindow() != dialog:
        return "Not done: BlueJ's New Class box lost the focus, so I didn't type."
    desktop.type_text(name)
    time.sleep(0.2)
    keys.press("enter")  # OK is the default button
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        time.sleep(0.3)
        if any(n == name for n, _ in _class_buttons(hwnd)):
            return f"Created the class {name}."
    if win32gui.GetForegroundWindow() == dialog:
        return f"Not done: BlueJ's New Class box is still open; it may not accept the name {name}."
    return f"Not done: I don't see the class {name} in {project}."


def run_main(cls: str, project: str | None = None) -> str:
    UIA, uia = desktop._uia()
    hwnd, project = _project_window(project)
    if not hwnd:
        return "Not done: no BlueJ project is open."
    desktop._focus(hwnd)
    time.sleep(0.4)
    hit = _find_class(hwnd, cls)
    if not hit:
        return f"Not done: there's no class {cls} in {project}."
    name, el = hit
    _centre_click(el, "right")
    time.sleep(0.8)
    menu = uia.ElementFromHandle(win32gui.GetForegroundWindow()).FindAll(
        UIA.TreeScope_Descendants, uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId,
                                                               UIA.UIA_MenuItemControlTypeId))
    main = next((menu.GetElement(i) for i in range(menu.Length)
                 if (menu.GetElement(i).CurrentName or "").startswith("void main(")), None)
    if not main:
        keys.press("escape")
        return f"Not done: {name} has no main method to run (compile it first?)."
    main.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:  # "Method Call" window: OK
        time.sleep(0.25)
        fg = win32gui.GetForegroundWindow()
        if "Method Call" in win32gui.GetWindowText(fg):
            ok = uia.ElementFromHandle(fg).FindFirst(UIA.TreeScope_Descendants, uia.CreateAndCondition(
                uia.CreatePropertyCondition(UIA.UIA_NamePropertyId, "OK"),
                uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_ButtonControlTypeId)))
            if ok:
                ok.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
            break
    time.sleep(1.5)
    out = terminal_text(project)
    if out is None:
        return f"Running {name}."
    shown = [ln for ln in out.splitlines() if ln.strip()]
    return f"Running {name}. It printed: {' / '.join(shown[-4:])[:200]}" if shown else \
        f"Running {name}. Nothing printed yet (it may be waiting for input in the terminal)."


def terminal_text(project: str) -> str | None:
    UIA, uia = desktop._uia()
    term = next((h for h, p, t in desktop._app_windows() if p.startswith("java") and "Terminal Window" in t
                 and project in t), None)
    if not term:
        return None
    f = uia.ElementFromHandle(term).FindAll(UIA.TreeScope_Descendants, uia.CreateTrueCondition())
    for i in range(f.Length):
        tp = f.GetElement(i).GetCurrentPattern(UIA.UIA_TextPatternId)
        if tp:
            text = tp.QueryInterface(UIA.IUIAutomationTextPattern).DocumentRange.GetText(4000)
            if "Can only enter input" not in text:
                return text
    return ""


def current() -> Editor | None:
    front = desktop.front_window()
    proc, _, title = front.partition(": ")
    if proc == "code":
        return VSCode(title)
    if proc.startswith("javaw") and " - " in title and not title.startswith("BlueJ"):
        return BlueJ(title)
    return None
