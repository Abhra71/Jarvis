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


def parse(raw: str) -> Intent | None:
    text = normalize(raw)
    if not text:
        return None

    # Jarvis's own AI status (works offline)
    if re.search(r"\b(open|show)\b.*\b(dashboard|status page)\b", text):
        return Intent("open_dashboard")
    if re.search(r"\b(ai|model|models)\b.*\b(status|usage|using|used|left|limit|limits)\b", text) \
            or re.search(r"\bwhich (ai|model)\b", text) or text in ("status", "ai status", "jarvis status"):
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
