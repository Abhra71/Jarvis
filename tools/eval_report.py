"""Summarise logs/ai_eval.jsonl as a comparison table (latest run per model and suite).

    .venv\\Scripts\\python tools\\eval_report.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    latest = {}
    for line in (ROOT / "logs" / "ai_eval.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for suite in ("text", "screen"):
            rows = [x for x in r.get("rows", []) if x["suite"] == suite]
            if rows:
                latest[(r["model"], suite)] = rows
    print(f"{'model':48} {'suite':6} {'right':>9} {'errors':>6} {'median':>7} {'slowest':>7} {'tok in':>7} {'tok out':>7}")
    for (model, suite), rows in sorted(latest.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        ok = [x for x in rows if x.get("status") == 200]
        err = len(rows) - len(ok)
        if not ok:
            print(f"{model:48} {suite:6} {'-':>9} {err:>6}   (all failed: {rows[0].get('error', '')[:60]})")
            continue
        right = sum(x["score"] for x in ok)
        secs = sorted(x["seconds"] for x in ok)
        med = secs[len(secs) // 2]
        tin = sum(x["tokens_in"] for x in ok) / len(ok)
        tout = sum(x["tokens_out"] for x in ok) / len(ok)
        print(f"{model:48} {suite:6} {right:>4g}/{len(rows):<4} {err:>6} {med:>6.1f}s {secs[-1]:>6.1f}s {tin:>7.0f} {tout:>7.0f}")


if __name__ == "__main__":
    main()
