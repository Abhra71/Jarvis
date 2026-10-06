"""The AI pipeline's router: each job goes to the model proven best at it, and the load is spread BEFORE a limit
is hit, not after a failure.

- Chains: for each job ("understand", "code", ...) an ordered list of models, best first, written by
  tools/assign.py from the benchmark results (data/pipeline.json). Nothing here guesses which model is good.
- Budgets: every model's free limits (requests a minute and a day, tokens a minute and a day). Groq says what is
  left in every answer; for the others Jarvis counts what it used. A model whose budget can't take the next call
  is skipped for now.
- Health: a model that just failed (outage, timeout, rate limit) is rested for a while (30 s, then 2 min, then
  10 min), so one bad model never slows every request.
- Usage is saved (data/pipeline_state.json) so a restart doesn't forget today's counts.
"""

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from ..config import ROOT
from .providers import Reply, split

PIPELINE = ROOT / "data" / "pipeline.json"
STATE = ROOT / "data" / "pipeline_state.json"

# Free-tier limits (checked 5 Oct 2026). None = not published; the model is then limited only by its own errors.
LIMITS = {
    "groq": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200_000},
    "gemini": {"rpm": 15, "rpd": 1000, "tpm": 250_000, "tpd": None},
    "nvidia": {"rpm": 40, "rpd": None, "tpm": None, "tpd": None},
    "cloudflare": {"rpm": 300, "rpd": 400, "tpm": None, "tpd": None},  # 10,000 neurons a day, ~400 short calls
}
REST = (30, 120, 600)  # seconds a failing model is rested: first, second, third+ failure in a row


@dataclass
class _Use:
    minute: deque = field(default_factory=deque)       # (time, tokens) of calls in the last 60 s
    day: str = ""
    day_requests: int = 0
    day_tokens: int = 0
    failures: int = 0
    rest_until: float = 0.0
    told_left: dict = field(default_factory=dict)       # what the provider last said was left


class Router:
    def __init__(self, chains: dict[str, list[str]] | None = None, clock=time.time):
        self.chains = chains if chains is not None else _load_chains()
        self.clock = clock
        self.use: dict[str, _Use] = {}
        self.lock = threading.Lock()
        self._load_state()

    # ---- choosing --------------------------------------------------------------------------------------
    def candidates(self, job: str, tokens: int = 1500) -> list[str]:
        """The job's chain, in order, without the models that are resting or out of budget right now."""
        with self.lock:
            return [m for m in self.chains.get(job, []) if self._can(m, tokens)]

    def _can(self, model: str, tokens: int) -> bool:
        u = self._u(model)
        now = self.clock()
        if now < u.rest_until:
            return False
        lim = LIMITS[split(model)[0]]
        while u.minute and now - u.minute[0][0] > 60:
            u.minute.popleft()
        if lim["rpm"] and len(u.minute) >= lim["rpm"]:
            return False
        if lim["tpm"] and sum(t for _, t in u.minute) + tokens > lim["tpm"]:
            return False
        if "tokens_left" in u.told_left and u.told_left["tokens_left"] < tokens and now - u.told_left["at"] < 60:
            return False
        if lim["rpd"] and u.day_requests >= lim["rpd"]:
            return False
        if "requests_left" in u.told_left and u.told_left["requests_left"] <= 0:
            return False
        if lim["tpd"] and u.day_tokens + tokens > lim["tpd"]:
            return False
        return True

    # ---- recording ---------------------------------------------------------------------------------------
    def record(self, reply: Reply):
        with self.lock:
            u = self._u(reply.model)
            now = self.clock()
            tokens = max(0, reply.tokens_in - reply.cached) + reply.tokens_out  # cached tokens don't count (Groq)
            u.minute.append((now, tokens))
            u.day_requests += 1
            u.day_tokens += tokens
            left = (reply.extra or {}).get("limits") or {}
            if left:
                u.told_left = dict(left, at=now)
            if reply.ok:
                u.failures = 0
            elif reply.error in ("rate_limit", "server", "timeout", "network", "empty"):
                u.failures += 1
                rest = REST[min(u.failures, len(REST)) - 1]
                if reply.error == "rate_limit" and reply.retry_after:
                    rest = max(rest, reply.retry_after)
                u.rest_until = now + rest
            self._save_state()

    def run(self, job: str, attempt, tokens: int = 1500, max_models: int = 3, hedge_after: float | None = 2.5):
        """attempt(model) -> (result, Reply). Returns (result, replies).

        Hedged (6 Oct, live: one flaky Gemini call plus a slow fallback made a coding answer take 33 s): the first
        model starts; if it hasn't answered after `hedge_after` seconds (or fails), the next one starts too, and the
        first good answer wins. A slow or failing provider can't make the user wait. hedge_after=None: one at a time."""
        import concurrent.futures as cf
        models = self.candidates(job, tokens)[:max_models]
        replies: list[Reply] = []
        if not models:
            return None, replies
        pool = cf.ThreadPoolExecutor(max_workers=len(models))
        running: dict = {}
        try:
            nxt = 0
            running[pool.submit(attempt, models[0])] = models[0]
            nxt = 1
            while running:
                wait = hedge_after if (hedge_after is not None and nxt < len(models)) else None
                done, _ = cf.wait(running, timeout=wait, return_when=cf.FIRST_COMPLETED)
                for fut in done:
                    running.pop(fut)
                    try:
                        result, reply = fut.result()
                    except Exception as e:  # an attempt that crashed is a failure like any other
                        result, reply = None, Reply("?", error="network", detail=str(e)[:100])
                    self.record(reply)
                    replies.append(reply)
                    if result is not None:
                        return result, replies
                if nxt < len(models) and (not done or not running):
                    # no answer yet in time (hedge), or everything running so far failed: start the next model
                    running[pool.submit(attempt, models[nxt])] = models[nxt]
                    nxt += 1
            return None, replies
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    # ---- state -------------------------------------------------------------------------------------------
    def _u(self, model: str) -> _Use:
        u = self.use.setdefault(model, _Use())
        today = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))  # the free limits reset at midnight UTC
        if u.day != today:
            u.day, u.day_requests, u.day_tokens = today, 0, 0
            u.told_left = {}
        return u

    def status(self) -> list[dict]:
        """For the status page: each model's use today and whether it's resting."""
        now = self.clock()
        with self.lock:
            return [{"model": m, "requests_today": u.day_requests, "tokens_today": u.day_tokens,
                     "resting_s": max(0, round(u.rest_until - now)), "provider_says_left": u.told_left}
                    for m, u in sorted(self.use.items())]

    def _load_state(self):
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for m, d in data.items():
            self.use[m] = _Use(day=d.get("day", ""), day_requests=d.get("requests", 0), day_tokens=d.get("tokens", 0))

    def _save_state(self):
        try:
            STATE.write_text(json.dumps({m: {"day": u.day, "requests": u.day_requests, "tokens": u.day_tokens}
                                         for m, u in self.use.items()}), encoding="utf-8")
        except OSError:
            pass


def _load_chains() -> dict[str, list[str]]:
    try:
        return json.loads(PIPELINE.read_text(encoding="utf-8"))["chains"]
    except (OSError, ValueError, KeyError):
        return {}
