"""Keeps track of which AI model handled what, screenshots, failures and limits, for today.

Everything is saved to logs/usage-YYYY-MM-DD.json so the numbers survive a restart,
and the status page (dashboard.py) and the "AI status" voice command read from here.
"""

import json
import threading
import time
from collections import deque
from datetime import date, datetime

from .config import LOG_DIR

COOLDOWN_SECONDS = 60  # after a "limit reached", treat that model as limited for about this long


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


class Usage:
    def __init__(self, persist: bool = True):
        self.persist = persist  # tests turn this off so they don't touch your real stats
        self._lock = threading.Lock()
        self._listeners = []
        self._load(date.today())

    # ---- storage ------------------------------------------------------------------

    def _path(self, day: date):
        return LOG_DIR / f"usage-{day.isoformat()}.json"

    def _load(self, day: date):
        self.day = day
        self.models: dict[str, dict] = {}
        self.turns: deque = deque(maxlen=60)
        self.screenshots = {"count": 0, "last": None}
        self.routes = {"offline rules": 0, "gemini": 0, "groq": 0, "failed": 0}
        self.current_turn = None
        self.activity = "idle"
        self.last_answered_by = None
        if not self.persist:
            return
        try:
            data = json.loads(self._path(day).read_text(encoding="utf-8"))
            self.models = data.get("models", {})
            self.turns.extend(data.get("turns", []))
            self.screenshots = data.get("screenshots", self.screenshots)
            self.routes.update(data.get("routes", {}))
        except (OSError, ValueError):
            pass

    def _save(self):
        if not self.persist:
            return
        LOG_DIR.mkdir(exist_ok=True)
        data = {"models": self.models, "turns": list(self.turns), "screenshots": self.screenshots, "routes": self.routes}
        self._path(self.day).write_text(json.dumps(data, indent=1), encoding="utf-8")

    def _rollover(self):
        if date.today() != self.day:
            self._load(date.today())

    def on_change(self, fn):
        self._listeners.append(fn)

    def _changed(self, event: str):
        for fn in self._listeners:
            try:
                fn(event)
            except Exception:
                pass

    # ---- recording ------------------------------------------------------------------

    def begin_turn(self, text: str):
        with self._lock:
            self._rollover()
            self.current_turn = {"time": _now(), "said": text, "route": None, "models": [], "screenshots": 0,
                                 "actions": [], "seconds": None, "reply": None, "_t0": time.monotonic()}

    def end_turn(self, route: str, reply: str):
        with self._lock:
            t = self.current_turn
            if not t:
                return
            t["route"] = route
            t["reply"] = reply
            t["seconds"] = round(time.monotonic() - t.pop("_t0"), 1)
            self.routes[route] = self.routes.get(route, 0) + 1
            self.turns.append(t)
            self.current_turn = None
            self.activity = "idle"
            self._save()
        self._changed("turn")

    def api_call(self, provider: str, model: str, status: int | str, seconds: float,
                 tokens_in: int = 0, tokens_out: int = 0, limits: dict | None = None,
                 limited_for: int | None = None):
        """One request to an AI model. status: HTTP code, or 'timeout' / 'error'.
        limited_for: after a 429, how many seconds to leave this model alone (default COOLDOWN_SECONDS)."""
        with self._lock:
            self._rollover()
            key = f"{provider}:{model}"
            m = self.models.setdefault(key, {
                "provider": provider, "model": model, "requests": 0, "ok": 0, "limited": 0, "busy": 0,
                "timeouts": 0, "other_errors": 0, "seconds_total": 0.0, "tokens_in": 0, "tokens_out": 0,
                "last_used": None, "last_status": None, "limited_until": 0, "limits": {}})
            m["requests"] += 1
            m["last_used"] = _now()
            m["last_status"] = status
            if status == 200:
                m["ok"] += 1
                m["seconds_total"] += seconds
                m["tokens_in"] += tokens_in or 0
                m["tokens_out"] += tokens_out or 0
                self.last_answered_by = key
            elif status == 429:
                m["limited"] += 1
                m["limited_until"] = time.time() + (limited_for or COOLDOWN_SECONDS)
            elif status in (500, 502, 503, 504):
                m["busy"] += 1
            elif status == "timeout":
                m["timeouts"] += 1
            else:
                m["other_errors"] += 1
            if limits:
                m["limits"] = limits
                m["limits_at"] = time.time()
            if self.current_turn is not None:
                self.current_turn["models"].append(f"{model} → {status}")
            self._save()
        self._changed("api")

    def action(self, tool: str):
        with self._lock:
            if tool == "look_at_screen":
                self.screenshots["count"] += 1
                self.screenshots["last"] = _now()
                if self.current_turn is not None:
                    self.current_turn["screenshots"] += 1
            if self.current_turn is not None:
                self.current_turn["actions"].append(tool)
            self.activity = {"look_at_screen": "looking at your screen", "click": "using the mouse",
                             "scroll": "using the mouse", "hover": "using the mouse"}.get(tool, f"doing: {tool}")
        self._changed("action")

    def set_activity(self, text: str):
        self.activity = text
        self._changed("activity")

    # ---- reading ------------------------------------------------------------------

    def is_limited(self, key: str) -> bool:
        return self.models.get(key, {}).get("limited_until", 0) > time.time()

    def tokens_left(self, key: str) -> float | None:
        """Estimated tokens this model can take right now under its per-minute limit, from the last
        rate-limit headers plus what has refilled since (the allowance refills evenly over a minute).
        None if the provider hasn't told us its limits yet."""
        m = self.models.get(key, {})
        limits, at = m.get("limits") or {}, m.get("limits_at")
        try:
            remaining, limit = float(limits["remaining-tokens"]), float(limits["limit-tokens"])
        except (KeyError, TypeError, ValueError):
            return None
        refilled = (time.time() - at) * limit / 60 if at else limit
        return min(limit, remaining + refilled)

    def model_state(self, m: dict) -> str:
        left = m.get("limited_until", 0) - time.time()
        if left > 0:
            wait = f"{int(left)}s" if left < 120 else f"{int(left // 60)} min"
            return f"limit reached (skipped for ~{wait})"
        return {200: "working", 429: "limit reached", "timeout": "slow / timed out"}.get(
            m.get("last_status"), "busy" if m.get("last_status") in (500, 502, 503, 504) else
            ("not used yet" if m.get("last_status") is None else f"error {m.get('last_status')}"))

    def snapshot(self) -> dict:
        with self._lock:
            self._rollover()
            models = []
            for key, m in self.models.items():
                models.append({**m, "key": key, "state": self.model_state(m),
                               "avg_seconds": round(m["seconds_total"] / m["ok"], 1) if m["ok"] else None})
            return {
                "now": _now(), "day": self.day.isoformat(), "activity": self.activity,
                "last_answered_by": self.last_answered_by, "models": models, "routes": dict(self.routes),
                "screenshots": dict(self.screenshots), "turns": list(self.turns)[::-1],
                "ai_requests": sum(m["requests"] for m in self.models.values()),
            }

    def spoken_summary(self, order: list[str]) -> str:
        """Short sentence for the 'AI status' voice command. `order` = model keys in the order Jarvis tries them."""
        s = self.snapshot()
        by_key = {m["key"]: m for m in s["models"]}
        now_using = next((k for k in order if not by_key.get(k, {}).get("state", "").startswith("limit")), None)
        parts = []
        if now_using:
            parts.append(f"Right now I'd use {now_using.split(':', 1)[1].replace('-', ' ')}.")
        limited = [k.split(":", 1)[1].replace("-", " ") for k in order if by_key.get(k, {}).get("state", "").startswith("limit")]
        if limited:
            parts.append(f"{' and '.join(limited)} {'is' if len(limited) == 1 else 'are'} at the limit for now.")
        r = s["routes"]
        parts.append(f"Today: {s['ai_requests']} AI requests, {r.get('offline rules', 0)} offline commands, "
                     f"{s['screenshots']['count']} screenshots, and the backup was used {r.get('groq', 0)} times.")
        return " ".join(parts)


usage = Usage()
