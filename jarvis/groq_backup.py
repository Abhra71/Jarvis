"""Groq: the fast brain (~1 s) for commands and questions.

Groq speaks the OpenAI chat format, so this converts Jarvis's Gemini-style tool
declarations and conversation into that format and runs the same tool loop.

Groq's free tier limits tokens per minute *per model*, so we move down a list of
models when one is rate-limited. Its models can't see: when a request needs the
screen, it raises NeedsVision and brain.py hands the request to Gemini, along
with the steps already done (unless a Groq vision model is configured).
"""

import base64
import json
import logging
import time

import httpx

from .notify import popup
from .usage import usage

log = logging.getLogger(__name__)

API = "https://api.groq.com/openai/v1"

DEFAULT_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


class NeedsVision(Exception):
    """The AI wanted to see the screen but Groq can't. `done` lists the steps already carried out, so the
    next AI continues instead of repeating them; `image` is the screenshot that was taken."""

    def __init__(self, done: list[str], image: bytes):
        super().__init__("needs vision")
        self.done = done
        self.image = image


def _schema(s, _in_properties=False):
    """Gemini schema (type: 'STRING') -> JSON schema (type: 'string').

    Per-parameter descriptions are dropped: Groq's free tier counts every token, and the
    parameter names plus the tool's own description are enough for it.
    """
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            if k == "description" and _in_properties:
                continue
            if k == "type" and isinstance(v, str):
                out[k] = v.lower()
            elif k == "properties":
                out[k] = {name: _schema(p, True) for name, p in v.items()}
            else:
                out[k] = _schema(v)
        return out
    if isinstance(s, list):
        return [_schema(x) for x in s]
    return s


def _text(content: dict) -> str:
    return " ".join(p["text"] for p in content.get("parts", []) if "text" in p and not p.get("thought")).strip()


class GroqBackup:
    def __init__(self, key: str, cfg: dict, http: httpx.Client):
        self.key = key
        self.models = cfg.get("groq_models", DEFAULT_MODELS)
        self.vision_model = cfg.get("groq_vision_model") or None
        self.http = http
        # Groq counts max_tokens against its 8k tokens/minute up front, so ask only for what a reply needs
        # (1024 used up the minute after a few requests on 27 Sep).
        self.max_tokens = cfg.get("groq_max_tokens", 400)  # gpt-oss also spends some on thinking; ~125 is typical

    def _complete(self, models: list[str], body: dict) -> dict:
        """Try each model in turn until one isn't rate-limited, busy, or retired."""
        last = ""
        # A malformed tool call (400 "tool_use_failed" / "tool call validation failed") is the model's slip,
        # not an outage: ask the same model once more, then the next one (27 Sep: 3 turns fell to slow Gemini).
        # Share the load: each model has its own 8k tokens/minute, so ask the one with the most left
        # instead of draining the first (27 Sep: both hit 429 in one Bluetooth task, then a 60 s Gemini wait).
        if len(models) > 1:
            left = {m: usage.tokens_left(f"groq:{m}") for m in models}
            models = sorted(models, key=lambda m: -(left[m] if left[m] is not None else 1e9))
        queue = [(m, 0) for m in models]
        while queue:
            model, tries = queue.pop(0)
            if len(models) > 1 and usage.is_limited(f"groq:{model}"):
                continue  # hit its per-minute limit moments ago; don't waste a request
            t0 = time.monotonic()
            try:
                r = self.http.post(f"{API}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                   json={**body, "model": model})
            except httpx.TimeoutException:
                usage.api_call("groq", model, "timeout", time.monotonic() - t0)
                last = f"{model} timed out"
                continue
            h = r.headers if isinstance(getattr(r, "headers", None), (dict, httpx.Headers)) else {}
            limits = {k: h.get(f"x-ratelimit-{k}") for k in
                      ("remaining-requests", "limit-requests", "remaining-tokens", "limit-tokens")}
            u = r.json().get("usage", {}) if r.status_code == 200 else {}
            retry_after = h.get("retry-after")
            usage.api_call("groq", model, r.status_code, time.monotonic() - t0,
                           u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
                           limits if any(limits.values()) else None,
                           limited_for=int(float(retry_after)) + 1 if r.status_code == 429 and retry_after else None)
            if r.status_code == 200:
                if model != models[0]:
                    log.info("Groq answered with %s", model)
                if last:  # an earlier model failed (limit, timeout, outage): a real fallback, not load-sharing
                    popup(f"Groq {last.split()[0].split('/')[-1]} unavailable → {model.split('/')[-1]}",
                          f"groq-{model}")
                return r.json()["choices"][0]["message"]
            last = f"{model} {r.status_code}: {r.text[:150]}"
            log.warning("Groq %s", last)
            if r.status_code == 400 and ("tool" in r.text.lower() or "json_validate" in r.text.lower()):
                if tries == 0:
                    queue.insert(0, (model, 1))
                continue
            if r.status_code not in (404, 429, 500, 503):  # 404: model retired, try the next
                break
        raise RuntimeError(f"Groq failed ({last})")

    def complete(self, system: str, user: str, max_tokens: int = 900) -> str:
        """One plain JSON answer, no tools (the agent's plan). Low reasoning effort: planning from a list of
        tools and the screen as text doesn't need long thinking, and thinking tokens count against the limit."""
        msg = self._complete(self.models, {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
            "reasoning_effort": "low"})
        return msg.get("content") or ""

    def ask(self, system: str, history: list[dict], text: str, declarations,
            call_tool, max_steps: int = 6, finish=None, context: str = "") -> tuple[str, list[dict]]:
        """Returns (reply, what to add to the shared history in Gemini format).

        declarations: a list, or a function returning the current list (the tools can grow mid-request).
        finish(tool_names, results, said) -> reply to speak now, or None to ask the AI again.
        context: extra text sent with the request (e.g. the on-screen items) but not kept in history.
        """
        messages = [{"role": "system", "content": system}]
        for c in history:  # earlier turns as plain text; tool details aren't needed
            t = _text(c)
            if t:
                messages.append({"role": "assistant" if c["role"] == "model" else "user", "content": t})
        messages.append({"role": "user", "content": f"{text}\n{context}" if context else text})
        def tools():
            decls = declarations() if callable(declarations) else declarations
            return [{"type": "function", "function": {
                "name": d["name"], "description": d["description"],
                "parameters": _schema(d.get("parameters", {"type": "OBJECT", "properties": {}}))}} for d in decls]

        models = self.models
        done: list[str] = []  # steps carried out, for a hand-over to an AI that can see
        t0 = time.monotonic()
        for _ in range(max_steps):
            msg = self._complete(models, {"messages": messages, "tools": tools(), "temperature": 0.4,
                                           "max_tokens": self.max_tokens})
            calls = msg.get("tool_calls") or []
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v is not None})
            if not calls:
                reply = (msg.get("content") or "Done.").strip()
                log.info("Groq answered in %.1fs", time.monotonic() - t0)
                return reply, [{"role": "user", "parts": [{"text": text}]},
                               {"role": "model", "parts": [{"text": reply}]}]

            images, results = [], []
            for call in calls:
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                result = call_tool(call["function"]["name"], args)
                if isinstance(result, dict):  # a screenshot
                    images.append(result["image_jpeg"])
                    result = result["text"]
                elif call["function"]["name"] not in ("more_tools", "look_at_screen"):
                    done.append(f"{call['function']['name']}: {result}")
                results.append(result)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(result)})
            quick = None if images or not finish else finish(
                [c["function"]["name"] for c in calls], results, (msg.get("content") or "").strip())
            if quick:
                log.info("Groq answered in %.1fs (fast finish)", time.monotonic() - t0)
                return quick, [{"role": "user", "parts": [{"text": text}]}, {"role": "model", "parts": [{"text": quick}]}]
            if images and not self.vision_model:
                raise NeedsVision(done, images[-1])
            if images:
                # Tool messages can't carry images in this format, so show it as a user message,
                # and finish the turn on the model that can actually see.
                content = [{"type": "text", "text": "Here is the screenshot you asked for."}]
                content += [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(j).decode()}}
                            for j in images]
                messages.append({"role": "user", "content": content})
                models = [self.vision_model]
        return "That took too many steps, so I stopped.", [{"role": "user", "parts": [{"text": text}]},
                                                           {"role": "model", "parts": [{"text": "(stopped)"}]}]
