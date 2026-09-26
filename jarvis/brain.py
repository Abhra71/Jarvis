"""Gemini brain: understands free-form requests, uses Jarvis's tools, and answers questions.

Talks to the Gemini REST API with plain httpx (no google-genai SDK, whose compiled
dependencies Windows Smart App Control may block).
"""

import base64
import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import os
import re
import time
from datetime import datetime

import httpx

from .config import ROOT
from .groq_backup import GroqBackup
from .skills import Skills, desktop, mouse
from .usage import usage

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta"

# Kept compact: it's sent with every request, and the free tiers count tokens.
SYSTEM_PROMPT = """You are Jarvis, a voice assistant on the user's Windows PC. Replies are read aloud: one or two \
short spoken sentences, no markdown/lists/URLs. The user's words come from speech recognition; assume the most \
sensible meaning. Answer general-knowledge questions directly from what you know, without tools or searching.
Only search when they ask you to, or when it needs live data (today's news, weather, scores, prices).

You act only through the tools, like a person at the keyboard and mouse; the user watches the screen.
- Do only what was asked, nothing extra. Afterwards say exactly what you did or opened, by its real name.
- "Open YouTube" = the website (open_website, full URL) unless they say "app". "Search X on YouTube" =
  web_search with that site; if that site is already in front, site_search. "Here", "this tab", "address
  bar" = act on the current tab (address_bar / browser / site_search), not a new window.
- "Third profile" = number 3 in the profile list below. Nicknames (main, AI, backup…) are listed there.
  If a profile request fits none or several, ask which one.
- Recent or changing facts (latest film, current score, news, prices, "this year"): web_search, then read the
  answer from the results on screen. Never answer those from memory; your knowledge may be out of date.
- If a click didn't do what you wanted, don't click the same spot again: look again and aim somewhere else,
  or use the keyboard (Tab to move between fields), or ask the user.
- "Close this" right after you opened a window = close that window. Close a tab only if they say tab.
  "Close both/all of them" = window with action close_all.
- To click: look_at_screen, then click the centre of the item (x,y 0-1000). Skip the browser's tab/toolbar
  strip (top ~10%) unless asked. For "the second video": count page results top to bottom, skipping ads/Shorts.
- Look again after a click only if the next step needs the new screen, or to confirm you opened the right
  thing before saying so. Never claim success you haven't seen.
- To find text on a long page use find_on_page, not repeated scroll-and-look.
- Files: find_files, then open_path / show_in_explorer. Deleting is turned off: never try.
- Ask first (one short question, act only after a clear yes) before anything that sends, posts, buys, pays,
  subscribes, signs in, submits a form, deletes, or changes account settings. Opening, closing or switching
  apps, windows and tabs needs no confirmation. Never type passwords or card numbers.
- If the tool calls you're making finish the request, include your short reply text in the same response.
- "It", "that tab" = what you did last or the front window. If unclear, ask briefly.
- If the request doesn't make sense (e.g. just numbers, a garbled phrase), ask what they meant. Don't act.
- Never read out verification codes, one-time passwords, passwords, card or account numbers you see on
  screen; say that one is shown, without the digits.

Time: {now}
Front window: {front}
Open windows: {windows}
Chrome profiles (pass the folder as `profile`): {profiles}"""


def load_api_key(name: str = "GEMINI_API_KEY") -> str | None:
    key = os.environ.get(name)
    env_file = ROOT / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():  # -sig: Notepad may add a BOM
            if line.strip().startswith(f"{name}="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key or None


_FAILURE_STARTS = ("error", "not allowed", "unknown", "no ", "i couldn't", "i don't", "sorry", "i can only",
                   "needs confirmation", "not clicked")
_YES = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|confirm|confirmed|please do|"
                  r"send it|buy it|post it|delete it|haan|ha)\b", re.I)


def _is_yes(text: str) -> bool:
    return bool(_YES.search(text or ""))
_FAILURE_WORDS = ("doesn't exist", "isn't a", "couldn't find", "won't overwrite", "already exists", "don't see",
                  "may not have worked")


def _looks_failed(result: str) -> bool:
    """Tool results are plain sentences; these are the ones that mean it didn't work."""
    r = str(result).strip().lower()
    return r.startswith(_FAILURE_STARTS) or any(w in r for w in _FAILURE_WORDS)


# Actions whose own result sentence is a fine spoken reply when they're the whole request.
# Deliberately excludes looking, clicking, scrolling, typing and searching files: those
# usually lead to another step, or their success can only be judged by the AI.
_FINISHING_TOOLS = {
    "open_app", "window", "open_chrome", "open_website", "web_search", "browser", "address_bar", "site_search",
    "media", "volume", "timer", "open_path",
    "show_in_explorer", "create_folder", "copy_file", "move_file", "rename_file", "write_text_file",
}
_MULTI_STEP = re.compile(r"\b(and|then|after that|also|once)\b|,")
_LAUNCHING_TOOLS = {"open_app", "open_website", "open_chrome", "open_path", "web_search", "show_in_explorer"}
_QUESTION = re.compile(r"\?\s*$|^\s*(what|who|when|where|which|why|how|is|are|was|were|did|does|do|can|tell me)\b",
                       re.I)


def fast_reply(request: str, calls: list[str], results: list, said: str = "") -> str | None:
    """If this round of actions finishes the request, the sentence to say now (skipping another AI round trip).

    Only for simple finishing actions. Clicks, typing and looking always go back to the AI (and a click gets
    checked on screen), even if the AI already wrote a reply: on 26 Sep that shortcut spoke garbage like
    "hob" and "thought" right after clicks that had missed.
    """
    if not calls or any(isinstance(r, dict) or _looks_failed(r) for r in results):
        return None
    if not all(c in _FINISHING_TOOLS for c in calls):
        return None
    if "web_search" in calls and _QUESTION.search(request):
        # A question answered by searching must be read from the results, not from memory
        # (it opened a search about Ranveer Singh, then answered with outdated facts).
        return None
    if speakable(said):  # the AI already wrote a proper reply alongside the actions
        return said
    if not _MULTI_STEP.search(request.lower()):
        return " ".join(str(r) for r in results)
    return None


def _clean(text: str) -> str:
    text = re.sub(r"^\s*thought\s*\n", "", text)  # a leaked "thinking" label at the start of the reply
    return re.sub(r"[*_#`]+", "", text).strip()


def speakable(text: str) -> bool:
    """Is this a real sentence worth saying? Rejects fragments like "hob", "it", "thought" and garbled
    characters that Gemini occasionally sends alongside its actions."""
    t = (text or "").strip()
    if not t or t.lower().startswith("thought"):
        return False
    ascii_letters = sum(c.isascii() and c.isalpha() for c in t)
    if ascii_letters < 0.6 * sum(not c.isspace() for c in t):
        return False
    if len(t.split()) == 1:  # one-word answers ("Paris.", "Joyful.") are fine; fragments ("hob", "it") aren't
        return ascii_letters >= 3 and (t[0].isupper() or t.endswith((".", "!", "?")))
    return True


def _limit_seconds(r: httpx.Response) -> int:
    """How long to leave a model alone after Gemini says "too many requests".

    Google's reply says which quota ran out. Per-minute ones come with a sensible retry delay;
    for the per-day one (e.g. only 20 free requests/day on full Flash) the suggested delay is
    misleading, so wait an hour before checking again.
    """
    try:
        details = r.json().get("error", {}).get("details", [])
        for d in details:
            for v in d.get("violations", []):
                if "PerDay" in v.get("quotaId", ""):
                    return 3600
        for d in details:
            delay = d.get("retryDelay", "")
            if delay.endswith("s"):
                return max(5, int(float(delay[:-1])) + 1)
    except Exception:
        pass  # unexpected error format: fall back to the default
    return 60


class BrainUnavailable(Exception):
    """No key, no internet, busy, or quota used up: the caller falls back to offline rules."""


class Brain:
    def __init__(self, cfg: dict, skills: Skills):
        self.cfg = cfg
        self.skills = skills
        self.key = load_api_key()
        self.models = [cfg.get("model", "gemini-flash-latest"), *cfg.get("fallback_models", ["gemini-flash-lite-latest"])]
        self.history: list[dict] = []
        self.last_turn = 0.0
        self.http = httpx.Client(timeout=cfg.get("timeout_seconds", 20))
        self.groq = None
        self.answered_by = None  # "gemini" or "groq", for the usage stats
        self.gemini_slow_until = 0.0  # while in the future, Groq is asked first
        if not self.available:
            log.warning("No GEMINI_API_KEY or GROQ_API_KEY in .env: AI features are off, offline commands still work")

    @property
    def available(self) -> bool:
        # Re-read .env when a key is missing, so keys pasted in while Jarvis runs work without a restart.
        if not self.key:
            self.key = load_api_key()
            if self.key:
                log.info("Gemini key found")
        if not self.groq:
            groq_key = load_api_key("GROQ_API_KEY")
            if groq_key:
                self.groq = GroqBackup(groq_key, self.cfg, self.http)
                log.info("Groq backup key found")
        return bool(self.key or self.groq)

    # ---- conversation ------------------------------------------------------------

    def _trim_history(self):
        if time.monotonic() - self.last_turn > self.cfg.get("history_minutes", 5) * 60:
            self.history.clear()
        # Keep the last N user turns; always cut at a plain user text message so tool calls stay paired.
        max_turns = self.cfg.get("history_turns", 10)
        starts = [i for i, c in enumerate(self.history) if c["role"] == "user" and "text" in c["parts"][0]]
        if len(starts) > max_turns:
            self.history = self.history[starts[-max_turns]:]
        # Screenshots are big; keep only the words from older turns.
        for c in self.history:
            c["parts"] = [p for p in c["parts"] if "inlineData" not in p] or [{"text": "(screenshot)"}]

    def remember(self, user_text: str, reply: str):
        """Record exchanges handled by offline rules, so 'close it' still makes sense afterwards."""
        self._trim_history()
        self.history += [{"role": "user", "parts": [{"text": user_text}]},
                         {"role": "model", "parts": [{"text": reply}]}]
        self.last_turn = time.monotonic()

    def _system_prompt(self) -> str:
        try:
            front, windows = desktop.front_window(), desktop.list_open_windows()
        except Exception:
            front = windows = "unknown"
        return SYSTEM_PROMPT.format(
            now=datetime.now().strftime("%A %d %B %Y, %I:%M %p"),
            front=front, windows=windows,
            profiles=self.skills.browser.profile_summary() or "none")

    def _post(self, model: str, body: dict) -> tuple[httpx.Response, str]:
        """POST with a "hedge". The newest Gemini models often hang on requests that normally take ~2s
        (4-6 out of 8 in a test on 26 Sep). If there's no answer after `hedge_after_seconds`, the same
        request also goes to `hedge_model` (an older model that didn't hang), and whichever answers
        first wins. Returns (response, model that answered)."""
        def send(m):
            return self.http.post(f"{API}/models/{m}:generateContent",
                                  headers={"x-goog-api-key": self.key}, json=body), m

        hedge_model = self.cfg.get("hedge_model") or model
        if usage.is_limited(f"gemini:{hedge_model}"):
            hedge_model = model
        hedge_after = self.cfg.get("hedge_after_seconds", 2.5)
        deadline = time.monotonic() + self.cfg.get("timeout_seconds", 8)
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            pending = {pool.submit(send, model)}
            hedged = False
            while pending:
                wait_for = min(deadline, time.monotonic() + hedge_after) if not hedged else deadline
                done, pending = wait(pending, timeout=max(0.0, wait_for - time.monotonic()),
                                     return_when=FIRST_COMPLETED)
                for f in done:
                    if f.exception() is None:
                        return f.result()
                if time.monotonic() >= deadline:
                    break
                if not hedged:
                    hedged = True
                    log.info("Gemini %s is slow; also asking %s", model, hedge_model)
                    pending.add(pool.submit(send, hedge_model))
            raise httpx.ReadTimeout(f"Gemini {model} didn't answer in time")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _generate(self, contents: list[dict]) -> dict:
        body = {
            "system_instruction": {"parts": [{"text": self._system_prompt()}]},
            "contents": contents,
            "tools": [{"functionDeclarations": self.skills.declarations()}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": self.cfg.get("max_output_tokens", 2048)},
        }
        last = None
        # Busy or rate-limited? Try the next model instead of giving up.
        for model in self.models:
            if usage.is_limited(f"gemini:{model}"):
                log.info("Skipping %s: hit its limit less than a minute ago", model)
                continue
            t0 = time.monotonic()
            try:
                r, model = self._post(model, body)  # `model` becomes whichever one answered
            except httpx.TimeoutException:
                log.warning("Gemini %s timed out", model)
                usage.api_call("gemini", model, "timeout", time.monotonic() - t0)
                last = None
                continue  # slow right now; try the next model
            if r.status_code == 200:
                data = r.json()
                meta = data.get("usageMetadata", {})
                usage.api_call("gemini", model, 200, time.monotonic() - t0,
                               meta.get("promptTokenCount", 0), meta.get("candidatesTokenCount", 0))
                if model != self.models[0]:
                    log.info("Answered by fallback model %s", model)
                return data
            usage.api_call("gemini", model, r.status_code, time.monotonic() - t0,
                           limited_for=_limit_seconds(r) if r.status_code == 429 else None)
            last = r
            log.warning("Gemini %s returned %s: %s", model, r.status_code, r.text[:200])
            if r.status_code in (401, 403):
                raise BrainUnavailable("Gemini rejected the API key")
            if r.status_code not in (429, 500, 503, 504):
                break
        if last is None and all(usage.is_limited(f"gemini:{m}") for m in self.models):
            raise BrainUnavailable("Gemini free limit reached for now")
        if last is None or last.status_code in (500, 503, 504):
            raise BrainUnavailable("Gemini is busy")
        if last.status_code == 429:
            raise BrainUnavailable("Gemini free limit reached for now")
        last.raise_for_status()
        raise BrainUnavailable("unexpected Gemini response")

    def ask(self, text: str) -> str:
        if not self.available:
            raise BrainUnavailable("no API key")
        self._trim_history()
        mouse.reset_takeover()
        # A risky action (send, buy, delete…) is only allowed when this message is a "yes" to the
        # question Jarvis just asked. Decided here in code, not left to the AI.
        self.skills.confirmed = _is_yes(text) and self._just_asked()
        self.skills.screen_fresh = False  # time has passed since any earlier screenshot
        try:
            return self._ask_any(text)
        except mouse.UserTookOver:
            log.info("User moved the mouse; stopped")  # the partial turn is already closed in history
            return "You moved the mouse, so I stopped."
        except mouse.Cancelled:
            log.info("User said Hey Jarvis mid-task; stopped")
            return "Stopped."
        finally:
            self.skills.confirmed = False

    def _just_asked(self) -> bool:
        """Did Jarvis's last reply end with a question?"""
        for c in reversed(self.history):
            if c["role"] == "model":
                t = " ".join(p.get("text", "") for p in c.get("parts", []) if not p.get("thought")).strip()
                if t:
                    return t.endswith("?")
        return False

    def _ask_any(self, text: str) -> str:
        # While Gemini is stalling, go to Groq first (~0.7s) instead of waiting on Gemini every time.
        if self.groq and self.key and time.monotonic() < self.gemini_slow_until:
            log.info("Gemini was stalling recently; asking Groq first")
            try:
                reply = self._ask_groq(text)
                self.answered_by = "groq"
                return reply
            except BrainUnavailable as e:
                log.warning("Groq unavailable (%s), trying Gemini", e)
        if self.key:
            try:
                reply = self._ask_gemini(text)
                self.answered_by = "gemini"
                return reply
            except BrainUnavailable as e:
                if not self.groq:
                    raise
                if "busy" in str(e):
                    self.gemini_slow_until = time.monotonic() + self.cfg.get("slow_backoff_seconds", 180)
                    usage.set_activity("Gemini is stalling; using Groq first for a few minutes")
                log.warning("Gemini unavailable (%s), asking Groq", e)
        reply = self._ask_groq(text)
        self.answered_by = "groq"
        return reply

    def model_order(self) -> list[str]:
        """Every model Jarvis may use, in the order it tries them (for the status page / voice summary)."""
        order = [f"gemini:{m}" for m in self.models] if self.key else []
        if self.groq:
            order += [f"groq:{m}" for m in self.groq.models]
        return order

    def _ask_groq(self, text: str) -> str:
        try:
            reply, turn = self.groq.ask(self._system_prompt(), self.history, text, self.skills.declarations(),
                                        self.skills.call, self.cfg.get("max_steps", 6),
                                        finish=lambda names, results, said: fast_reply(text, names, results, said))
        except (httpx.HTTPError, RuntimeError, KeyError) as e:
            log.warning("Groq failed: %s", e)
            raise BrainUnavailable("both AI services failed") from e
        self.history += turn
        self.last_turn = time.monotonic()
        return reply

    def _ask_gemini(self, text: str) -> str:
        turn = [{"role": "user", "parts": [{"text": text}]}]
        t0 = time.monotonic()
        unchecked_click = False  # clicked since the last look at the screen
        verified = False         # the "look before you claim" check runs at most once per request
        asked_again = False      # a garbled final answer gets one retry
        launched = False         # an app or window was opened this request

        try:
            for _ in range(self.cfg.get("max_steps", 6)):
                if self.skills.cancel.is_set():
                    raise mouse.Cancelled()
                data = self._generate(self.history + turn)
                cands = data.get("candidates") or []
                if not cands or "content" not in cands[0]:
                    reason = data.get("promptFeedback", {}).get("blockReason") or (cands[0].get("finishReason") if cands else "empty")
                    log.warning("Gemini returned no content (%s)", reason)
                    return "Sorry, I can't help with that."
                content = cands[0]["content"]
                content.setdefault("role", "model")
                content.setdefault("parts", [])
                turn.append(content)  # keep it verbatim; newer models need their thought signatures back

                calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
                said = _clean(" ".join(p.get("text", "") for p in content["parts"] if not p.get("thought")))
                if not calls:
                    if unchecked_click and not verified:
                        # It clicked and is about to report without looking. Make it check first,
                        # so it can't say "Chemistry 2026 is open" when 2024 opened.
                        verified = True
                        log.info("Checking the screen before Jarvis reports a click result")
                        if launched:
                            time.sleep(1.5)  # an app/window just opened; let it appear before judging
                        shot = self.skills.call("look_at_screen", {})
                        turn.append({"role": "user", "parts": [
                            {"text": "Before replying, check this screenshot of the result. Say only what it "
                                     "actually shows, using the exact title, or say plainly that it didn't work."},
                            {"inlineData": {"mimeType": "image/jpeg",
                                            "data": base64.b64encode(shot["image_jpeg"]).decode()}}]})
                        continue
                    if not speakable(said) and not said.lower().rstrip(".!") in ("done", "ok", "okay", "stopped"):
                        if not asked_again:
                            # Garbled or empty final answer ("hob", "thought"): ask once for a real one.
                            asked_again = True
                            log.warning("Unusable reply %r; asking the AI again", said[:40])
                            turn.append({"role": "user", "parts": [{"text":
                                "Your last reply was empty or garbled. Either carry on with the task using the "
                                "tools, or tell the user in one clear English sentence what happened."}]})
                            continue
                        return "Sorry, I lost track of that. Could you say it again?"
                    log.info("Gemini answered in %.1fs", time.monotonic() - t0)
                    return said
                for c in calls:
                    # Clicking and typing both need checking: "name it Jarvis" was typed into the
                    # search bar and reported as done.
                    if c["name"] in ("click", "type_text", "press_key") or (
                            c["name"] == "web_search" and _QUESTION.search(text)):
                        unchecked_click = True
                    elif c["name"] == "look_at_screen":
                        unchecked_click = False
                    if c["name"] in _LAUNCHING_TOOLS:
                        launched = True

                parts, images, results = [], [], []
                for call in calls:
                    result = self.skills.call(call["name"], call.get("args", {}))
                    if isinstance(result, dict):  # tool returned a screenshot
                        images.append(result["image_jpeg"])
                        result = result["text"]
                    results.append(result)
                    parts.append({"functionResponse": {"name": call["name"], "response": {"result": result}}})
                for jpeg in images:
                    parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}})
                turn.append({"role": "user", "parts": parts})

                # Fast finish: the actions worked and they complete the request, so speak now instead of
                # paying for another round trip just to hear "Done".
                quick = None if images else fast_reply(text, [c["name"] for c in calls], results, said)
                if quick:
                    turn.append({"role": "model", "parts": [{"text": quick}]})
                    log.info("Gemini answered in %.1fs (fast finish)", time.monotonic() - t0)
                    return quick
            return "That took too many steps, so I stopped."
        except httpx.HTTPError as e:
            log.warning("Gemini request failed: %s", e)
            raise BrainUnavailable(str(e)) from e
        finally:
            if len(turn) > 1:
                if turn[-1]["role"] == "user":  # cut off mid tool-loop; close the turn so history stays valid
                    turn.append({"role": "model", "parts": [{"text": "(stopped)"}]})
                self.history += turn
                self.last_turn = time.monotonic()
