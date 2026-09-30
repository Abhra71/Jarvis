"""Small pop-ups (a Windows notification from the tray icon) for model switches and fallbacks.

The user's rule (30 Sep): fallbacks are shown, never spoken. "Hearing: cloud unavailable → local model",
"Gemini busy → answered by Groq"… The same message isn't repeated within a minute, so a flaky connection
doesn't flood the screen. Without a tray (tests, the text runner) pop-ups only go to the log.
"""

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

REPEAT_AFTER = 60.0  # seconds before the same pop-up may show again

_sink: Callable[[str, str], None] | None = None
_shown: dict[str, float] = {}
_down: set[str] = set()  # areas now on a backup (hearing, voice, planning, a model…)
_lock = threading.Lock()


def set_sink(fn: Callable[[str, str], None] | None):
    """fn(message, title): the tray icon's notify."""
    global _sink
    _sink = fn


def popup(text: str, key: str | None = None):
    key = key or text
    now = time.monotonic()
    with _lock:
        if now - _shown.get(key, -1e9) < REPEAT_AFTER:
            return
        _shown[key] = now
    log.info("Pop-up: %s", text)
    sink = _sink
    if sink:
        threading.Thread(target=_show, args=(sink, text), daemon=True).start()


def fell_back(area: str, text: str):
    """Something switched to its backup: pop up (the same area at most once a minute)."""
    _down.add(area)
    popup(text, f"down-{area}")


def recovered(area: str, text: str):
    """The main one works again: pop up, but only if we had told the user it fell back (1 Oct: the user
    asked for a pop-up when a model returns; before, only the AI and cloud hearing had one)."""
    if area in _down:
        _down.discard(area)
        _shown.pop(f"down-{area}", None)  # a new fall-back later shows at once
        popup(text, f"up-{area}")


def _show(sink, text: str):
    try:
        sink(text, "Jarvis")
    except Exception:
        log.debug("Couldn't show the pop-up", exc_info=True)
