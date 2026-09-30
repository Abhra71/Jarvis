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


def _show(sink, text: str):
    try:
        sink(text, "Jarvis")
    except Exception:
        log.debug("Couldn't show the pop-up", exc_info=True)
