"""The agent task suite (docs/agent-core.md): 12 real tasks, scored done / time / AI calls.

    .venv\\Scripts\\python tools\\agent_suite.py            plan only: the real AI plans each task from the real
                                                          screen (as text), NOTHING is executed. Safe any time.
    .venv\\Scripts\\python tools\\agent_suite.py --live 7   really do task 7 on this PC (the same path as a voice
                                                          command). Only while nobody is using the PC.

Results are appended as JSON lines to logs/agent_suite.jsonl.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from jarvis.config import load_config  # noqa: E402

TASKS = [
    "Play lofi on YouTube and make it full screen",
    "Email abhrachakraborty21 at gmail dot com saying Jarvis email test",  # WhatsApp dropped by the user (30 Sep)
    "Connect my Rockerz headphones",
    "Open my Downloads and find the newest PDF",
    "Upload my newest pdf here",  # no resume file on this PC (30 Sep)
    "Open VS Code, go to line 40 and comment it",
    "Snap Chrome left and VS Code right",
    "Close all YouTube tabs",
    "Turn on night light and set brightness to 40",
    "What's on my screen?",
    "Open Physics Wallah, my batch, chemistry",
    "Pause, go back 30 seconds, and turn on subtitles",
    "Open Khazana chemistry",
]


def _log(row: dict):
    out = ROOT / "logs" / "agent_suite.jsonl"
    out.parent.mkdir(exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), **row}) + "\n")


def plan_only(numbers: list[int]):
    from unittest import mock

    from jarvis import router
    from jarvis.agent import context, plan as planmod
    from jarvis.brain import Brain
    from jarvis.skills import Skills, shortcuts

    config = load_config()
    skills = Skills(config, announce=print)
    brain = Brain({**config.get("ai", {}), "agent_mode": True}, skills)
    if not brain.available:
        sys.exit("No AI keys in .env")
    snap = context.take()
    screen = snap.text()
    print(f"Screen as text ({len(screen)} chars):\n{screen[:600]}\n")
    for n in numbers:
        task = TASKS[n - 1]
        kind = router.classify(task)
        system, user = planmod.planning_prompt(task, skills.tools, screen, "",
                                               shortcuts.for_window(snap.front, task), False)
        t0 = time.monotonic()
        try:
            raw = brain._think(system, user)
            took = time.monotonic() - t0
            try:
                p = planmod.parse(raw, skills.tools)
                steps = [f"{s.label()}" + (f"  ⟶ {s.check}" if s.check else "") for s in p.steps]
                verdict = "plan" if p.steps else ("ask" if p.ask else "reply")
                said = p.ask or p.reply
            except planmod.NeedsEyes:
                verdict, steps, said = "needs_eyes", [], ""
            except planmod.PlanError as e:
                verdict, steps, said = "bad_plan", [], str(e)
        except Exception as e:
            took, verdict, steps, said, raw = time.monotonic() - t0, "error", [], str(e), ""
        print(f"[{n}] {task}  ({kind}, {took:.1f}s, {verdict})")
        for s in steps:
            print(f"     - {s}")
        if said:
            print(f"     says: {said}")
        _log({"mode": "plan", "task": n, "said": task, "kind": kind, "seconds": round(took, 2),
              "verdict": verdict, "steps": steps, "reply": said, "prompt_chars": len(system) + len(user)})


def live(numbers: list[int], then: list[str] = ()):
    from jarvis.assistant import Assistant

    config = load_config()
    a = Assistant(config)
    for n in numbers:
        task = TASKS[n - 1]
        t0 = time.monotonic()
        reply = a.handle_text(task)
        took = time.monotonic() - t0
        last = a.brain.agent.last if a.brain.agent else None
        print(f"[{n}] {task}\n     -> {reply}  ({took:.1f}s; {last.line() if last else 'old loop'})")
        _log({"mode": "live", "task": n, "said": task, "seconds": round(took, 2), "reply": reply,
              "agent": last.__dict__ if last else None})
        for said in then:  # the user's answers to Jarvis's questions ("close it")
            t0 = time.monotonic()
            reply = a.handle_text(said)
            print(f"     user: {said}\n     -> {reply}  ({time.monotonic() - t0:.1f}s)")
            _log({"mode": "live", "task": n, "said": said, "seconds": round(time.monotonic() - t0, 2), "reply": reply})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tasks", nargs="*", type=int, help="task numbers (default: all)")
    p.add_argument("--live", action="store_true", help="really do the tasks on this PC")
    p.add_argument("--then", action="append", default=[], help="what the user says next (answers), in order")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.live:  # every step, check and timing, for the review (logs/agent_suite.log)
        h = logging.FileHandler(ROOT / "logs" / "agent_suite.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(name)s: %(message)s", "%H:%M:%S"))
        h.setLevel(logging.INFO)
        logging.getLogger().addHandler(h)
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().handlers[0].setLevel(logging.WARNING)
    numbers = args.tasks or list(range(1, len(TASKS) + 1))
    live(numbers, args.then) if args.live else plan_only(numbers)


if __name__ == "__main__":
    main()
