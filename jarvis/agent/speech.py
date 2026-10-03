"""What Jarvis SAYS when something didn't work: short, plain words, like a person helping.

The checks explain failures in detail for the repair AI ("the page isn't https://www.clawedgame.com; it's
https://pw.live/?redirectUrl=study-v2%2Fstudy."). Read out loud that sounded like a log file (the user, 30 Sep).
These turn them into speech: no URLs, no process names, no item lists, one idea per sentence.
"""

import re
from urllib.parse import urlparse

_APP_NAMES = {"explorer": "File Explorer", "chrome": "Chrome", "msedge": "Edge", "code": "VS Code",
              "brave": "Brave", "notepad": "Notepad", "bluej": "BlueJ", "java": "BlueJ", "javaw": "BlueJ",
              "whatsapp": "WhatsApp", "claude": "Claude", "cmd": "Command Prompt", "windowsterminal": "Terminal",
              "applicationframehost": "Settings", "systemsettings": "Settings", "taskmgr": "Task Manager"}
_KEY_NAMES = {"win": "Windows", "ctrl": "Control", "alt": "Alt", "shift": "Shift", "esc": "Escape",
              "del": "Delete", "pgup": "Page Up", "pgdn": "Page Down", "enter": "Enter", "tab": "Tab",
              "space": "Space", "backspace": "Backspace", "up": "Up", "down": "Down", "left": "Left",
              "right": "Right", "home": "Home", "end": "End", "delete": "Delete"}
_URL = re.compile(r"https?://\S+?(?=[;,]?\s|[;,.]?$)|www\.\S+?(?=[;,]?\s|[;,.]?$)")


def site(url: str) -> str:
    """'https://www.pw.live/study?x=1' -> 'pw.live'."""
    u = url if "://" in url else "https://" + url
    host = urlparse(u).netloc.lower()
    return host[4:] if host.startswith("www.") else host or url


def app(name: str) -> str:
    """'explorer' -> 'File Explorer', 'the_brutal_revenge_not_ready' -> 'the brutal revenge not ready'."""
    n = name.strip().strip("'\"")
    return _APP_NAMES.get(n.lower(), n.replace("_", " "))


def keys(combo: str) -> str:
    """'win+up' -> 'Windows Up', 'alt+f4' -> 'Alt F4'."""
    parts = [p for p in re.split(r"[+\s]+", combo.strip().lower()) if p]
    return " ".join(_KEY_NAMES.get(p, p.upper() if re.fullmatch(r"f\d{1,2}|[a-z0-9]", p) else p) for p in parts)


def _sentence(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    s = s[0].upper() + s[1:]
    return s if s.endswith((".", "?", "!")) else s + "."


def problem(why: str) -> str:
    """One failure reason in plain words."""
    w = re.sub(r"^(Not done|Not clicked|Not allowed|Error|Sorry)[:,]?\s*", "", str(why).strip())
    w = w.split(" Current items:")[0].split(" Closest installed apps:")[0].strip()
    m = re.match(r"the page isn't (\S+?);? it's (.+?)\.?$", w)
    if m:
        want, got = site(m.group(1)), site(m.group(2)) if "://" in m.group(2) or "www." in m.group(2) else ""
        return _sentence(f"{want} didn't open" + (f"; I'm on {got}" if got and got != want else ""))
    m = re.match(r"(.+?) isn't in front; (.+?) is\.?$", w)
    if m:
        front = app(m.group(2))
        where = "" if front.lower() in ("nothing", "file explorer", "explorer") else f"; {front} is in front"
        return _sentence(f"{app(m.group(1))} didn't come up{where}")
    m = re.match(r"(.+?) (?:didn't open|isn't open)\.?$", w)
    if m:
        return _sentence(f"{app(m.group(1))} didn't open")
    m = re.match(r"(.+?) is still open\.?$", w)
    if m and not w.startswith("the dialog box"):
        return _sentence(f"{app(m.group(1))} didn't close")
    m = re.match(r"(.+?) is still there\.?$", w)
    if m:
        return _sentence(f"{m.group(1)} is still showing")
    m = re.match(r"Nothing called '(.+?)' is on screen\.?$", w, re.I)
    if m:
        return _sentence(f"I can't find {m.group(1)} on the screen")
    m = re.match(r"I can't see (.+?) on screen in (.+?)\.?$", w)
    if m:
        return _sentence(f"I can't see {m.group(1)} on the screen")
    m = re.match(r"the dialog box '(.+?)' is still open\.?$", w)
    if m:
        name = m.group(1)
        return "The box in front is still open." if name.lower() in ("a dialog box", "dialog") \
            else _sentence(f"The {name} box is still open")
    if re.match(r"A dialog box is open in front", w):
        return "There's a box open in front that needs an answer first."
    if w.startswith("the user didn't ask for more actions"):
        # 3 Oct live: the guard's note to the AI was read out word for word.
        return "That needed more steps than you asked for, so I stopped partway."
    if re.search(r"\b(the user|ask the user)\b", w, re.I):
        return "I stopped partway."  # any other note meant for the AI is never read out
    if w.startswith("the cursor isn't in a text box"):
        return "I couldn't get into a text box."
    if w.startswith("the media is still playing"):
        return "It's still playing."
    if w.startswith("nothing started playing"):
        return "Nothing started playing."
    m = re.match(r"(?:I )?couldn't find an app called (.+?)\.?$", w, re.I)
    if m:
        return _sentence(f"I couldn't find an app called {m.group(1)}")
    w = _URL.sub(lambda u: site(u.group(0)), w)
    return _sentence(w)


def stuck(why: str) -> str:
    """Stopped: what went wrong, and hand it back to the user."""
    return f"{problem(why)} What should I do?"


def unconfirmed(results: list[str]) -> str:
    """Done, but not seen to work: the last thing done, said honestly and briefly."""
    last = str(results[-1]).strip().rstrip(".") if results else ""
    m = re.fullmatch(r"Pressed (.+)", last)
    if m:
        did = f"I pressed {keys(m.group(1))}"
    elif re.fullmatch(r"Typed it|Typed", last):
        did = "I typed it"
    else:
        m = re.fullmatch(r"Clicked (?:the )?(.+?)(?: (?:button|link|menu item|tab|list item|item|checkbox))?", last)
        did = f"I clicked {m.group(1)}" if m else (last[0].lower() + last[1:] if last else "I did it")
        if not m and not did.lower().startswith("i "):
            did = _sentence(last).rstrip(".")
    if len(did) > 90:
        did = did[:90].rsplit(" ", 1)[0]
    return f"{did}, but I can't tell if it worked."
