"""Keyboard shortcuts per app, so the AI uses a shortcut (instant) instead of the mouse (slow).

Only the sheet for the app in front is sent with a request (every word costs tokens); the
Windows and text-editing sheets only when the request is about those. Written in press_key's
notation.
"""

import re

WINDOWS = ("switch app alt+tab; show desktop win+d; minimize all win+m; file explorer win+e; run win+r; "
           "settings win+i; screenshot of an area win+shift+s; lock win+l; task manager ctrl+shift+esc; "
           "snap window win+left / win+right; maximize win+up; minimize win+down; clipboard history win+v; "
           "emoji win+.; virtual desktops win+ctrl+left/right; close window alt+f4")

_BROWSER = ("tab N ctrl+1..8, last tab ctrl+9; reopen closed tab ctrl+shift+t; address bar ctrl+l; "
            "find ctrl+f; zoom ctrl++ / ctrl+- / ctrl+0; history ctrl+h; downloads ctrl+j; bookmark ctrl+d; "
            "incognito ctrl+shift+n; page down space; top/bottom home / end")  # new/close tab etc.: browser tool

_YOUTUBE = ("play/pause k; back/forward 10 s j / l; back/forward 5 s left / right; mute m; full screen f; "
            "theatre t; captions c; faster/slower shift+. / shift+,; next video shift+n; previous shift+p; "
            "jump to 10%..90% 1..9, start 0; search box /")

_EXPLORER = ("address bar alt+d or ctrl+l; search ctrl+e; new folder ctrl+shift+n; rename f2; up a folder alt+up; "
             "back alt+left; select all ctrl+a; copy/cut/paste ctrl+c / ctrl+x / ctrl+v; properties alt+enter; "
             "new window ctrl+n; open enter")

_VSCODE = ("command palette ctrl+shift+p; quick open file ctrl+p; go to line ctrl+g; find ctrl+f; replace ctrl+h; "
           "save ctrl+s; select line ctrl+l; select down/up shift+down / shift+up; delete line ctrl+shift+k; "
           "comment line ctrl+/; new line below ctrl+enter; move line alt+up / alt+down; start/end of line "
           "home / end; start/end of file ctrl+home / ctrl+end; undo/redo ctrl+z / ctrl+y; terminal ctrl+`; "
           "sidebar ctrl+b; close editor ctrl+w; next editor ctrl+tab; format shift+alt+f")

_OFFICE = ("save ctrl+s; bold/italic/underline ctrl+b / ctrl+i / ctrl+u; select all ctrl+a; find ctrl+f; "
           "replace ctrl+h; undo/redo ctrl+z / ctrl+y; print ctrl+p; new ctrl+n; start/end of document ctrl+home / "
           "ctrl+end; select word ctrl+shift+right; heading 1/2 ctrl+alt+1 / ctrl+alt+2 (Word); new slide ctrl+m "
           "(PowerPoint); next sheet ctrl+pagedown (Excel)")

_NOTEPAD = "save ctrl+s; find ctrl+f; replace ctrl+h; go to line ctrl+g; select all ctrl+a; new tab ctrl+t"

_TEXT = ("in any text box: select all ctrl+a; start/end of line home / end; select to line end shift+end; "
         "word left/right ctrl+left / ctrl+right; delete word ctrl+backspace")

_BY_PROCESS = {
    "chrome": _BROWSER, "msedge": _BROWSER, "brave": _BROWSER, "opera": _BROWSER, "firefox": _BROWSER,
    "explorer": _EXPLORER, "code": _VSCODE, "winword": _OFFICE, "excel": _OFFICE, "powerpnt": _OFFICE,
    "notepad": _NOTEPAD,
}


# The Windows and text sheets go along only when the request is about those things (tokens).
_WINDOWS_WORDS = re.compile(r"\b(window|windows|desktop|screenshot|snip|lock|switch|snap|minimi[sz]e|maximi[sz]e|"
                            r"clipboard|emoji|task manager|settings|explorer|run|virtual)\b")
_TEXT_WORDS = re.compile(r"\b(type|write|text|select|delete|erase|word|words|line|lines|paragraph|cursor|copy|"
                         r"paste|cut|undo)\b")


def for_window(front: str, request: str = "") -> str:
    """The shortcut lines for the front window ("chrome: lofi - YouTube - Google Chrome")."""
    process, _, title = (front or "").partition(":")
    words = (request or "").lower()
    lines = []
    sheet = _BY_PROCESS.get(process.strip().lower().removesuffix(".exe"))
    if sheet:
        lines.append(f"{process.strip()} shortcuts: {sheet}")
    if "youtube" in title.lower():
        lines.append(f"YouTube player shortcuts: {_YOUTUBE}")
    if _TEXT_WORDS.search(words):
        lines.append(f"Text: {_TEXT}")
    if not sheet or _WINDOWS_WORDS.search(words):
        lines.append(f"Windows shortcuts: {WINDOWS}")
    return "\n".join(lines)
