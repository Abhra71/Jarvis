"""What's on screen right now, as text: the agent's eyes (no AI, ~0.1 s).

A Snapshot reads lazily: the front window is always cheap; the window list, the on-screen items, the
address bar, the focused control and the OCR text are read only when a plan or a check needs them, and
each at most once per snapshot. Every reader can be swapped out (tests use fake ones).

How Jarvis sees, cheapest first: the accessibility tree as text (named buttons, links, fields) → the
window list and address → Windows' own offline OCR (apps that don't name their buttons) → a screenshot
for Gemini, only when nothing else works (the old loop does that).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from ..skills import desktop, elements, files

log = logging.getLogger(__name__)


def _windows() -> list[str]:
    return [f"{proc.removesuffix('.exe')}: {title}" for _, proc, title in desktop._app_windows()]


def _url() -> str | None:
    return desktop.current_url() if elements.front_is_browser() else None


def _ocr() -> list[str]:
    from . import ocr
    return ocr.read_front()


@dataclass
class Readers:
    front: Callable[[], str] = desktop.front_window          # "chrome: YouTube - Google Chrome"
    windows: Callable[[], list[str]] = _windows              # every open window, front-most first
    items: Callable[[], list] = elements.read_front          # named buttons/links/fields (elements.Element)
    url: Callable[[], str | None] = _url                     # the front browser tab's address
    focus: Callable[[], str] = elements.focused_kind          # "field", "document", "button"…
    ocr: Callable[[], list[str]] = _ocr                       # text lines read off the front window's pixels


_EMPTY = {"front": "", "windows": [], "items": [], "url": None, "focus": "none", "ocr": []}
_PRIVATE = ("items", "focus", "ocr")  # never read inside a secrets file's window


@dataclass
class Snapshot:
    readers: Readers = field(default_factory=Readers)
    _cache: dict = field(default_factory=dict)

    def _get(self, key: str):
        if key not in self._cache:
            if key in _PRIVATE and files.is_secret(self.front):
                self._cache[key] = _EMPTY[key]
                return self._cache[key]
            t0 = time.monotonic()
            try:
                self._cache[key] = getattr(self.readers, key)()
            except Exception:
                log.debug("Snapshot couldn't read %s", key, exc_info=True)
                self._cache[key] = _EMPTY[key]
            log.debug("Snapshot %s in %.2fs", key, time.monotonic() - t0)
        return self._cache[key]

    @property
    def front(self) -> str:
        return self._get("front") or ""

    @property
    def windows(self) -> list[str]:
        return self._get("windows") or []

    @property
    def items(self) -> list:
        return self._get("items") or []

    @property
    def url(self) -> str | None:
        return self._get("url")

    @property
    def focus(self) -> str:
        return self._get("focus") or "none"

    @property
    def ocr(self) -> list[str]:
        return self._get("ocr") or []

    def text(self, max_items: int = 40, max_windows: int = 8) -> str:
        """For the AI planner: short, and only facts."""
        lines = [f"Front window: {self.front or 'none'}"]
        others = [w for w in self.windows if w != self.front][:max_windows]
        if others:
            lines.append("Other windows: " + " | ".join(others))
        if self.url:
            lines.append(f"Address: {self.url}")
        items = self.items
        if items:
            shown = "; ".join(el.label() for el in items[:max_items])
            more = f" (+{len(items) - max_items} more)" if len(items) > max_items else ""
            lines.append(f"On screen: {shown}{more}")
        elif self.ocr:
            lines.append("Text on screen (read from pixels, not clickable by name): "
                         + " | ".join(self.ocr[:max_items]))
        return "\n".join(lines)


def take(readers: Readers | None = None) -> Snapshot:
    return Snapshot(readers or Readers())


@dataclass
class Turn:
    said: str
    reply: str
    when: float = field(default_factory=time.monotonic)


class Memory:
    """The last few requests and what came of them, and what "it"/"that" means right now."""

    def __init__(self, keep: int = 3, minutes: float = 5):
        self.turns: list[Turn] = []
        self.keep, self.minutes = keep, minutes
        self.it = ""  # the last thing acted on: "WhatsApp", "Downloads/cv.pdf", "lofi"

    def add(self, said: str, reply: str):
        self.turns = [*self.recent(), Turn(said, reply)][-self.keep:]

    def recent(self) -> list[Turn]:
        cutoff = time.monotonic() - self.minutes * 60
        return [t for t in self.turns if t.when >= cutoff]

    def text(self) -> str:
        lines = [f'- "{t.said}" -> {t.reply}' for t in self.recent()]
        if self.it:
            lines.append(f'"it"/"that" = {self.it}')
        return "\n".join(lines)
