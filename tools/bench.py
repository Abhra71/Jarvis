"""Benchmark AI models on the user's REAL sentences, so each job goes to the model that is proven best at it.

    .venv\\Scripts\\python tools\\bench.py understand --models groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite
    .venv\\Scripts\\python tools\\bench.py understand --all          # every candidate model
    .venv\\Scripts\\python tools\\bench.py report                    # the table, from the saved results

Gold set: data/gold/understand.jsonl (every sentence the user ever said, labelled by hand with what should happen
on the screen it was said on). A fixed, stratified sample (data/gold/bench_ids.json) is used so every model sees
the same sentences. Results are saved per model in data/bench/ and the run resumes where it stopped, so a rate
limit only pauses it. Each model runs in its own thread, paced to its provider's free limits.

Grading (per sentence):
- pass:          the right kind (or an acceptable one), the right actions, and the key details (names, numbers).
- wrong_action:  it ACTED but did the wrong thing, or acted where it should have asked, ignored, refused or chatted.
                 This is the worst outcome: a confident wrong action on the user's PC.
- wrong_kind:    it asked/chatted/ignored where it should have acted (annoying, not harmful).
- missing:       the right action but a key detail is missing or wrong.
- error:         no usable answer (timeout, bad JSON, rate limit after retries).
"""

import argparse
import json
import random
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jarvis.llm import understand as U  # noqa: E402

GOLD = ROOT / "data" / "gold" / "understand.jsonl"
IDS = ROOT / "data" / "gold" / "bench_ids.json"
OUT = ROOT / "data" / "bench" / ("understand-" + __import__("hashlib").sha1(U.SYSTEM.encode()).hexdigest()[:8])

PROFILE = ("Chrome profiles: main = ABHRA, AI = Abhra (second), backup = Abhra Chakraborty, Large Language, "
           "Miscellaneous, Work. Browsers: Chrome, Brave. Studies on PW (Physics Wallah, pw.live; batch VICTORY 2027; "
           "Khazana = recorded classes). Plays chess on chess.com. Headphones: Rockerz 480. Java in BlueJ, "
           "C++ in VS Code. Apps include Claude, WhatsApp, eFootball, Notepad.")

CANDIDATES = [
    "groq:openai/gpt-oss-20b", "groq:openai/gpt-oss-120b", "groq:qwen/qwen3.8-27b",
    "gemini:gemini-3.5-flash-lite", "gemini:gemini-3.1-flash-lite", "gemini:gemini-3.5-flash", "gemini:gemini-3.8-flash",
    "gemini:gemma-4-31b-it",
    "nvidia:nvidia/nemotron-3-super-120b-a12b", "nvidia:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "cloudflare:@cf/openai/gpt-oss-120b", "cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "cloudflare:@cf/qwen/qwen3-30b-a3b-fp8",
]
GAP = {"groq": 2.2, "gemini": 4.5, "nvidia": 1.6, "cloudflare": 0.5}  # seconds between calls, per model

# The same thing said different ways.
SYNONYMS = {
    "back": ("back", "alt+left", "browser_back"), "f5": ("f5", "refresh", "reload"), "enter": ("enter", "return"),
    "delete": ("delete", "del", "backspace", "remove"), "ctrl+a": ("ctrl+a", "select all", "select_all"),
    "minimize": ("minimize", "minimise"), "code": ("code", "visual studio"), "120": ("120", "2 min"),
    "exit": ("exit", "leave"), "fullscreen": ("fullscreen", "full screen", "full_screen"), "skip": ("skip",),
    "close": ("close",), "new_class": ("new_class", "new class", "create"), "open": ("open",),
    "chess": ("chess",), "youtube": ("youtube",), "main": ("main", "abhra"), "ai": ("ai", "abhra (second)", "second"),
    "all": ("all",), "monitor": ("monitor", "screen", "display"), "other": ("other", "close_others"),
    "rockerz": ("rockerz", "rockers"), "480": ("480",), "night": ("night",), "down": ("down",),
    "double": ("double",), "trust folder": ("trust folder", "trust"), "lastindexof": ("lastindexof", "last index"),
    "remove": ("remove", "delete", "clear"), "string": ("string",), "aeiou": ("aeiou",),
    "screenshot": ("screenshot",), "pdf": ("pdf",), "first": ("first", "1"), "second": ("second", "2"),
    "third": ("third", "3"), "chemistry": ("chemistry",), "khazana": ("khazana",), "notification": ("notification",),
    "lecture 3": ("lecture 3", "lecture three", "lecture_3"), "done": ("done", "complete", "mark"),
}


_RETRY = ("rate_limit", "server", "timeout", "empty", "network")


def gold() -> dict[int, dict]:
    return {g["id"]: g for g in (json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines())}


def sample_ids(golds: dict[int, dict], seed: int = 7) -> list[int]:
    """Every rare kind, and a fair share of the common ones (fixed, so all models see the same sentences)."""
    if IDS.exists():
        return json.loads(IDS.read_text())
    by = defaultdict(list)
    for g in golds.values():
        by[g["kind"]].append(g["id"])
    want = {"act": 80, "ignore": 22, "chat": 12, "code": 28, "ask": 14, "refuse": 5, "control": 6}
    rnd = random.Random(seed)
    ids = []
    for kind, n in want.items():
        pool = sorted(by[kind])
        ids += pool if len(pool) <= n else sorted(rnd.sample(pool, n))
    IDS.write_text(json.dumps(sorted(ids)))
    return sorted(ids)


def _has(text: str, word: str) -> bool:
    return any(w in text for w in SYNONYMS.get(word, (word,)))


def grade(g: dict, m: dict | None) -> str:
    if m is None:
        return "error"
    kind, ok = m.get("kind"), set(g["ok"])
    kinds_ok = {g["kind"]} | (ok & set(U.KINDS))
    dos = [s.get("do", "") for s in m.get("steps", [])]
    text = U.as_text(m)
    if kind == "control":
        if g["kind"] == "control":
            return "pass" if (not g["intent"] or m.get("control") == g["intent"]) else "wrong_kind"
        return "pass" if "control" in ok else ("wrong_action" if m.get("control") in ("stop", "yes", "undo") else "wrong_kind")
    if kind not in kinds_ok:
        if kind == "act" and any(d in ok for d in dos) and g["kind"] in ("act", "code", "ask", "chat"):
            pass  # an acceptable alternative action (e.g. keys ctrl+a for "select all and delete" in coding)
        elif kind == "act":
            return "wrong_action"
        else:
            return "wrong_kind"
    if kind == "act" and g["kind"] == "act":
        need = [i for i in g["intent"].split("+") if i]
        if not (all(i in dos for i in need) or any(d in ok for d in dos)):
            return "wrong_action"
    if kind in ("act", "code") and not all(_has(text, w) for w in g["must"]):
        return "missing"
    return "pass"


def run_model(model: str, ids: list[int], golds: dict, lock: threading.Lock, timeout: float = 20.0):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("understand__" + model.replace(":", "__").replace("/", "_").replace("@", "") + ".jsonl")
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("error") not in _RETRY:  # outages are tried again on the next run (and counted as availability)
                done.add(r["id"])
    gap = GAP[model.split(":")[0]]
    timeouts = 0
    for n, i in enumerate(i for i in ids if i not in done):
        g = golds[i]
        for attempt in range(4):
            t0 = time.monotonic()
            m, rep = U.understand(model, g["said"], g["ctx"], g["prev"], g["unsure"], PROFILE,
                                  coding="coding mode on" in g["ctx"].lower() or g["kind"] == "code", timeout=timeout)
            if rep.error == "rate_limit" and attempt < 3:
                time.sleep(max(rep.retry_after, 15 * (attempt + 1)))
                continue
            break
        res = {"id": i, "model": model, "grade": grade(g, m), "kind": (m or {}).get("kind"), "meaning": m,
               "seconds": round(rep.seconds, 2), "tokens_in": rep.tokens_in, "tokens_out": rep.tokens_out,
               "cached": rep.cached, "error": rep.error, "detail": rep.detail[:200]}
        with lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        timeouts = timeouts + 1 if rep.error == "timeout" else 0
        if timeouts >= 4:
            with lock:
                print(f"[{model}] 4 timeouts in a row: stopped", flush=True)
            return
        if n % 20 == 0:
            with lock:
                print(f"[{model}] {n} done", flush=True)
        time.sleep(max(0.0, gap - (time.monotonic() - t0)))
    with lock:
        print(f"[{model}] finished", flush=True)


def report(write: bool = True) -> str:
    golds = gold()
    rows = []
    for path in sorted(OUT.glob("understand__*.jsonl")):
        res, calls, outages = {}, 0, 0
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            calls += 1
            outages += r.get("error") in _RETRY
            if r["id"] not in res or res[r["id"]].get("error") in _RETRY:
                res[r["id"]] = r  # a real answer counts; an outage only until it's retried
        rs = list(res.values())
        if not rs:
            continue
        c = Counter(r["grade"] for r in rs)
        secs = sorted(r["seconds"] for r in rs if not r["error"])
        by_kind = defaultdict(lambda: [0, 0])
        for r in rs:
            k = golds[r["id"]]["kind"]
            by_kind[k][1] += 1
            by_kind[k][0] += r["grade"] == "pass"
        n = len(rs)
        rows.append({
            "model": rs[0]["model"], "n": n, "pass": c["pass"] / n, "wrong_action": c["wrong_action"] / n,
            "wrong_kind": c["wrong_kind"] / n, "missing": c["missing"] / n, "error": c["error"] / n,
            "median": statistics.median(secs) if secs else 0, "p90": secs[int(len(secs) * 0.9) - 1] if secs else 0,
            "tin": statistics.mean(r["tokens_in"] for r in rs), "tout": statistics.mean(r["tokens_out"] for r in rs),
            "cached": statistics.mean(r["cached"] for r in rs),
            "kinds": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_kind.items())}, "avail": 1 - outages / calls,
        })
    rows.sort(key=lambda r: (-r["pass"], r["wrong_action"], r["median"]))
    out = ["| Model | Sentences | Available | Right | Wrong action | Wrong kind | Missing detail | No answer | Median s | Slow 10% s | Tokens in/out (cached) | act | ignore | chat | ask | code | refuse | control |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        k = r["kinds"]
        out.append(f"| {r['model']} | {r['n']} | {r['avail']:.0%} | **{r['pass']:.0%}** | {r['wrong_action']:.0%} | {r['wrong_kind']:.0%} | "
                   f"{r['missing']:.0%} | {r['error']:.0%} | {r['median']:.1f} | {r['p90']:.1f} | "
                   f"{r['tin']:.0f}/{r['tout']:.0f} ({r['cached']:.0f}) | " +
                   " | ".join(k.get(x, "-") for x in ("act", "ignore", "chat", "ask", "code", "refuse", "control")) + " |")
    table = "\n".join(out)
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=["understand", "report", "failures"])
    ap.add_argument("--models", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N sample sentences (a quick look)")
    ap.add_argument("--model", default="", help="failures: which model")
    args = ap.parse_args()
    golds = gold()
    if args.job == "report":
        print(report())
        return
    if args.job == "failures":
        path = next(OUT.glob("understand__" + args.model.replace(":", "__").replace("/", "_").replace("@", "") + ".jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["grade"] != "pass":
                g = golds[r["id"]]
                print(f"[{r['grade']}] {g['said'][:80]!r}\n   want {g['kind']}/{g['intent']} {g['must']}  "
                      f"got {json.dumps(r['meaning'], ensure_ascii=False)[:220] if r['meaning'] else r['error'] + ' ' + r['detail'][:100]}")
        return
    ids = sample_ids(golds)
    if args.limit:
        ids = ids[:args.limit]
    models = CANDIDATES if args.all else [m for m in args.models.split(",") if m]
    print(f"{len(ids)} sentences x {len(models)} models", flush=True)
    lock = threading.Lock()
    threads = [threading.Thread(target=run_model, args=(m, ids, golds, lock), daemon=True) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(report())


if __name__ == "__main__":
    main()
