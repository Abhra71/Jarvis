"""Accuracy + speed check for the AI brain: does it pick the right first action for typical requests?

Nothing is executed: only the AI's *choice* is checked. Uses real prompts and tools, so it costs free quota
(one request per case per setting). Requests are spaced out to stay under the per-minute limit.

    .venv\\Scripts\\python tools\\ai_eval.py                      # the configured model, as configured
    .venv\\Scripts\\python tools\\ai_eval.py --thinking minimal   # compare a thinking level
"""

import argparse
import base64
import logging
import statistics
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.disable(logging.WARNING)

import httpx  # noqa: E402

from jarvis.brain import API, Brain  # noqa: E402
from jarvis.skills import Skills, desktop  # noqa: E402

TEXT = "(reply)"  # the right answer is words, not an action
# (request, acceptable first actions, attach a screenshot?)
CASES = [
    ("open youtube in my main profile", {"open_website"}, False),
    ("search lofi music on youtube", {"web_search"}, False),
    ("what's the capital of peru", {TEXT}, False),
    ("close this tab", {"browser"}, False),
    ("volume 30", {"volume"}, False),
    ("set a timer for 10 minutes", {"timer"}, False),
    ("minimise chrome", {"window"}, False),
    ("close the chess tab", {"close_tab_named"}, False),
    ("open notepad", {"open_app"}, False),
    ("go back", {"browser"}, False),
    ("find my resume in downloads", {"find_files", "list_folder"}, False),
    ("create a folder called trips on the desktop", {"create_folder"}, False),
    ("who won the latest IPL final", {"web_search"}, False),
    ("1, 2, 4", {TEXT}, False),
    ("delete the file todo.txt on my desktop", {TEXT}, False),
    ("send hi to mom on whatsapp", {TEXT, "open_app", "window"}, False),
    ("click the start button", {"click"}, True),
    ("what's on my screen right now", {TEXT}, True),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--thinking", help="Gemini 3 thinkingLevel, e.g. minimal/low (default: as configured)")
    ap.add_argument("--gap", type=float, default=4.5, help="seconds between requests (rate limit)")
    a = ap.parse_args()

    cfg = tomllib.load(open(ROOT / "config.toml", "rb"))
    skills = Skills(cfg, print)
    brain = Brain(cfg["ai"], skills)
    model = a.model or cfg["ai"]["model"]
    thinking = a.thinking or cfg["ai"].get("thinking_level")
    shot = base64.b64encode(desktop.screenshot_jpeg()).decode()
    http = httpx.Client(timeout=30)
    print(f"model {model}, thinking {thinking or 'default'}")

    right, times = 0, []
    for text, ok, with_screen in CASES:
        parts = [{"text": text}]
        if with_screen:
            parts += [{"text": "(The current screen is attached.)"},
                      {"inlineData": {"mimeType": "image/jpeg", "data": shot}}]
        gen = {"temperature": 0.4, "maxOutputTokens": 2048}
        if thinking:
            gen["thinkingConfig"] = {"thinkingLevel": thinking}
        body = {"system_instruction": {"parts": [{"text": brain._system_prompt()}]},
                "contents": [{"role": "user", "parts": parts}],
                "tools": [{"functionDeclarations": skills.declarations()}], "generationConfig": gen}
        for attempt in range(3):
            t0 = time.monotonic()
            r = http.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": brain.key}, json=body)
            dt = time.monotonic() - t0
            if r.status_code == 200:
                break
            print(f"   (HTTP {r.status_code}, retrying)")
            time.sleep(15)
        else:
            print(f"SKIP  {text!r}: HTTP {r.status_code}")
            continue
        times.append(dt)
        out = r.json()["candidates"][0]["content"].get("parts", [])
        calls = [p["functionCall"] for p in out if "functionCall" in p]
        said = " ".join(p.get("text", "") for p in out if not p.get("thought")).strip()
        got = calls[0]["name"] if calls else TEXT
        good = got in ok
        right += good
        detail = f"{got}({calls[0].get('args', {})})" if calls else said
        print(f"{'ok  ' if good else 'MISS'}  {dt:4.1f}s  {text!r:45} -> {detail[:80]}")
        time.sleep(a.gap)

    print(f"\n{right}/{len(times)} right, median {statistics.median(times):.1f}s, "
          f"slowest {max(times):.1f}s")


if __name__ == "__main__":
    main()
