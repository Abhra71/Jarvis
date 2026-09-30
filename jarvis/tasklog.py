"""One line per request, for the trial and its review (Phase 4).

Each request the user makes is written to logs/tasks-YYYY-MM-DD.jsonl, and one readable line goes to jarvis.log:

    Task: stuck | agent | 'Open Clawed.' | 8.1s | 2 AI calls | hearing cloud -0.80 unsure | Clawed didn't come up.

`result` is the one word the review needs:
    done         did it, and saw it work (or it needs no checking: an answer, a volume change)
    unconfirmed  did it, but couldn't see it work
    asked        asked the user a question instead (unclear request, "did you mean", "shall I send it?")
    stuck        tried and couldn't finish
    failed       an error, or nothing could handle it
    stopped      the user stopped it (moved the mouse, said stop)
    ignored      nothing to do (noise)
"""

import json
import logging
import re
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from .config import ROOT

log = logging.getLogger(__name__)

LOG_DIR = ROOT / "logs"
_lock = threading.Lock()
FORCE: bool | None = None  # tests set True (with LOG_DIR in a temp folder); None = on, except under unittest


def _enabled() -> bool:
    return FORCE if FORCE is not None else "unittest" not in sys.modules

_FAILED = re.compile(r"^(sorry|not done|not clicked|not allowed|error|i couldn't|i can't|i lost|that didn't|"
                     r"it didn't|unknown)\b", re.I)
_UNCONFIRMED = re.compile(r"can't tell if it worked|couldn't confirm", re.I)
_STUCK = re.compile(r"what should i do\?$", re.I)


def classify(route: str, reply: str) -> str:
    """The result word for a request that didn't go through the agent (which reports its own)."""
    r = (reply or "").strip()
    if route == "stopped":
        return "stopped"
    if route == "failed":
        return "failed"
    if _STUCK.search(r):
        return "stuck"
    if _UNCONFIRMED.search(r):
        return "unconfirmed"
    if _FAILED.match(r):
        return "failed"
    if r.endswith("?"):
        return "asked"
    return "done"


def path_for(day: date | None = None) -> Path:
    return LOG_DIR / f"tasks-{(day or date.today()).isoformat()}.jsonl"


def write(entry: dict):
    """Append one request's line (file) and its readable line (jarvis.log)."""
    entry = {"time": datetime.now().strftime("%H:%M:%S"), **entry}
    bits = [entry.get("result", "?"), entry.get("route", "?"), repr(entry.get("said", "")),
            f"{entry.get('seconds', 0):.1f}s"]
    if entry.get("ai_calls"):
        bits.append(f"{entry['ai_calls']} AI calls")
    if entry.get("hearing"):
        h = entry["hearing"]
        bits.append(f"hearing {h.get('source', '?')} {h.get('confidence', 0):.2f}{' unsure' if h.get('unsure') else ''}")
    if entry.get("why"):
        bits.append(str(entry["why"])[:160])
    log.info("Task: %s", " | ".join(bits))
    if not _enabled():
        return  # the test suite's pretend requests don't belong in the user's review
    try:
        with _lock:
            LOG_DIR.mkdir(exist_ok=True)
            with path_for().open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("Couldn't write the task log", exc_info=True)


def read(day: date | None = None) -> list[dict]:
    try:
        lines = path_for(day).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def summary(entries: list[dict]) -> dict:
    """Today's review: counts by result, the median time, and what went wrong (newest first)."""
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.get("result", "?")] = counts.get(e.get("result", "?"), 0) + 1
    secs = sorted(e.get("seconds", 0) for e in entries if e.get("result") != "ignored")
    wrong = [e for e in entries if e.get("result") in ("stuck", "failed", "unconfirmed")]
    real = [e for e in entries if e.get("result") != "ignored"]
    return {"total": len(real), "counts": counts,
            "median_seconds": secs[len(secs) // 2] if secs else None,
            "slow": sum(1 for s in secs if s >= 6),
            "worked_percent": round(100 * counts.get("done", 0) / len(real)) if real else None,
            "wrong": wrong[::-1][:40]}


class Turn:
    """Times one request and collects what's known about it, then writes it."""

    def __init__(self, said: str, hearing: dict | None = None):
        self.said, self.hearing, self.t0 = said, hearing, time.monotonic()

    def finish(self, route: str, reply: str, agent_outcome=None):
        entry = {"said": self.said, "route": route, "reply": (reply or "")[:300],
                 "seconds": round(time.monotonic() - self.t0, 2)}
        if self.hearing:
            entry["hearing"] = self.hearing
        o = agent_outcome
        if route == "agent" and o is not None:
            entry.update(result=o.result if o.result != "needs_yes" else "asked", plan=o.source, steps=o.steps,
                         ai_calls=o.ai_calls, why=o.detail)
            if o.result == "fallback":
                entry["result"] = classify(route, reply)
        else:
            entry["result"] = classify(route, reply)
            if entry["result"] != "done":
                entry["why"] = (reply or "")[:200]
        write(entry)
        return entry
