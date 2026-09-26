"""Accuracy + speed + token check for AI models, across providers (Gemini, Groq, Mistral, NVIDIA, OpenRouter).

Nothing is executed: only the AI's *first chosen action* is checked. Two suites:
- text:   16 typical spoken requests -> is the chosen tool (or a plain reply) right?
- screen: 12 click tasks on synthetic screens (tools/eval_screens.py) -> does the click land on the target?

Jarvis's real system prompt and tool list are used, but with FAKE window/profile names, so nothing personal
is sent to the services being tested. Results are appended as JSON lines to logs/ai_eval.jsonl.

    .venv\\Scripts\\python tools\\ai_eval.py --models gemini:gemini-3.1-flash-lite groq:openai/gpt-oss-120b
    .venv\\Scripts\\python tools\\ai_eval.py --models nvidia:meta/muse-glimmer-30b --suite screen
"""

import argparse
import base64
import json
import logging
import statistics
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
logging.disable(logging.WARNING)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # model replies can hold any character

import httpx  # noqa: E402

import eval_screens  # noqa: E402
from jarvis.brain import SYSTEM_PROMPT, load_api_key  # noqa: E402
from jarvis.skills import Skills  # noqa: E402

PROVIDERS = {  # name: (OpenAI-compatible base URL, key name in .env)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"

TEXT = "(reply)"  # the right answer is words, not an action
TEXT_CASES = [
    ("open youtube in my main profile", {"open_website"}),
    ("search lofi music on youtube", {"web_search"}),
    ("what's the capital of peru", {TEXT}),
    ("close this tab", {"browser"}),
    ("volume 30", {"volume"}),
    ("set a timer for 10 minutes", {"timer"}),
    ("minimise chrome", {"window"}),
    ("close the chess tab", {"close_tab_named"}),
    ("open notepad", {"open_app"}),
    ("go back", {"browser"}),
    ("find my resume in downloads", {"find_files", "list_folder"}),
    ("create a folder called trips on the desktop", {"create_folder"}),
    ("who won the latest IPL final", {"web_search"}),
    ("1, 2, 4", {TEXT}),
    ("delete the file todo.txt on my desktop", {TEXT}),
    ("send hi to mom on whatsapp", {TEXT, "open_app", "window"}),
]

FAKE_PROMPT = SYSTEM_PROMPT.format(
    now="Saturday 26 September 2026, 09:30 PM", sound="",
    front="Google Chrome - New Tab", windows="Google Chrome - New Tab; File Explorer - Downloads",
    profiles="1. Main (nicknames: main, personal) [folder: Default]; 2. Work (nickname: AI) [folder: Profile 2]; "
             "3. Backup [folder: Profile 3]")


def _schema(s, in_props=False):
    """Gemini schema (type 'STRING') -> JSON schema ('string'); per-parameter descriptions dropped (tokens)."""
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            if k == "description" and in_props:
                continue
            if k == "type" and isinstance(v, str):
                out[k] = v.lower()
            elif k == "properties":
                out[k] = {n: _schema(p, True) for n, p in v.items()}
            else:
                out[k] = _schema(v)
        return out
    if isinstance(s, list):
        return [_schema(x) for x in s]
    return s


class Caller:
    def __init__(self, provider: str, model: str, decls: list[dict], thinking: str | None = None):
        self.provider, self.model, self.decls, self.thinking = provider, model, decls, thinking
        self.http = httpx.Client(timeout=60)
        self.limits = {}
        if provider == "gemini":
            self.key = load_api_key("GEMINI_API_KEY")
        else:
            base, env = PROVIDERS[provider]
            self.base, self.key = base, load_api_key(env)
            # Some providers (Mistral) insist on a parameters object even for tools that take none.
            self.tools = [{"type": "function", "function": {"parameters": {"type": "object", "properties": {}},
                                                            **_schema(d)}} for d in decls]

    def ask(self, text: str, jpeg: bytes | None = None):
        """-> (status, seconds, calls [(name, args)], said, tokens_in, tokens_out, error text)"""
        t0 = time.monotonic()
        try:
            return self._ask(text, jpeg)
        except httpx.TimeoutException:
            return "timeout", time.monotonic() - t0, [], "", 0, 0, "no answer within 60 s"
        except Exception as e:  # a strange reply shouldn't stop the whole run
            return "bad-reply", time.monotonic() - t0, [], "", 0, 0, f"{type(e).__name__}: {e}"

    def _ask(self, text: str, jpeg: bytes | None = None):
        if self.provider == "gemini":
            parts = [{"text": text}]
            if jpeg:
                parts += [{"text": "(The current screen is attached; positions are x,y from 0 to 1000.)"},
                          {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}}]
            gen = {"temperature": 0.4, "maxOutputTokens": 2048}
            if self.thinking:
                gen["thinkingConfig"] = {"thinkingLevel": self.thinking}
            body = {"system_instruction": {"parts": [{"text": FAKE_PROMPT}]},
                    "contents": [{"role": "user", "parts": parts}],
                    "tools": [{"functionDeclarations": self.decls}], "generationConfig": gen}
            t0 = time.monotonic()
            r = self.http.post(f"{GEMINI_API}/models/{self.model}:generateContent",
                               headers={"x-goog-api-key": self.key}, json=body)
            dt = time.monotonic() - t0
            if r.status_code != 200:
                return r.status_code, dt, [], "", 0, 0, r.text[:300]
            d = r.json()
            out = (d.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            calls = [(p["functionCall"]["name"], p["functionCall"].get("args", {})) for p in out if "functionCall" in p]
            said = " ".join(p.get("text", "") for p in out if not p.get("thought")).strip()
            m = d.get("usageMetadata", {})
            return 200, dt, calls, said, m.get("promptTokenCount", 0), \
                m.get("candidatesTokenCount", 0) + m.get("thoughtsTokenCount", 0), ""

        content = text
        if jpeg:
            content = [{"type": "text", "text": text + "\n(The current screen is attached; positions are x,y from 0 to 1000.)"},
                       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}]
        # A small answer budget: Groq counts max_tokens against its 8,000 tokens/minute limit up front.
        body = {"model": self.model, "temperature": 0.4, "max_tokens": 400, "tools": self.tools,
                "tool_choice": "auto",
                "messages": [{"role": "system", "content": FAKE_PROMPT}, {"role": "user", "content": content}]}
        t0 = time.monotonic()
        r = self.http.post(f"{self.base}/chat/completions", headers={"Authorization": f"Bearer {self.key}"}, json=body)
        dt = time.monotonic() - t0
        self.limits.update({k: v for k, v in r.headers.items() if "ratelimit" in k.lower() or k.lower() == "retry-after"})
        if r.status_code != 200:
            return r.status_code, dt, [], "", 0, 0, r.text[:300]
        d = r.json()
        msg = d["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparsed": tc["function"].get("arguments")}
            calls.append((tc["function"]["name"], args))
        said = msg.get("content") or ""
        if isinstance(said, list):
            said = " ".join(c.get("text", "") for c in said if isinstance(c, dict))
        u = d.get("usage") or {}
        return 200, dt, calls, said.strip(), u.get("prompt_tokens", 0), u.get("completion_tokens", 0), ""


def score_screen(calls, targets, truth) -> tuple[float, str]:
    if not calls:
        return 0.0, "no action"
    name, a = calls[0]
    try:
        if len(targets) == 1:
            if name == "click":
                return float(eval_screens.hit(truth[targets[0]], a["x"], a["y"])), f"click {a['x']},{a['y']}"
            return 0.0, f"{name}"
        if name == "click_pair":
            ok = eval_screens.hit(truth[targets[0]], a["x"], a["y"]) and eval_screens.hit(truth[targets[1]], a["x2"], a["y2"])
            return float(ok), f"pair {a['x']},{a['y']}->{a['x2']},{a['y2']}"
        if name == "click":  # only the first half of a two-click move
            return 0.5 * eval_screens.hit(truth[targets[0]], a["x"], a["y"]), f"single click {a['x']},{a['y']}"
        return 0.0, name
    except (KeyError, TypeError, ValueError) as e:
        return 0.0, f"bad args {a} ({e})"


def run_model(spec: str, suites: list[str], gap: float, screens, decls, thinking=None) -> dict:
    provider, model = spec.split(":", 1)
    c = Caller(provider, model, decls, thinking)
    res = {"model": spec, "thinking": thinking, "when": datetime.now().isoformat(timespec="seconds")}
    jobs = []
    if "text" in suites:
        jobs += [("text", t, ok, None) for t, ok in TEXT_CASES]
    if "screen" in suites:
        jobs += [("screen", t, tg, sc) for sc, t, tg in eval_screens.cases()]
    rows, fails = [], 0
    for suite, text, expect, screen in jobs:
        jpeg, truth = screens[screen] if screen else (None, None)
        for attempt in range(3):
            status, dt, calls, said, tin, tout, err = c.ask(text, jpeg)
            if status in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(min(60, float(c.limits.get("retry-after", 20) or 20)))
                continue
            break
        if status != 200:
            fails += 1
            print(f"  {spec:45} ERR {status} {text[:40]!r}: {err[:150]}")
            rows.append({"suite": suite, "text": text, "status": status, "error": err[:300]})
            if fails >= 3 and not any(r.get("status") == 200 for r in rows):
                print(f"  {spec}: giving up (every request failed)")
                break
            time.sleep(gap)
            continue
        if suite == "text":
            got = calls[0][0] if calls else TEXT
            score, detail = float(got in expect), (f"{got}({calls[0][1]})" if calls else said[:60])
        else:
            score, detail = score_screen(calls, expect, truth)
        rows.append({"suite": suite, "text": text, "status": 200, "score": score, "seconds": round(dt, 2),
                     "tokens_in": tin, "tokens_out": tout, "detail": str(detail)[:120]})
        print(f"  {spec:45} {'ok  ' if score == 1 else 'half' if score else 'MISS'} {dt:5.1f}s {text[:38]!r:40} -> {str(detail)[:70]}")
        time.sleep(gap)
    res["rows"] = rows
    res["limits_headers"] = c.limits
    for suite in suites:
        ok = [r for r in rows if r["suite"] == suite and r.get("status") == 200]
        if ok:
            res[suite] = {"score": sum(r["score"] for r in ok), "of": len(ok),
                          "errors": sum(1 for r in rows if r["suite"] == suite and r.get("status") != 200),
                          "median_s": round(statistics.median(r["seconds"] for r in ok), 2),
                          "max_s": max(r["seconds"] for r in ok),
                          "avg_tokens_in": round(statistics.mean(r["tokens_in"] for r in ok)),
                          "avg_tokens_out": round(statistics.mean(r["tokens_out"] for r in ok))}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True, help="provider:model, e.g. groq:openai/gpt-oss-120b")
    ap.add_argument("--suite", default="both", choices=["text", "screen", "both"])
    ap.add_argument("--thinking", help="Gemini 3 thinkingLevel (minimal/low/...)")
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between requests (rate limits)")
    a = ap.parse_args()

    cfg = tomllib.load(open(ROOT / "config.toml", "rb"))
    decls = Skills(cfg, print).declarations()
    suites = ["text", "screen"] if a.suite == "both" else [a.suite]
    screens = eval_screens.build_screens() if "screen" in suites else {}
    out = ROOT / "logs" / "ai_eval.jsonl"
    for spec in a.models:
        res = run_model(spec, suites, a.gap, screens, decls, a.thinking)
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(res) + "\n")
        summary = {s: res.get(s) for s in suites}
        print(f"== {spec}: {json.dumps(summary)}\n   limit headers: {res['limits_headers']}")


if __name__ == "__main__":
    main()
