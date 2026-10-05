"""One way to call every AI model Jarvis may use, and an honest record of how each call went.

All four providers speak the OpenAI chat format, so a model is just "provider:model":
    groq:openai/gpt-oss-20b    gemini:gemini-3.5-flash-lite    nvidia:nvidia/nemotron-3-super-120b-a12b
    cloudflare:@cf/meta/llama-3.3-70b-instruct-fp8-fast
Each call returns a Reply with the text, the time it took, the tokens (and how many were cached), and, when it
failed, what kind of failure it was (rate limit, timeout, server, auth, gone, bad request). The pipeline uses
these to pick the next model; the benchmark uses them to rank models. Keys come from .env, never from code.
"""

import json
import re
import time
from dataclasses import dataclass, field

import httpx

from ..brain import load_api_key
from ..config import load_config

PROVIDERS = {
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "keys": ("GROQ_API_KEY",)},
    "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "keys": ("GEMINI_API_KEY",)},
    "nvidia": {"url": "https://integrate.api.nvidia.com/v1/chat/completions", "keys": ("NVIDIA_API_KEY",)},
    "cloudflare": {"url": "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions",
                   "keys": ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY")},
}

# Thinking models answer much faster with little thinking; for a short JSON decision "low" is plenty.
_LOW_EFFORT = re.compile(r"gpt-oss|qwen3|nemotron|gemini-3|deepseek", re.I)


@dataclass
class Reply:
    model: str
    text: str = ""
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cached: int = 0
    error: str = ""          # "", rate_limit, timeout, server, auth, gone, bad_request, network, empty
    detail: str = ""
    retry_after: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error


def split(model: str) -> tuple[str, str]:
    provider, _, name = model.partition(":")
    if provider not in PROVIDERS or not name:
        raise ValueError(f"models look like 'groq:openai/gpt-oss-20b', got {model!r}")
    return provider, name


def key_for(provider: str) -> str | None:
    for name in PROVIDERS[provider]["keys"]:
        k = load_api_key(name)
        if k:
            return k
    return None


def _url(provider: str) -> str:
    url = PROVIDERS[provider]["url"]
    if "{account}" in url:
        account = load_config().get("ai", {}).get("cloudflare_account_id", "")
        url = url.replace("{account}", account)
    return url


_client = httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))


def call(model: str, messages: list[dict], *, json_mode: bool = True, max_tokens: int = 700,
         timeout: float = 20.0, effort: str | None = "low", temperature: float = 0.0) -> Reply:
    """One chat call. Never raises: a failure comes back as Reply.error."""
    provider, name = split(model)
    key = key_for(provider)
    if not key:
        return Reply(model, error="auth", detail=f"no key for {provider} in .env")
    body = {"model": name, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if effort and _LOW_EFFORT.search(name):
        body["reasoning_effort"] = effort
    t = time.monotonic()
    for attempt in range(2):
        try:
            r = _client.post(_url(provider), headers={"Authorization": f"Bearer {key}"}, json=body, timeout=timeout)
        except httpx.TimeoutException:
            return Reply(model, seconds=time.monotonic() - t, error="timeout")
        except httpx.HTTPError as e:
            return Reply(model, seconds=time.monotonic() - t, error="network", detail=type(e).__name__)
        if r.status_code == 400 and attempt == 0 and ("reasoning_effort" in body or "response_format" in body):
            # Some models refuse one of the options: try once without them (and remember it in the reply).
            msg = r.text.lower()
            if "reasoning" in msg and "reasoning_effort" in body:
                body.pop("reasoning_effort")
                continue
            if ("response_format" in msg or "json" in msg) and "response_format" in body:
                body.pop("response_format")
                continue
        break
    secs = time.monotonic() - t
    if r.status_code != 200:
        kind = {429: "rate_limit", 401: "auth", 403: "auth", 404: "gone", 410: "gone", 400: "bad_request",
                413: "bad_request"}.get(r.status_code, "server" if r.status_code >= 500 else "bad_request")
        retry = r.headers.get("retry-after")
        return Reply(model, seconds=secs, error=kind, detail=f"HTTP {r.status_code}: {r.text[:200]}",
                     retry_after=float(retry) if retry and retry.replace(".", "").isdigit() else 0.0)
    try:
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    except (ValueError, AttributeError):
        return Reply(model, seconds=secs, error="bad_request", detail="not JSON")
    if not text.strip():
        return Reply(model, seconds=secs, error="empty", detail=str(data)[:200])
    return Reply(model, text=text, seconds=secs, tokens_in=usage.get("prompt_tokens", 0) or 0,
                 tokens_out=usage.get("completion_tokens", 0) or 0, cached=cached,
                 extra={"no_effort": "reasoning_effort" not in body, "no_json_mode": "response_format" not in body,
                        "limits": _limits(r.headers)})


def _limits(headers) -> dict:
    """What the provider says is left (Groq: requests left today, tokens left this minute). Empty for the others."""
    out = {}
    for name, key in (("x-ratelimit-remaining-requests", "requests_left"), ("x-ratelimit-remaining-tokens", "tokens_left"),
                      ("x-ratelimit-limit-requests", "requests_limit"), ("x-ratelimit-limit-tokens", "tokens_limit")):
        v = headers.get(name)
        if v and v.isdigit():
            out[key] = int(v)
    return out


def parse_json(text: str) -> dict | None:
    """The first JSON object in a reply (models sometimes wrap it in ``` fences or add a sentence)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(text[start:i + 1])
                        return v if isinstance(v, dict) else None
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None
