"""Reliability run: the everyday tasks, N rounds, through Jarvis exactly as if spoken (text in, no microphone).

    .venv\\Scripts\\python tools\\reliability.py 10

Each task is a pass only if Jarvis did it and could see it done (no "Not done", "I'm stuck", "couldn't
confirm"). Results: logs/reliability.jsonl (one line per try) and a summary table at the end. Settings the run
changes (brightness, night light) are put back afterwards.
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (label, what's said, how long to wait after it for the next one)
ROUND = [
    ("youtube lofi full screen", "Play lofi on YouTube and make it full screen", 4),
    ("pause/back 30/subtitles", "Pause, go back 30 seconds, and turn on subtitles", 1),
    ("exit full screen", "exit full screen", 1),
    ("close all YouTube tabs", "Close all YouTube tabs", 1),
    ("newest pdf", "Open my Downloads and find the newest PDF", 1),
    ("snap chrome/vs code", "Snap Chrome left and VS Code right", 1),
    ("night light + brightness", "Turn on night light and set brightness to 40", 1),
    ("what's on my screen", "What's on my screen?", 1),
    ("PW batch chemistry", "Open Physics Wallah, my batch, chemistry", 1),
    ("Khazana chemistry", "Open Khazana chemistry", 1),
]
FAILED = ("not done", "i'm stuck", "couldn't confirm", "i couldn't", "sorry", "didn't work", "not clicked")


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    logging.basicConfig(level=logging.WARNING)
    h = logging.FileHandler(ROOT / "logs" / "reliability.log", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s", "%H:%M:%S"))
    h.setLevel(logging.INFO)
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().handlers[0].setLevel(logging.WARNING)

    from jarvis.assistant import Assistant
    from jarvis.config import load_config
    from jarvis.skills import quick

    brightness = quick.brightness()
    a = Assistant(load_config())
    out = ROOT / "logs" / "reliability.jsonl"
    stats: dict[str, list] = {label: [] for label, _, _ in ROUND}
    try:
        for r in range(1, rounds + 1):
            print(f"\n=== round {r}/{rounds} ===", flush=True)
            for label, said, pause in ROUND:
                t0 = time.monotonic()
                try:
                    reply = a.handle_text(said)
                except Exception as e:  # a crash is a failure too
                    reply = f"Not done: crashed ({type(e).__name__}: {e})"
                if "Shall I close it, or do you want to fill it in" in reply:
                    # a site's pop-up form: answered the way the user said to (30 Sep), then the task goes on
                    print(f"       (pop-up: answering 'close it')", flush=True)
                    reply = a.handle_text("close it")
                took = time.monotonic() - t0
                last = a.brain.agent.last if a.brain.agent else None
                ok = not any(f in reply.lower() for f in FAILED)
                stats[label].append((ok, took))
                print(f"  {'PASS' if ok else 'FAIL'} {label:26} {took:5.1f}s  {reply[:110]}", flush=True)
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "round": r,
                                        "task": label, "said": said, "ok": ok, "seconds": round(took, 2),
                                        "reply": reply, "agent": last.line() if last else None}) + "\n")
                time.sleep(pause)
    finally:
        quick.set_switch("night light", False)
        if brightness is not None:
            quick.set_brightness(brightness)
    print("\n=== summary ===")
    total = sum(len(v) for v in stats.values())
    passed = sum(ok for v in stats.values() for ok, _ in v)
    for label, tries in stats.items():
        if tries:
            n_ok = sum(ok for ok, _ in tries)
            times = sorted(t for _, t in tries)
            print(f"  {label:26} {n_ok}/{len(tries)}  median {times[len(times) // 2]:.1f}s  worst {times[-1]:.1f}s")
    print(f"  ALL: {passed}/{total} ({100 * passed / max(1, total):.0f}%)")


if __name__ == "__main__":
    main()
