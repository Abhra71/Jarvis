"""Turns a transcript like 'set volume to 40' into Intent('set_volume', {'level': 40})."""

import re
from dataclasses import dataclass, field


@dataclass
class Intent:
    name: str
    slots: dict = field(default_factory=dict)


_UNITS = {
    "zero": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


_TIME_UNITS = {"hour", "hours", "minute", "minutes", "second", "seconds"}


def words_to_digits(text: str) -> str:
    """'twenty five minutes' -> '25 minutes', 'a minute' -> '1 minute', 'a hundred' -> '100'."""
    words = text.split()
    out, num = [], None
    for i, word in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if word in ("a", "an") and nxt not in _TIME_UNITS and nxt != "hundred":
            word_value = None  # just an article
        elif word in _TENS:
            word_value = _TENS[word]
        elif word in _UNITS:
            word_value = _UNITS[word]
        elif word == "hundred":
            num = (num or 1) * 100
            continue
        else:
            word_value = None

        if word_value is not None:
            num = (num or 0) + word_value
            continue
        if num is not None:
            out.append(str(num))
            num = None
        out.append(word)
    if num is not None:
        out.append(str(num))
    return " ".join(out)


_FILLER = re.compile(r"^(hey |ok |okay )?(jarvis[, ]*)?(please |can you |could you |would you )*")
_DURATION = re.compile(r"(\d+)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b")
_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}


def normalize(text: str) -> str:
    text = text.lower().replace("%", " percent")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\bdot (com|org|net|in|io|live|co|ai|dev)\b", r"\1", text)  # "chess dot com" -> "chess com"
    text = re.sub(r"\byou tube\b", "youtube", text)
    text = words_to_digits(text)
    text = _FILLER.sub("", text)
    text = re.sub(r"\s*\bplease$", "", text)
    return text.strip()


def parse_duration(text: str) -> int | None:
    total = 0
    for amount, unit in _DURATION.findall(text):
        total += int(amount) * _UNIT_SECONDS[unit[0]]
    if "half an hour" in text:
        total += 1800
    return total or None


# Everyday commands that are one shortcut on the window in front: instant, no AI. They work the same in
# browsers, File Explorer, VS Code and most apps. (Checked before "open X", so "open a new tab" lands here.)
_SHORTCUTS = [
    (r"(open )?(a )?new tab", "ctrl+t", "New tab."),
    (r"close (this |the |current )?tab", "ctrl+w", "Closed the tab."),
    (r"(reopen|restore|bring back) (the )?(last |closed |last closed )?tab", "ctrl+shift+t", "Reopened the tab."),
    (r"(go to |switch to )?(the )?next tab", "ctrl+tab", "Next tab."),
    (r"(go to |switch to )?(the )?previous tab", "ctrl+shift+tab", "Previous tab."),
    (r"(go )?back", "alt+left", "Went back."),
    (r"(go )?forward", "alt+right", "Went forward."),
    (r"(reload|refresh)( (the |this )?page)?", "f5", "Reloaded."),
    (r"zoom in", "ctrl++", "Zoomed in."),
    (r"zoom out", "ctrl+-", "Zoomed out."),
    (r"(reset|normal) zoom", "ctrl+0", "Zoom reset."),
    (r"copy( (that|this|it))?", "ctrl+c", "Copied."),
    (r"paste( (that|this|it|here))?", "ctrl+v", "Pasted."),
    (r"cut( (that|this|it))?", "ctrl+x", "Cut."),
    (r"undo( (that|it))?", "ctrl+z", "Undone."),
    (r"redo( (that|it))?", "ctrl+y", "Redone."),
    (r"select (all|everything)", "ctrl+a", "Selected everything."),
    (r"save( (it|this|that|the file))?", "ctrl+s", "Saved."),
    (r"(switch|change) (window|windows|app|apps)|alt tab", "alt+tab", "Switched."),
    (r"(show|go to) (the )?desktop|minimi[sz]e (everything|all( windows)?)", "win+d", "Here's the desktop."),
    (r"(take a |take )?screenshot|snip( it)?|(screen|area) snip", "win+shift+s", "Drag over the area to snip."),
    (r"(open )?(the )?clipboard( history)?", "win+v", "Here's the clipboard history."),
    (r"find on (this )?page|find in (this )?page", "ctrl+f", "Find is open."),
]
_SHORTCUTS = [(re.compile(f"^(?:{p})$"), k, r) for p, k, r in _SHORTCUTS]
_SPOKEN_KEYS = {"control": "ctrl", "ctrl": "ctrl", "shift": "shift", "alt": "alt", "windows": "win",
                "window": "win", "win": "win", "escape": "esc", "enter": "enter", "return": "enter",
                "page up": "pageup", "page down": "pagedown", "plus": "plus", "minus": "minus"}
_MODIFIER_WORDS = {"ctrl", "shift", "alt", "win"}


def _spoken_combo(words: str) -> str:
    """'control shift t' -> 'ctrl+shift+t'; 'alt f4' -> 'alt+f4'; 'enter' -> 'enter'."""
    for spoken in ("page up", "page down"):
        words = words.replace(spoken, spoken.replace(" ", ""))
    presses, current = [], []
    for w in words.split():
        w = _SPOKEN_KEYS.get(w, w)
        current.append(w)
        if w not in _MODIFIER_WORDS:
            presses.append("+".join(current))
            current = []
    if current:
        presses.append("+".join(current))
    return " ".join(presses)


def _shortcut(text: str) -> tuple[str, str] | None:
    for pattern, keys, reply in _SHORTCUTS:
        if pattern.match(text):
            return keys, reply
    m = re.match(r"^(?:press|hit|use the shortcut|use shortcut)\s+(?:the\s+)?(.+?)(?:\s+(?:key|keys|shortcut))?$", text)
    if m:
        combo = _spoken_combo(m.group(1))
        return combo, f"Pressed {combo}."
    return None


def parse(raw: str) -> Intent | None:
    text = normalize(raw)
    if not text:
        return None

    # Jarvis's own AI status (works offline)
    if re.search(r"\b(open|show)\b.*\b(dashboard|status page)\b", text):
        return Intent("open_dashboard")
    # Only short questions about Jarvis's own AI: on 27 Sep "…only Google and Groq AI services are used"
    # (an instruction for a file) matched and read the status out instead.
    if len(text.split()) <= 8 and (
            re.search(r"\b(ai|model|models)\b.*\b(status|usage|using|used|left|limit|limits)\b", text)
            or re.search(r"\bwhich (ai|model)\b", text)) or text in ("status", "ai status", "jarvis status"):
        return Intent("ai_status")

    # Timer
    if re.search(r"\b(cancel|stop|clear)\b.*\btimers?\b", text):
        return Intent("cancel_timer")
    if "timer" in text or text.startswith("remind me in"):
        return Intent("set_timer", {"seconds": parse_duration(text)})

    # Volume
    if re.search(r"\bunmute\b", text):
        return Intent("mute", {"on": False})
    if re.search(r"\bmute\b", text):
        return Intent("mute", {"on": True})
    if "volume" in text or "sound" in text or text in ("louder", "quieter"):
        level = re.search(r"\b(\d{1,3})\b", text)
        if level:
            return Intent("set_volume", {"level": min(int(level.group(1)), 100)})
        if re.search(r"\b(up|increase|raise|louder|higher)\b", text):
            return Intent("change_volume", {"direction": 1})
        if re.search(r"\b(down|decrease|lower|reduce|quieter)\b", text):
            return Intent("change_volume", {"direction": -1})
        if re.search(r"\b(max|maximum|full)\b", text):
            return Intent("set_volume", {"level": 100})

    # Keyboard shortcuts on the window in front, like a person would press them.
    shortcut = _shortcut(text)
    if shortcut:
        return Intent("shortcut", {"keys": shortcut[0], "reply": shortcut[1]})

    # Web search
    m = re.match(r"^(?:search(?: google)?(?: for)?|google|look up)\s+(.+?)(?:\s+on google)?$", text)
    if m:
        return Intent("web_search", {"query": m.group(1)})

    # Chrome profile: "open the third account", "open chrome work profile", "switch to my misc profile"
    m = re.match(r"^(?:open|launch|start|switch to)\s+(?:google\s+)?(?:chrome\s+)?(?:(?:in|with|on)\s+)?"
                 r"(?:the\s+|my\s+)?(.+?)\s+(?:chrome\s+)?(?:profile|account)$", text)
    if m and not re.search(r"\b(in|on|and|then)\b", m.group(1)):
        return Intent("open_profile", {"profile": m.group(1)})

    # Open app
    m = re.match(r"^(?:open|launch|start|run)\s+(?:the\s+)?(.+?)(?:\s+app)?$", text)
    if m:
        return Intent("open_app", {"app": m.group(1)})

    # Time (small freebie)
    if re.search(r"\bwhat( s|s| is)? the time\b|\bwhat time is it\b", text):
        return Intent("tell_time")

    return None
