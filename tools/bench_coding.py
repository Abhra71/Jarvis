"""Benchmark the coding expert: every model, the same coding cases, every answer compiled by the real compiler.

    .venv\\Scripts\\python tools\\bench_coding.py --models groq:openai/gpt-oss-120b,gemini:gemini-3.5-flash
    .venv\\Scripts\\python tools\\bench_coding.py --all
    .venv\\Scripts\\python tools\\bench_coding.py report
    .venv\\Scripts\\python tools\\bench_coding.py failures --model groq:openai/gpt-oss-120b

Cases: data/gold/coding.jsonl (tools/gold_coding.py: the user's real coding sentences + student-style ones).
Grades:
- pass:          the right kind; an edit compiles and has what it must (and not what it mustn't).
- no_compile:    an edit that doesn't compile (Jarvis would refuse it: the user hears "that would break the code").
- wrong_code:    compiles, but isn't what was asked.
- wrong_action:  WROTE code where it should have asked (a clash, a missing detail, deleting everything).
- wrong_kind:    asked/ignored where it should have written.
- error:         no usable answer.
"""

import argparse
import hashlib
import json
import re
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from bench import CANDIDATES, GAP  # noqa: E402
from jarvis import codecheck  # noqa: E402
from jarvis.llm import coder  # noqa: E402

GOLD = ROOT / "data" / "gold" / "coding.jsonl"
OUT = ROOT / "data" / "bench" / ("coding-" + hashlib.sha1(coder.SYSTEM.encode()).hexdigest()[:8])


from bench import _RETRY  # noqa: E402


def cases() -> dict[int, dict]:
    return {c["id"]: c for c in (json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines())}


def file_name(c: dict) -> str:
    if c["lang"] == "cpp":
        return "main.cpp"
    m = re.search(r"\bclass\s+(\w+)", c["file"]) or re.search(r"\bclass\s+(?:called\s+)?(\w+)", c["said"], re.I)
    return (m.group(1) if m else "Main") + ".java"


def grade(c: dict, out: dict | None) -> tuple[str, str]:
    if out is None:
        return "error", ""
    kind = out.get("kind")
    if c["expect"] == "ask":
        if kind == "ask":
            return "pass", ""
        return ("wrong_action", "wrote code instead of asking") if kind == "edit" else ("wrong_kind", kind)
    if c["expect"] == "cursor":
        return ("pass", "") if kind == "cursor" else ("wrong_kind", kind)
    if kind != "edit":
        return "wrong_kind", str(kind)
    code = str(out.get("code") or "")
    errs = codecheck.errors(code, c["lang"])
    if errs:
        return "no_compile", "; ".join(e.message for e in errs[:2])
    missing = [h for h in c["has"] if not re.search(h, code, re.M)]
    extra = [n for n in c["not"] if re.search(n, code, re.M)]
    if missing or extra:
        return "wrong_code", f"missing {missing[:2]} / unwanted {extra[:2]}"
    return "pass", ""


def run_model(model: str, cs: dict, lock: threading.Lock):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (model.replace(":", "__").replace("/", "_").replace("@", "") + ".jsonl")
    done = set()
    if path.exists():
        done = {json.loads(l)["id"] for l in path.read_text(encoding="utf-8").splitlines()
                if json.loads(l).get("error") not in _RETRY}
    gap = GAP[model.split(":")[0]]
    timeouts = 0
    for n, c in enumerate(c for c in cs.values() if c["id"] not in done):
        for attempt in range(4):
            t0 = time.monotonic()
            out, rep = coder.edit(model, c["lang"], c["said"], c["file"], c["cursor"], c["previous"], file_name(c))
            if rep.error == "rate_limit" and attempt < 3:
                time.sleep(max(rep.retry_after, 20 * (attempt + 1)))
                continue
            break
        g, why = grade(c, out)
        res = {"id": c["id"], "model": model, "grade": g, "why": why[:300], "kind": (out or {}).get("kind"),
               "out": out, "seconds": round(rep.seconds, 2), "tokens_in": rep.tokens_in, "tokens_out": rep.tokens_out,
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


def report() -> str:
    cs = cases()
    rows = []
    for path in sorted(OUT.glob("*.jsonl")):
        res = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            res[r["id"]] = r
        rs = list(res.values())
        if not rs:
            continue
        n = len(rs)
        c = Counter(r["grade"] for r in rs)
        user = [r for r in rs if cs[r["id"]]["source"] == "user"]
        secs = sorted(r["seconds"] for r in rs if not r["error"])
        rows.append((rs[0]["model"], n, c["pass"] / n, sum(r["grade"] == "pass" for r in user), len(user),
                     c["no_compile"] / n, c["wrong_code"] / n, c["wrong_action"] / n, c["wrong_kind"] / n,
                     c["error"] / n, statistics.median(secs) if secs else 0,
                     secs[int(len(secs) * 0.9) - 1] if secs else 0))
    rows.sort(key=lambda r: (-r[2], r[7], r[10]))
    out = ["| Model | Cases | Right | User's own | Doesn't compile | Wrong code | Wrote instead of asking | Asked instead of writing | No answer | Median s | Slow 10% s |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, n, p, up, un, nc, wc, wa, wk, er, med, p90 in rows:
        out.append(f"| {m} | {n} | **{p:.0%}** | {up}/{un} | {nc:.0%} | {wc:.0%} | {wa:.0%} | {wk:.0%} | {er:.0%} | {med:.1f} | {p90:.1f} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job", nargs="?", default="run", choices=["run", "report", "failures"])
    ap.add_argument("--models", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.job == "report":
        print(report())
        return
    cs = cases()
    if args.job == "failures":
        path = OUT / (args.model.replace(":", "__").replace("/", "_").replace("@", "") + ".jsonl")
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["grade"] != "pass":
                c = cs[r["id"]]
                print(f"[{r['grade']}] ({c['source']}) {c['said'][:70]!r}: {r['why'][:160] or r['error']}")
        return
    models = CANDIDATES if args.all else [m for m in args.models.split(",") if m]
    print(f"{len(cs)} cases x {len(models)} models", flush=True)
    lock = threading.Lock()
    threads = [threading.Thread(target=run_model, args=(m, cs, lock), daemon=True) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(report())


if __name__ == "__main__":
    main()
