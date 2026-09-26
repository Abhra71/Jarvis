import logging
import threading
import winsound
from typing import Callable

log = logging.getLogger(__name__)


def describe(seconds: int) -> str:
    parts = []
    for unit, size in (("hour", 3600), ("minute", 60), ("second", 1)):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {unit}{'s' if n > 1 else ''}")
    return " and ".join(parts) if parts else "0 seconds"


class Timers:
    def __init__(self, announce: Callable[[str], None]):
        self.announce = announce
        self._timers: list[threading.Timer] = []

    def start(self, seconds: int | None) -> str:
        if not seconds:
            return "How long? Say something like, set a timer for 5 minutes."
        label = describe(seconds)
        t = threading.Timer(seconds, self._ring, args=(label,))
        t.daemon = True
        self._timers.append(t)
        t.start()
        log.info("Timer set: %s", label)
        return f"Timer set for {label}."

    def _ring(self, label: str):
        self._timers = [t for t in self._timers if t.is_alive() and t is not threading.current_thread()]
        for _ in range(3):
            winsound.Beep(880, 250)
            winsound.Beep(660, 250)
        self.announce(f"Your {label} timer is done.")

    def cancel_all(self) -> str:
        active = [t for t in self._timers if t.is_alive()]
        for t in active:
            t.cancel()
        self._timers.clear()
        return f"Cancelled {len(active)} timer{'s' if len(active) != 1 else ''}." if active else "No timers running."
