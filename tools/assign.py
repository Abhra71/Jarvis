"""Turn benchmark results into each job's model chain (data/pipeline.json) by fixed rules, not opinion.

    .venv\\Scripts\\python tools\\assign.py            # print the chains and why
    .venv\\Scripts\\python tools\\assign.py --write    # also save data/pipeline.json (the router reads it)

Rules (the same for every job):
1. Score = right answers - 2 x wrong actions (a confident wrong action on the user's PC costs more than a question).
   Leaders within 3 points of the best: the fastest leads.
2. Can lead a chain only if: available >= 95% of calls, median answer <= the job's time budget
   (understanding 2 s, coding 3 s). Backups: available >= 90% and median <= twice the budget, if any are.
3. The chain is the best leader, then the next best models, preferring a DIFFERENT provider for each next place
   (one company's outage can't take Jarvis down), up to 4 models.
4. A model with fewer than 60 graded answers is listed as "not enough data" and never leads.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import bench  # noqa: E402
import bench_coding  # noqa: E402

BUDGET = {"understand": 2.0, "code": 3.0}  # median seconds a leader may take (a stressed user won't wait 6 s a line)


def rows_understand() -> list[dict]:
    golds = bench.gold()
    out = []
    for path in sorted(bench.OUT.glob("understand__*.jsonl")):
        out.append(_summarise(path, lambda r: "error" if r.get("error") else bench.grade(golds[r["id"]], r["meaning"])))
    return out


def rows_code() -> list[dict]:
    cs = bench_coding.cases()
    out = []
    for path in sorted(bench_coding._dir(True).glob("*.jsonl")):  # as Jarvis runs it: with the one repair
        # the grade saved at run time (each answer was compiled then; compiling hundreds again takes minutes)
        out.append(_summarise(path, lambda r: "error" if r.get("error") else r["grade"]))
    return out


def _summarise(path: Path, grade) -> dict:
    res, calls, outages = {}, 0, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        calls += 1
        outages += r.get("error") in bench._RETRY
        if r["id"] not in res or res[r["id"]].get("error") in bench._RETRY:
            res[r["id"]] = r
    rs = [r for r in res.values() if r.get("error") not in bench._RETRY]
    grades = [grade(r) for r in rs]
    n = len(grades) or 1
    secs = sorted(r["seconds"] for r in rs)
    right = grades.count("pass") / n
    wrong = grades.count("wrong_action") / n
    return {"model": next(iter(res.values()))["model"] if res else path.stem, "n": len(grades),
            "available": 1 - outages / max(calls, 1), "right": right, "wrong_action": wrong,
            "score": right - 2 * wrong, "median": secs[len(secs) // 2] if secs else 99.0}


def chain(rows: list[dict], budget: float) -> tuple[list[str], list[str]]:
    why = []
    ok = [r for r in rows if r["n"] >= 60]
    for r in rows:
        if r["n"] < 60:
            why.append(f"{r['model']}: not enough data ({r['n']} answers)")
    ranked = sorted(ok, key=lambda r: -r["score"])
    leaders = [r for r in ranked if r["available"] >= 0.95 and r["median"] <= budget]
    if not leaders:
        return [], why + ["no model meets the leader rules"]
    # Within 3 points of the best leader, the faster one leads (6 Oct live: 94% at 2.2 s and flaky vs 92% at
    # 0.8 s; a stressed user feels the seconds, not 2 points).
    close = [r for r in leaders if r["score"] >= leaders[0]["score"] - 0.03]
    leaders = sorted(close, key=lambda r: r["median"]) + [r for r in leaders if r not in close]
    picked = [leaders[0]]
    why.append(f"leader {leaders[0]['model']}: right {leaders[0]['right']:.0%}, wrong actions "
               f"{leaders[0]['wrong_action']:.0%}, {leaders[0]['median']:.1f} s, available {leaders[0]['available']:.0%}")
    # Backups must be usable when needed: available >= 90% and no slower than twice the budget; the rest only if
    # nothing else is left (6 Oct: a 4.4 s, 82%-available model had been picked over a 1.0 s, 100% one).
    good = [r for r in ranked if r is not leaders[0] and r["available"] >= 0.9 and r["median"] <= 2 * budget]
    rest = good + [r for r in ranked if r is not leaders[0] and r not in good and r["available"] >= 0.8]
    while rest and len(picked) < 4:
        used = {p["model"].split(":")[0] for p in picked}
        other = [r for r in rest if r["model"].split(":")[0] not in used and r in good]
        nxt = (other or [r for r in rest if r in good] or rest)[0]
        picked.append(nxt)
        rest.remove(nxt)
        why.append(f"then {nxt['model']}: right {nxt['right']:.0%}, wrong actions {nxt['wrong_action']:.0%}, "
                   f"{nxt['median']:.1f} s, available {nxt['available']:.0%}")
    return [p["model"] for p in picked], why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    chains, notes = {}, {}
    for job, rows in (("understand", rows_understand()), ("code", rows_code())):
        if not rows:
            print(f"{job}: no results yet")
            continue
        chains[job], notes[job] = chain(rows, BUDGET[job])
        print(f"\n{job}: {' -> '.join(chains[job]) or '(none)'}")
        for w in notes[job]:
            print("  " + w)
    if args.write:
        from jarvis.llm.router import PIPELINE
        PIPELINE.write_text(json.dumps({"chains": chains, "why": notes}, indent=1), encoding="utf-8")
        print(f"\nsaved {PIPELINE}")
        doc = ROOT / "docs" / "model-benchmark.md"
        parts = ["# Which model does which job, and why",
                 "",
                 "Made by `tools/assign.py --write` from the benchmark results. Do not edit by hand: re-run the "
                 "benchmarks (`tools/bench.py understand --all`, `tools/bench_coding.py --repair --all`) and this tool.",
                 "",
                 f"Updated: {__import__('time').strftime('%d %b %Y %H:%M')}",
                 "",
                 "## The chains (the router tries them in this order)"]
        for job in chains:
            parts += ["", f"**{job}:** " + " → ".join(f"`{m}`" for m in chains[job])]
            parts += [f"- {w}" for w in notes[job]]
        parts += ["", "## Understanding: the user's real sentences",
                  "", "Each model got the same 167 sentences (a fixed sample of the 537 the user really said, labelled "
                  "by hand with the screen they were said on). *Wrong action* = it acted, but wrongly or where it "
                  "should have asked/ignored: the worst outcome. *Available* = calls that got an answer (the free "
                  "tiers are sometimes overloaded).", "", bench.report()]
        parts += ["", "## Coding: Java (BlueJ) and C++ (VS Code)",
                  "", "118 cases: the user's 25 real coding sentences on the file they had, plus 93 student-style "
                  "ones. Every edit compiled by the real javac / g++. With one repair try (as Jarvis runs it).",
                  "", bench_coding.report(repair=True)]
        doc.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")
        print(f"saved {doc}")


if __name__ == "__main__":
    main()
