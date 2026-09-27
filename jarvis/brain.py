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

from . import abilities, router
from .config import ROOT
from .groq_backup import GroqBackup, NeedsVision
from .skills import Skills, action_budget, desktop, elements, mouse, request_parts, shortcuts
from .skills import volume
from .usage import usage

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta"

# The system prompt is built from sections: each request carries only the rules its kind of job needs
# (router.py decides the kind). Every word is paid for in tokens on every request, so keep them short.
_CORE = """You are Jarvis, a voice assistant on the user's Windows PC. Replies are read aloud: one or two \
short spoken sentences, no markdown/lists/URLs. The words come from speech recognition; assume the most sensible \
meaning. If a request doesn't make sense (just numbers, a garbled phrase), ask what they meant; don't act.
Answer general knowledge from what you know. Recent or changing facts (news, scores, prices, "latest", "this \
year"): web_search, then read the answer on screen; never from memory.
Do only what was asked, nothing extra, then say briefly what happened ("Opened YouTube"). Never claim success \
you haven't seen. Don't read out page titles unless asked.
Ask one short yes/no question first before anything that sends, posts, buys, pays, subscribes, signs in, submits \
a form, deletes or changes account settings. Never type passwords or card numbers. Never read out codes, \
passwords, card or account numbers seen on screen; say one is shown, without the digits.
If your tool calls finish the request, put your short reply in the same response. If a tool you need is \
missing, call more_tools."""

_APPS = """- "Open YouTube" = the website (open_website, full URL) unless they say "app". "Search X on YouTube" = \
web_search with that site; if that site is in front, site_search. "Here", "this tab", "address bar" = the current \
tab (address_bar / browser / site_search), not a new window.
- "Close this" right after you opened a window = that window. Close a tab only if they say tab: "close the chess \
tab" = close_tab_named; "close this tab" = browser close_tab. "Close all of them" = window close_all.
- Minimize/maximize/restore/close a window = the window tool, never clicking its title-bar buttons.
- "It", "that" = what you did last or the front window; if unclear, ask. Searching, and opening, closing or \
switching apps, windows and tabs, need no confirmation: just do them."""

_SCREEN = """- To click a named item (button, link, field): click_element with its id from the on-screen list (one \
may be given; else page_elements). Only for things with no name (pictures, boards, games) use the screenshot \
(one may be attached, else look_at_screen) and click the centre, x,y 0-1000. Two clicks from one look (chess: piece then square; drag) = one click_pair. Skip the browser's \
tab/toolbar strip (top ~10%) unless asked. "The second video" = count results top to bottom, skipping ads/Shorts.
- If a click didn't work, don't click the same spot again: aim elsewhere, use the keyboard, or ask.
- Look again only if the next step needs the new screen, or to confirm before reporting. To find text on a long \
page use find_on_page."""

_FILES = """- Files: paths like 'Desktop/Trips' or 'Downloads/cv.pdf' work directly; use find_files only to locate \
something by name, then open_path / show_in_explorer. Deleting is turned off: never try."""

_PROFILES = """- "Third profile" = number 3 in the profile list. If a profile request fits none or several, ask.
Chrome profiles (pass the folder as `profile`): {profiles}"""


_GROUP_HINTS = {
    "apps": "open apps/sites, windows, tabs, web search, volume, media keys, timers",
    "system": "volume, media keys (play/pause/next), timers",
    "keys": "type text, press keys and shortcuts",
    "screen": "look at the screen, click, drag, scroll",
    "files": "find, open, copy, move, rename, read or write files and folders",
}


def build_prompt(kind: str, request: str, now: str, sound: str = "", front: str = "", windows: str = "",
                 profiles: str = "") -> str:
    """The system prompt for one request: core rules plus only the sections its kind needs."""
    parts = [_CORE]
    if kind in ("action", "screen", "files"):
        parts.append(_APPS)
    if kind in ("screen", "live"):
        parts.append(_SCREEN)
    if kind == "files":
        parts.append(_FILES)
    if kind in ("action", "screen") and router.wants_profiles(request):
        parts.append(_PROFILES.format(profiles=profiles or "none"))
    parts.append(f"Time: {now}{sound}")
    if kind != "chat":
        parts.append(f"Front window: {front}")
    if kind in ("action", "screen"):
        parts.append(f"Open windows: {windows}")
        # Shortcut first: a key press is instant and exact; the mouse is the last resort.
        parts.append("Prefer a shortcut (press_key) over the mouse whenever one exists.\n"
                     + shortcuts.for_window(front, request))
    return "\n".join(parts)


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
    "close_tab_named", "click_element",
    "media", "volume", "timer", "open_path",
    "show_in_explorer", "create_folder", "copy_file", "move_file", "rename_file", "write_text_file",
}
_MULTI_STEP = re.compile(r"\b(and|then|after that|also|once)\b|,")
_LAUNCHING_TOOLS = {"open_app", "open_website", "open_chrome", "open_path", "web_search", "show_in_explorer"}
_PLAY = re.compile(r"\b(play|listen to|put on|watch)\b", re.I)
_CLICKS = {"click", "click_pair", "type_text", "press_key"}
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


# A leaked "thinking" label at the start of the reply: "thought", "atthought" (26 Sep), "Thought:".
_THOUGHT_LABEL = re.compile(r"^\s*[a-z]{0,12}thought\s*(?:[:\-]\s*|\n\s*|$)", re.I)


def _clean(text: str) -> str:
    text = _THOUGHT_LABEL.sub("", text)
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


def tool_declarations(skills, kind: str, extra_groups: set[str], request: str) -> list[dict]:
    """Only the tools this kind of request needs, plus more_tools to ask for the rest."""
    decls = list(skills.declarations(router.tool_names(kind, extra_groups, request)))
    missing = router.missing_groups(kind, extra_groups, request)
    if missing:
        decls.append({"name": "more_tools",
                      "description": "Get tools this request needs but you don't have: "
                                     + "; ".join(f"{g} = {_GROUP_HINTS[g]}" for g in missing) + ".",
                      "parameters": {"type": "OBJECT", "required": ["group"],
                                     "properties": {"group": {"type": "STRING", "enum": missing}}}})
    return decls


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
        self.on_backup = False        # announced that the backup AI is answering
        self.kind = "action"          # router.classify() of the current request
        self.request = ""             # the current request's words
        self.extra_groups: set[str] = set()  # tool groups the AI asked for with more_tools
        self.turn_calls: list[tuple] = []     # (tool, args, result) this request, for phrase memory
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

    def _system_prompt(self, text: str = "") -> str:
        front = windows = ""
        if self.kind != "chat":
            try:
                front = desktop.front_window()
                windows = desktop.list_open_windows() if self.kind in ("action", "screen") else ""
            except Exception:
                front = windows = "unknown"
        wants_profiles = self.kind in ("action", "screen") and router.wants_profiles(text)
        muted = self.kind in ("action", "screen") and volume.others_muted()
        return build_prompt(
            self.kind, text, now=datetime.now().strftime("%A %d %B %Y, %I:%M %p"),
            sound="\nSound: other apps are MUTED (volume unmute to hear them)" if muted else "",
            front=front, windows=windows,
            profiles=(self.skills.browser.profile_summary() or "none") if wants_profiles else "")

    # ---- tools for this request --------------------------------------------------

    def _declarations(self) -> list[dict]:
        return tool_declarations(self.skills, self.kind, self.extra_groups, self.request)

    def _call(self, name: str, args: dict):
        if name == "more_tools":
            group = str((args or {}).get("group", ""))
            if group not in router.GROUPS:
                return f"Unknown group. Choose one of: {', '.join(router.GROUPS)}."
            self.extra_groups.add(group)
            log.info("AI asked for the %s tools", group)
            return f"Added the {group} tools. Use them now."
        result = self.skills.call(name, args)
        self.turn_calls.append((name, args or {}, result))
        return result

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
            "system_instruction": {"parts": [{"text": self._system_prompt(self.request)}]},
            "contents": contents,
            "tools": [{"functionDeclarations": self._declarations()}],
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

    def ask(self, text: str, unsure: bool = False) -> str:
        if not self.available:
            raise BrainUnavailable("no API key")
        if _PLAY.search(text) and volume.others_muted():
            # 26 Sep: "play Aari Aari" played silently because of a "mute" from an hour before.
            log.info("Unmuting: they asked to play something while other apps were muted")
            volume.mute(False)
        # Hands-on actions (clicks, typing…) are capped at what was asked; enforced in Skills.call.
        self.skills.budget = action_budget(text, self.cfg.get("open_ended_actions", 3))
        self.skills.launches = max(1, len(request_parts(text)))
        self.kind, self.request, self.extra_groups = router.classify(text), text, set()
        log.info("Request kind: %s", self.kind)
        if unsure:
            text += "\n(Speech recognition was unsure of these words. If they don't clearly make sense, ask.)"
        self._trim_history()
        mouse.reset_takeover()
        # A risky action (send, buy, delete…) is only allowed when this message is a "yes" to the
        # question Jarvis just asked. Decided here in code, not left to the AI.
        self.skills.confirmed = _is_yes(text) and self._just_asked()
        self.skills.screen_fresh = False  # time has passed since any earlier screenshot
        self.screen_items = ""  # the on-screen items as text, when that's enough (no screenshot needed)
        if self.kind == "screen" and not router.needs_eyes(text):
            items = self._call("page_elements", {})
            if isinstance(items, str) and items.startswith("[1]"):
                self.screen_items = items
        elif self.kind == "action" and router.thing_named(text) and elements.front_is_browser():
            # "Open chemistry" on the PW page means the Chemistry link on screen, not an app. One quick
            # read (~0.05 s) tells which.
            items = self._call("page_elements", {})
            if isinstance(items, str) and items.startswith("[1]") and elements.mentions(router.thing_named(text)):
                self.kind, self.screen_items = "screen", items
                log.info("%r is on screen: handling it as a screen request", router.thing_named(text))
        try:
            self.turn_calls = []  # the up-front screen read above doesn't count
            reply = self._ask_any(text)
            self._learn(text, unsure)
            return reply
        except mouse.UserTookOver:
            log.info("User moved the mouse; stopped")  # the partial turn is already closed in history
            return "You moved the mouse, so I stopped."
        except mouse.Cancelled:
            log.info("User said Hey Jarvis mid-task; stopped")
            return "Stopped."
        finally:
            self.skills.confirmed = False
            self.skills.budget = None
            self.skills.launches = None

    def _learn(self, text: str, unsure: bool):
        """If the AI did this request with exactly one built-in ability, remember the phrasing so it's
        instant (and free) next time. Only when speech recognition was sure."""
        if unsure or len(self.turn_calls) != 1:
            return
        name, args, result = self.turn_calls[0]
        ok = isinstance(result, str) and not _looks_failed(result) and not result.startswith(("Not done", "Unknown"))
        if name == "do" and ok:
            abilities.memory.learn(text, str(args.get("ability", "")), args.get("value"))

    def _just_asked(self) -> bool:
        """Did Jarvis's last reply end with a question?"""
        for c in reversed(self.history):
            if c["role"] == "model":
                t = " ".join(p.get("text", "") for p in c.get("parts", []) if not p.get("thought")).strip()
                if t:
                    return t.endswith("?")
        return False

    def _chain(self) -> list[str]:
        """Which AI to ask, in order. Groq (~1 s) for commands and questions; Gemini (can see) first for
        anything about the screen or needing live facts read off a results page, and as the fallback."""
        needs_gemini = self.kind == "live" or (self.kind == "screen" and not self.screen_items)
        default = ["gemini", "groq"] if needs_gemini else ["groq", "gemini"]
        order = list(self.cfg.get("routing", {}).get(self.kind, default))
        if "groq" in order and time.monotonic() < self.gemini_slow_until:
            order.remove("groq")
            order.insert(0, "groq")  # Gemini is stalling: don't wait on it every time
        return [p for p in order if (p == "gemini" and self.key) or (p == "groq" and self.groq)]

    def _ask_any(self, text: str) -> str:
        chain = self._chain()
        if not chain:
            raise BrainUnavailable("no API key")
        handoff, last = None, None
        for i, provider in enumerate(chain):
            try:
                if provider == "groq":
                    reply = self._ask_groq(text)
                else:
                    reply = self._ask_gemini(text, handoff)
                self.answered_by = provider
                if last is not None and not self.on_backup:
                    # The user wants to know when Jarvis leans on the backup (27 Sep). Said once per switch.
                    self.on_backup = True
                    usage.set_activity(f"Main AI unavailable; using {provider} as the backup")
                    return f"The main AI is busy, so I'm using the backup. {reply}"
                if last is None and i == 0:
                    self.on_backup = False
                return reply
            except NeedsVision as e:
                # Groq can't see. Hand the request, and what it already did, to Gemini.
                if "gemini" not in chain[i + 1:]:
                    log.warning("Groq needs to see the screen and Gemini isn't available")
                    self.answered_by = "groq"
                    return "I'd need to see the screen for that, and the AI that can see isn't available right now."
                log.info("Groq needs to see the screen; handing over to Gemini (done so far: %s)", e.done)
                handoff = e
            except BrainUnavailable as e:
                last = e
                if provider == "gemini" and "busy" in str(e) and self.groq:
                    self.gemini_slow_until = time.monotonic() + self.cfg.get("slow_backoff_seconds", 180)
                    usage.set_activity("Gemini is stalling; using Groq first for a few minutes")
                if i + 1 < len(chain):
                    log.warning("%s unavailable (%s), asking %s", provider, e, chain[i + 1])
        raise last or BrainUnavailable("no AI available")

    def model_order(self) -> list[str]:
        """Every model Jarvis may use, in the order it tries them (for the status page / voice summary)."""
        order = [f"gemini:{m}" for m in self.models] if self.key else []
        if self.groq:
            order += [f"groq:{m}" for m in self.groq.models]
        return order

    def _items_note(self) -> str:
        if not self.screen_items:
            return ""
        return f"(Items on screen now, for click_element: {self.screen_items})"

    def _ask_groq(self, text: str) -> str:
        self.skills.screen_fresh = False  # a screenshot attached for Gemini wasn't seen by Groq
        try:
            reply, turn = self.groq.ask(self._system_prompt(text), self.history, text, self._declarations,
                                        self._call, self.cfg.get("max_steps", 6), context=self._items_note(),
                                        finish=lambda names, results, said: fast_reply(text, names, results, said))
        except (httpx.HTTPError, RuntimeError, KeyError) as e:
            log.warning("Groq failed: %s", e)
            raise BrainUnavailable("both AI services failed") from e
        self.history += turn
        self.last_turn = time.monotonic()
        return reply

    def _ask_gemini(self, text: str, handoff: "NeedsVision | None" = None) -> str:
        turn = [{"role": "user", "parts": [{"text": text}]}]
        t0 = time.monotonic()
        if handoff:
            # Carrying on from Groq, which did some steps and then needed to see the screen.
            done = "; ".join(handoff.done) or "nothing yet"
            turn[0]["parts"] += [{"text": f"(Already done for this request: {done}. The screen now is attached; "
                                          "positions are x,y from 0 to 1000. Don't repeat those steps.)"},
                                 {"inlineData": {"mimeType": "image/jpeg",
                                                 "data": base64.b64encode(handoff.image).decode()}}]
        elif self.screen_items:
            turn[0]["parts"].append({"text": self._items_note()})
        elif self.kind == "screen":
            # Chess on 26 Sep: every move was look, think, click, look, think, click (13-32 s). Sending the
            # screen up front lets the AI act in its first answer.
            try:
                shot = self.skills.snapshot()
                turn[0]["parts"] += [{"text": "(The current screen is attached; positions are x,y from 0 to 1000.)"},
                                     {"inlineData": {"mimeType": "image/jpeg",
                                                     "data": base64.b64encode(shot).decode()}}]
            except PermissionError as e:
                turn[0]["parts"].append({"text": f"(No screenshot: {e})"})
        unchecked_click = False  # clicked since the last look at the screen
        checks = 0               # "look before you claim" checks so far (capped, each costs a round trip)
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
                    if unchecked_click and checks < 2:
                        # It clicked and is about to report without looking. Make it check first,
                        # so it can't say "Chemistry 2026 is open" when 2024 opened. Checked after the
                        # *last* click: chess moves were claimed from a check made after the first click.
                        checks += 1
                        unchecked_click = False
                        log.info("Checking the screen before Jarvis reports a click result")
                        if launched:
                            time.sleep(1.5)  # an app/window just opened; let it appear before judging
                        shot = self._call("look_at_screen", {})
                        turn.append({"role": "user", "parts": [
                            {"text": "This is the screen now. Did it work? Report the result. Do nothing that "
                                     "wasn't asked. Tell the user the outcome in one short sentence, e.g. 'Done, the "
                                     "pawn is on f4.' or 'That didn't work, nothing changed.' Don't read out titles."},
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
                    if c["name"] in _CLICKS or (
                            c["name"] == "web_search" and _QUESTION.search(text)):
                        unchecked_click = True
                    elif c["name"] == "look_at_screen":
                        unchecked_click = False
                    if c["name"] in _LAUNCHING_TOOLS:
                        launched = True

                parts, images, results = [], [], []
                for call in calls:
                    result = self._call(call["name"], call.get("args", {}))
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
                # Remember the turn as plain words: what was asked and what Jarvis said. The tool calls,
                # results and screenshots were resent with every later request (tokens) and aren't needed.
                said = "" if turn[-1]["role"] == "user" else _clean(
                    " ".join(p.get("text", "") for p in turn[-1]["parts"] if not p.get("thought")))
                self.history += [{"role": "user", "parts": [{"text": text}]},
                                 {"role": "model", "parts": [{"text": said or "(stopped)"}]}]
                self.last_turn = time.monotonic()
