"""Replay everything the user has said to Jarvis, offline, and show what Jarvis would do with it NOW.

Nothing is clicked, typed or opened: each sentence only goes through the deciding code (the stop words, the
YouTube pack's understanding, abilities, learned phrases, the offline rules, the router and the code plans).
Sentences that would reach the AI are listed with their kind; with --ai N, the first N of them are planned by
the real planner (Groq) against a plain pretend screen, and the plans are checked against the real tools
(uses a little of the free Groq allowance: about 1,300 tokens each).

    .venv\\Scripts\\python tools\\replay.py                 # routes + warnings, into logs/replay.txt
    .venv\\Scripts\\python tools\\replay.py --ai 15         # also plan 15 of the AI-bound sentences

Warnings flag decisions that were wrong in real sessions: app names that don't exist ("Open Clawed"),
noise that still gets through, commands that go to the AI although code could do them.
"""

import argparse
import time
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import logging  # noqa: E402

from jarvis import abilities, addressed, nlu, router  # noqa: E402
from jarvis.agent import plan as planmod  # noqa: E402
from jarvis.assistant import (_CODING_OFF, _CODING_ON, _DICTATE_ON, _GAMING_OFF, _GAMING_ON,  # noqa: E402
                              _NEEDS_AI, _SEARCH_CONTEXT, _STOP)
from jarvis.config import load_config  # noqa: E402
from jarvis.skills import request_parts, site_url  # noqa: E402
from jarvis.skills.apps import AppLauncher  # noqa: E402
from jarvis.skills.sites import youtube  # noqa: E402
from jarvis.stt import clean_transcript  # noqa: E402

HEARD = re.compile(r"Heard: (['\"])(.*)\1(?: \(confidence (-?[\d.]+)(, unsure)?\))?$")


def sentences() -> list[tuple[str, bool]]:
    """(what was heard, unsure) from the logs and the usage files, oldest first, each once."""
    seen, out = set(), []

    def add(text: str, unsure: bool):
        key = " ".join(text.lower().strip(" .!?,").split())
        if key and key not in seen:
            seen.add(key)
            out.append((text, unsure))

    for f in sorted((ROOT / "logs").glob("usage-*.json")):
        try:
            for t in json.loads(f.read_text(encoding="utf-8")).get("turns", []):
                if t.get("said"):
                    add(t["said"], False)
        except (OSError, ValueError):
            pass
    log = ROOT / "logs" / "jarvis.log"
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            m = HEARD.search(line)
            if m:
                add(m.group(2), bool(m.group(4)))
    return out


def route(text: str, unsure: bool, apps: AppLauncher) -> tuple[str, str]:
    """(route, detail) — what Jarvis would do first with this sentence, without doing it."""
    cleaned = clean_transcript(text)
    if not cleaned:
        return "ignored", "noise"
    why = addressed.background_reason(cleaned, -1.0 if unsure else None)  # the real confidence isn't in every log
    if why:
        return "ignored", why
    if _STOP.fullmatch(" ".join(cleaned.lower().strip(" .!?").split())):
        return "stop", ""
    if youtube.understands(cleaned, unsure):
        return "youtube pack", "(when YouTube is in front)"
    hit = abilities.match(cleaned)
    if hit:
        return "ability", f"{hit[0].name}({hit[1] or ''})"
    if not unsure:
        remembered = abilities.memory.get(cleaned)
        if remembered:
            return "learned phrase", f"{remembered[0]}({remembered[1] or ''})"
    spoken = " ".join(cleaned.lower().strip(" .!?,").split())
    for rx, mode in ((_CODING_ON, "coding on"), (_CODING_OFF, "coding off"), (_GAMING_ON, "gaming on"),
                     (_GAMING_OFF, "gaming off"), (_DICTATE_ON, "dictation on")):
        if rx.fullmatch(spoken):
            return "mode", mode
    intent = nlu.parse(cleaned)
    several = len(request_parts(cleaned)) > 1
    if intent and intent.name == "open_app" and not several:
        app = intent.slots["app"]
        if site_url(app) and not _NEEDS_AI.search(cleaned.lower()):
            return "rules", f"open website {site_url(app)}"
        if apps.find_exact(app):
            return "rules", f"open_app({app})"
        if not apps.find(app):
            meant = apps.suggest(app)
            return "AI", f"open_app({app}) -> no such app" + (f"; asks 'did you mean {meant}?'" if meant else "")
    elif intent and intent.name == "web_search" and not several and not _SEARCH_CONTEXT.search(intent.slots["query"]) \
            and len(intent.slots["query"].split()) <= 12:
        return "rules", f"{intent.name}{intent.slots}"
    elif intent and intent.name not in ("web_search",) and not several:
        return "rules", f"{intent.name}{intent.slots}"
    code = planmod.code_plan(cleaned, "", unsure)
    if code:
        return "code plan", " + ".join(s.label() for s in code.steps)
    return "AI", router.classify(cleaned)


def warnings(rows) -> list[str]:
    out = []
    for text, unsure, r, detail in rows:
        name = detail.split("(", 1)[-1].split(")", 1)[0]
        if r == "AI" and "no such app" in detail and "did you mean" not in detail and len(name.split()) <= 2:
            out.append(f"unknown app, no suggestion: {text!r} -> {detail}")
        words = re.findall(r"[a-z']+", text.lower())
        if r == "AI" and len(words) <= 3 and not unsure and detail in ("action",):
            out.append(f"short command goes to the AI: {text!r} ({detail})")
        if r != "ignored" and len(words) >= 8 and sum(len(w) <= 2 for w in words) >= 0.6 * len(words):
            out.append(f"noise gets through: {text[:60]!r}")
    return out


def plan_some(rows, n: int, skip: int = 0) -> list[str]:
    from jarvis.brain import load_api_key
    from jarvis.groq_backup import GroqBackup
    from jarvis.skills import Skills
    import httpx
    cfg = load_config()
    key = load_api_key("GROQ_API_KEY")
    if not key:
        return ["(no GROQ_API_KEY: skipped the AI plans)"]
    groq = GroqBackup(key, cfg.get("ai", {}), httpx.Client(timeout=20))
    tools = Skills(cfg, announce=lambda text: None).tools
    screen = "Front window: chrome: New Tab - Google Chrome\nOpen windows: chrome: New Tab - Google Chrome"
    out = []
    for text, unsure, r, detail in [x for x in rows if x[2] == "AI" and x[3] in ("action", "screen", "files")][skip:skip + n]:
        time.sleep(8)  # Groq's free limit: 8,000 tokens a minute per model
        system, user = planmod.planning_prompt(text, tools, screen, "", "", unsure, "chrome: New Tab - Google Chrome")
        try:
            p = planmod.parse(groq.complete(system, user), tools)
            got = " + ".join(s.label() for s in p.steps) or (f"asks: {p.ask}" if p.ask else f"says: {p.reply}")
        except planmod.NeedsEyes:
            got = "needs eyes (the seeing loop)"
        except Exception as e:  # a bad plan is a finding, not a crash
            got = f"BAD PLAN: {e}"
        out.append(f"{text!r}\n    -> {got}")
    return out


def main():
    logging.disable(logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai", type=int, default=0, help="plan this many AI-bound sentences with Groq")
    ap.add_argument("--skip", type=int, default=0, help="…after skipping this many of them")
    args = ap.parse_args()
    cfg = load_config()
    apps = AppLauncher(cfg.get("apps", {}))
    rows = [(t, u, *route(t, u, apps)) for t, u in sentences()]
    counts = Counter(r for _, _, r, _ in rows)
    lines = [f"{len(rows)} different sentences replayed", ""]
    lines += [f"{n:4}  {r}" for r, n in counts.most_common()]
    by = defaultdict(list)
    for t, u, r, d in rows:
        by[r].append(f"  {t!r}{' (unsure)' if u else ''}  ->  {d}")
    for r, _ in counts.most_common():
        lines += ["", f"== {r} =="] + by[r]
    w = warnings(rows)
    lines += ["", f"== warnings ({len(w)}) =="] + [f"  {x}" for x in w]
    if args.ai:
        lines += ["", f"== AI plans (pretend screen: a new Chrome tab) =="] + plan_some(rows, args.ai, args.skip)
    report = "\n".join(lines)
    (ROOT / "logs" / "replay.txt").write_text(report, encoding="utf-8")
    print(report[:3000])
    print(f"\n(full report: logs/replay.txt)")


if __name__ == "__main__":
    main()
