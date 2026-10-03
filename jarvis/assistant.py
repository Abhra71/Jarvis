"""The main loop: IDLE (wake word) -> LISTENING -> THINKING -> SPEAKING -> IDLE."""

import logging
import queue
import re
import threading
import time
import webbrowser
from enum import Enum
from typing import Callable

from . import nlu
from .audio import Mic, record_utterance
from .skills import volume
from .brain import Brain, BrainUnavailable
from . import abilities
from . import codemode
from .skills import Skills, desktop, editors, elements, keys, request_parts, site_url, sites
from .stt import Transcriber
from .tts import Speaker
from . import addressed, corrections, tasklog
from .usage import usage
from .wakeword import WakeWordDetector

log = logging.getLogger(__name__)

# Dictation (30 Sep): after "start dictation", everything said is typed where the cursor is, until "stop".
_DICTATE_ON = re.compile(r"(start|begin|turn on) (dictation|dictating|typing)( mode)?|dictation mode|take (a )?dictation|"
                         r"(start )?type (what|whatever) i (say|speak)")
_DICTATE_OFF = re.compile(r"(stop|end|finish|turn off|exit|quit) (dictation|dictating|typing)( mode)?|dictation off|"
                          r"stop|that'?s (it|all)|done|i'?m done")
_NEW_LINE = re.compile(r"(new|next) (line|paragraph)")
_SCRATCH = re.compile(r"(scratch|delete|undo|remove|erase) (that|it|the last (bit|part|sentence))")
DICTATION_SILENCE = 30  # seconds of quiet that end dictation

# Coding mode: with BlueJ or VS Code in front, speech becomes code (jarvis/codemode.py); commands still work.
_CODING_ON = re.compile(r"(start |enter |turn on |switch to )?(coding|code) mode( on)?|start coding|let'?s code")
# Gaming mode (30 Sep): no follow-up listening after a reply, so game sounds can't be taken for commands.
_GAMING_ON = re.compile(r"(start |enter |turn on |switch to )?(gaming|game) mode( on)?|let'?s play")
_GAMING_OFF = re.compile(r"(stop|end|exit|leave|turn off|quit) (gaming|game) mode|(gaming|game) mode off")
_CODING_OFF = re.compile(r"(stop|end|exit|leave|turn off|quit) (coding|code)( mode)?|(coding|code) mode off|"
                         r"stop coding")

_CLOSE_IT = re.compile(r"(?:(?:ok(?:ay)?|now|and|then|please),? )*(?:close|shut) (?:it|that|this|this one|that one|"
                       r"this window|that window|this folder|that folder|the folder)(?: now)?(?: please)?")
_PLAY = re.compile(r"\b(play|listen to|put on|watch|resume)\b", re.I)
_YES_WORD = re.compile(r"\s*(yes|yeah|yep|yup|sure|ok|okay|right|correct|exactly|haan|ha)\b", re.I)
_STOP = re.compile(r"(stop|cancel|never ?mind|forget it|leave it|that'?s all|nothing|no|nope|nah|no thanks|"
                   r"don'?t|do not)( it| that| send it| do it)?"
                   r"(,? (stop|cancel|nothing))*( please)?( jarvis)?")

# Words that make an "open …" / "search …" request too rich for the offline rules.
_SEARCH_CONTEXT = re.compile(r"\b(it|this|that|these|those|here|there|address bar|search (?:box|bar)|earlier|same|again|"
                             r"above|below|on (?:the |my )?screen|selected|copied|clipboard)\b")
_NEEDS_AI = re.compile(r"\b(profile|account|tabs?|window|and|then|close|in my|on my|on youtube|on amazon)\b")

_SECRET_CONTEXT = re.compile(r"\b(code|otp|one[- ]time|password|passcode|pin|verification|cvv|card|account number)\b", re.I)
_DIGITS = re.compile(r"\b\d[\d -]{2,}\d\b")


def redact_secrets(reply: str) -> str:
    """Never say codes/passwords out loud. On 26 Sep Jarvis read a GitHub verification code from Gmail;
    enforced here in code, not only by asking the AI."""
    if _SECRET_CONTEXT.search(reply) and _DIGITS.search(reply):
        return _DIGITS.sub("(hidden)", reply)
    return reply


# Things Whisper tends to "hear" in silence or background noise.
_NOT_DONE = re.compile(r"^Not done:\s*")

_HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "bye", "okay", "hmm"}


class State(Enum):
    LOADING = "Loading..."
    IDLE = "Waiting for 'Hi Jarvis'"
    LISTENING = "Listening"
    THINKING = "Thinking"
    LOOKING = "Looking at your screen"
    ACTING = "Using the mouse"
    SPEAKING = "Speaking"
    PAUSED = "Paused"
    ERROR = "Error - see logs"


class Assistant:
    def __init__(self, config: dict, on_state: Callable[[State], None] = lambda s: None):
        self.config = config
        self.on_state = on_state
        self.state = State.LOADING
        self.paused = threading.Event()
        self.stopping = threading.Event()

        self.speaker = Speaker(config["tts"])
        self.skills = Skills(config, announce=self.speaker.say)
        self.brain = Brain(config.get("ai", {}), self.skills)
        self.skills.on_tool = self._on_tool
        if self.brain.agent:
            self.brain.agent.narrate = self.speaker.say_async  # short updates while a plan runs
        self.dashboard_url = None
        self.stt = None
        self.wake = None
        self.dictating = False
        self.coding = False  # coding mode: speech -> code in BlueJ / VS Code
        self.gaming = False  # gaming mode: "Hi Jarvis" for every command (game sounds aren't commands)
        self.heard: dict | None = None  # how the current sentence was heard (for the task log)
        self.corrections = corrections.Corrections()  # "No, I meant Claude": fixed now, and remembered
        self.last_request = ""  # the last request handled (what a correction corrects)
        self.fixed_request: str | None = None
        self.codemode = codemode.CodeMode(think=self._think)
        self.dictated = ""  # the last piece typed, for "scratch that"
        self.mic = None

    def _set(self, state: State):
        self.state = state
        log.debug("state -> %s", state.name)
        usage.set_activity("idle" if state == State.IDLE else state.value.lower())
        self.on_state(state)

    # ---- understanding -----------------------------------------------------

    def _rules_can_handle(self, intent: nlu.Intent, text: str) -> bool:
        """Simple, clear commands run instantly offline; anything fancier goes to Gemini."""
        if intent.name == "web_search":
            # "search it here", "…in the address bar": the AI handles context far better. A plain search ("search
            # python tutorials on youtube") is an address: instant (3 Oct speed pass; it took 2-3 s via the AI).
            return not _SEARCH_CONTEXT.search(intent.slots["query"]) and len(intent.slots["query"].split()) <= 12 \
                and len(request_parts(text)) == 1
        if len(request_parts(text)) > 1:
            # 30 Sep: "open YouTube in Brave's browser, mute in Chrome" only muted. Several parts: the agent.
            return False
        if intent.name == "shortcut":
            # Only real keys, and nothing that needs a yes (Enter in a chat sends it): the AI asks those.
            try:
                refusal, needs_yes = keys.check(intent.slots["keys"], desktop.front_window())
            except keys.BadKeys:
                return False
            return not (refusal or needs_yes)
        if intent.name == "open_profile":
            return self.skills.browser.find(intent.slots["profile"]) is not None
        if intent.name == "open_app" and _NEEDS_AI.search(text.lower()):
            return False
        if intent.name == "open_app":
            app = intent.slots["app"]
            return site_url(app) is not None or self.skills.apps.find_exact(app) is not None
        return True

    def handle_text(self, text: str, unsure: bool = False) -> str:
        """Text in, spoken reply out. Used by both voice mode and --text mode.
        `unsure`: speech recognition wasn't confident, so the AI is told to ask rather than guess."""
        usage.begin_turn(text)
        turn = tasklog.Turn(text, getattr(self, "heard", None))
        self.heard = None
        agent = getattr(self.brain, "agent", None)
        last_before = getattr(agent, "last", None)
        from .skills import mouse
        mouse.reset_takeover()  # every request starts fresh (30 Sep: a stale "you moved the mouse" crashed a turn)
        corr = getattr(self, "corrections", None)
        if corr:
            text = corr.apply(text)  # mishearings the user corrected before ("Clawed" -> "Claude")
        opened_before = desktop.just_opened
        try:
            route, reply = self._handle(text, unsure)
        except mouse.UserTookOver:
            route, reply = "stopped", "You moved the mouse, so I stopped."
        except mouse.Cancelled:
            route, reply = "stopped", "Stopped."
        if desktop.just_opened is opened_before:
            desktop.just_opened = None  # "close it" means what was opened by the request just before, only
        reply = redact_secrets(reply)
        usage.end_turn(route, reply)
        log.info("Handled by %s", route)
        last_after = getattr(agent, "last", None)
        asked = re.match(r"I couldn't find (.+?)\. Did you mean (.+?)\?$", getattr(self, "last_reply", "") or "")
        if asked and corr and _YES_WORD.match(text) and route == "agent" \
                and tasklog.classify(route, reply) not in ("failed", "stuck"):
            corr.learn(asked.group(1), asked.group(2))  # "Did you mean Claude?" "Yes." -> Clawed is Claude from now on
        if route not in ("dictation",):
            self.last_request = getattr(self, "fixed_request", None) or text
            self.last_reply = reply
        self.fixed_request = None
        try:
            turn.finish(route, reply, last_after if last_after is not last_before else None)
        except Exception:
            log.warning("Couldn't log the task", exc_info=True)
        return reply

    def _handle(self, text: str, unsure: bool = False) -> tuple[str, str]:
        """Returns (who handled it, reply)."""
        spoken = " ".join(text.lower().strip(" .!?,").split())
        if self.dictating:
            return "dictation", self._dictate(text, spoken)
        corr = getattr(self, "corrections", None)
        if corr and corrections.is_forget(text):
            forgot = corr.forget_last()
            agent = getattr(self.brain, "agent", None)
            if agent and self.last_request:
                agent.memory.forget(self.last_request)  # a plan remembered from it isn't trusted either
            return "offline rules", f"Okay, I've forgotten that {forgot}." if forgot else "Okay."
        fixed = corr.fix(getattr(self, "last_request", ""), text) if corr else None
        if fixed:
            # "No, I meant Claude." after "Open Clawed.": do "Open Claude." and remember the mishearing.
            request, wrong = fixed
            right = corrections.meant(text)
            log.info("Correction: %r -> %r", self.last_request, request)
            self.fixed_request = request
            route, reply = self._handle(request, unsure=False)
            if tasklog.classify(route, reply) not in ("failed", "stuck"):
                corr.learn(wrong, right)
            return route, reply
        if _GAMING_ON.fullmatch(spoken):
            self.gaming = True
            return "gaming", ("Gaming mode on. Say Hi Jarvis before each command. Start eFootball, close the game, "
                              "maximize or minimize work as usual.")
        if _GAMING_OFF.fullmatch(spoken):
            self.gaming = False
            return "gaming", "Gaming mode off."
        if _CODING_ON.fullmatch(spoken):
            self.coding = True
            log.info("Coding mode on")
            return "coding", "Coding mode on. Java in BlueJ, C++ in VS Code. Say coding mode off when you're done."
        if _CODING_OFF.fullmatch(spoken):
            self.coding = False
            log.info("Coding mode off")
            return "coding", "Coding mode off."
        ed = editors.current() if self.coding else None
        if ed:
            # Coding mode (Block 2, 3 Oct): its fixed command set and code, checked before it's written
            # (jarvis/codemode.py). None: not a coding command (compile, run, open Chrome…): handled below.
            reply = self.codemode.handle(text, ed, unsure)
            if reply is not None:
                return "coding", reply
        if _DICTATE_ON.fullmatch(spoken):
            kind = elements.focused_kind()
            if kind not in ("field", "document", "dropdown"):
                return "dictation", ("Put the cursor in a text box first, for example say 'click the search box', "
                                     "then say start dictation.")
            self.dictating, self.dictated = True, ""
            log.info("Dictation on")
            return "dictation", "Dictation on. Say stop dictation when you're done."
        # The answer to the agent's own question comes first ("close" means the pop-up, not the window).
        answer = getattr(self.brain, "answer_agent", None)
        reply = answer(text) if callable(answer) else None
        if isinstance(reply, str):
            return "agent", reply
        if _STOP.fullmatch(" ".join(text.lower().strip(" .!?").split())):
            # 30 Sep: "Stop." went to the AI and came back as a question. Stopping needs no thinking.
            agent = getattr(self.brain, "agent", None)
            if agent:
                agent.drop_pending()
                agent.question = None
            # 30 Sep: a bare "no" after a question was planned as a new request (it asked about Send again).
            return "offline rules", "Okay." if re.match(r"(no|nope|nah|don)", text.lower().strip()) else "Okay, stopped."
        if _CLOSE_IT.fullmatch(spoken) and desktop.just_opened:
            # "Open downloads." "Close it.": the window just opened, in code (3 Oct: the AI closed a Chrome tab).
            closed = desktop.close_just_opened()
            if closed:
                return "offline rules", closed
        if _PLAY.search(text) and volume.others_muted():
            # Asked to play something while apps are muted (by an earlier "mute", maybe days ago): unmute first,
            # on every path (the site packs play YouTube without reaching the AI's check).
            log.info("Unmuting: they asked to play something while other apps were muted")
            volume.mute(False)
        # The main sites first: common actions there are done in code, instantly, with no AI.
        site = sites.handle(text, self.skills.browser, unsure)
        if site:
            self.brain.remember(text, site[1])
            return site
        # Built-in abilities and phrases learned earlier: instant, no AI.
        reply = abilities.handle(text, unsure)
        if reply and (not reply.startswith(("Not done", "Unknown ability")) or abilities.last_hit in abilities.FINAL):
            self.brain.remember(text, reply)
            return "ability", reply

        intent = nlu.parse(text)
        log.info("Rules: %s", intent)

        if intent and intent.name == "ai_status":
            return "offline rules", usage.spoken_summary(self.brain.model_order())
        if intent and intent.name == "open_dashboard":
            return "offline rules", self.open_dashboard()

        if intent and (self._rules_can_handle(intent, text) or not self.brain.available):
            reply = self.skills.run(intent)
            self.brain.remember(text, reply)
            return "offline rules", reply

        calls_before = self.skills.calls_made
        try:
            reply = self.brain.ask(text, unsure=unsure)
            return self.brain.answered_by or "gemini", reply
        except BrainUnavailable as e:
            if self.skills.calls_made != calls_before:
                # The AI already started doing things; guessing the rest offline would do the wrong thing.
                log.warning("AI dropped out mid-task: %s", e)
                return "failed", "I lost the AI connection partway through, so I stopped. Please try again in a moment."
            fallback = self._offline_fallback(intent, e)
            return ("offline rules" if intent else "failed"), fallback
        except Exception:
            log.exception("AI turn failed")
            return "failed", "Sorry, something went wrong with that."

    def _dictate(self, text: str, spoken: str) -> str:
        """One piece of dictation: typed as said (never Enter: in a chat that would send it). Replies are
        empty, so Jarvis stays quiet while you dictate."""
        if _DICTATE_OFF.fullmatch(spoken):
            self.dictating = False
            log.info("Dictation off")
            return "Dictation off."
        if _NEW_LINE.fullmatch(spoken):
            self.skills.call("press_key", {"key": "shift+enter"})  # a new line, not "send"
            self.dictated = ""
            return ""
        if _SCRATCH.fullmatch(spoken):
            if self.dictated:
                left = len(self.dictated)
                while left > 0:  # a key repeats at most 30 times per press
                    self.skills.call("press_key", {"key": "backspace", "times": min(30, left)})
                    left -= 30
                self.dictated = ""
                return ""
            return "Nothing to scratch."
        piece = text.strip() + " "
        result = self.skills.call("type_text", {"text": piece})
        result = result.get("text", "") if isinstance(result, dict) else str(result)
        if not result.startswith("Typed"):
            self.dictating = False
            return f"I stopped dictation: {result}"
        self.dictated = piece
        return ""

    def _think(self, system: str, user: str) -> str:
        """The AI for coding mode's bigger pieces ("write a method that…")."""
        if not getattr(self.brain, "available", False):
            raise RuntimeError("the AI isn't available")
        return self.brain._think(system, user)

    def open_dashboard(self) -> str:
        if not self.dashboard_url:
            return "The status page isn't running."
        webbrowser.open(self.dashboard_url)
        return "Here's the AI status page."

    def _on_tool(self, name: str):
        if name == "look_at_screen":
            self._set(State.LOOKING)
        elif name in ("click", "click_pair", "scroll", "hover"):
            self._set(State.ACTING)
        elif self.state in (State.LOOKING, State.ACTING):
            self._set(State.THINKING)

    def _offline_fallback(self, intent: nlu.Intent | None, e: Exception) -> str:
        log.warning("AI unavailable: %s", e)
        if intent:
            return self.skills.run(intent)
        if not self.brain.available:
            return "I need a Gemini key for that. Put it in the dot env file in my folder."
        reason = str(e)
        if "both" in reason:
            return "The main AI and the backup are both used up for now. Everyday commands still work without them."
        if "limit" in reason:
            return "I've hit the free AI limit for now. Simple commands still work."
        if "key" in reason:
            return "Gemini didn't accept the API key. Please check the dot env file."
        if "busy" in reason:
            return "Gemini is busy right now. Try again in a moment."
        return "I can't reach Gemini. Check the internet. Simple commands still work."

    # ---- voice mode ---------------------------------------------------------

    def load_voice(self):
        self._set(State.LOADING)
        self.speaker.prepare()
        self.stt = Transcriber(self.config["stt"],
                               vocabulary=self.corrections.words() + self.skills.apps.names_for_speech())
        self.wake = WakeWordDetector(self.config["wakeword"])
        self.mic = Mic(self.config["audio"]["sample_rate"], self.config["audio"]["input_device"])

    def start_dashboard(self):
        from . import dashboard
        self.dashboard_url = dashboard.start(self.brain.model_order)

    def run(self):
        try:
            self.start_dashboard()
            volume.recover()  # apps left turned down by a Jarvis stopped mid-listen
            self.load_voice()
            self.mic.start()
            self.speaker.say("Jarvis online.")
            self.mic.drain()
            self._set(State.IDLE)
            while not self.stopping.is_set():
                self._tick()
        except Exception:
            log.exception("Assistant crashed")
            self._set(State.ERROR)
        finally:
            if self.mic:
                self.mic.stop()

    def _tick(self):
        try:
            frame = self.mic.read(timeout=0.5)
        except queue.Empty:
            return

        if self.paused.is_set():
            if self.state != State.PAUSED:
                self._set(State.PAUSED)
            return
        if self.state == State.PAUSED:
            self.wake.reset()
            self._set(State.IDLE)

        if not self.wake.process(frame):
            return
        self.stt.prepare()  # GPU hearing starts loading now, while Jarvis answers (only during a conversation)

        self._set(State.LISTENING)
        self.speaker.chime("listen")
        self.mic.drain()  # don't transcribe our own chime
        try:
            self._conversation()
        except Exception:
            log.exception("Turn failed")
            self.speaker.say("Sorry, something went wrong.")

        # Falling chime = "I've stopped listening; say Hi Jarvis to start again".
        self.speaker.chime("sleep")
        # Forget everything heard while busy so Jarvis doesn't wake itself up.
        self.mic.drain()
        self.wake.reset()
        self._set(State.IDLE)

    def _conversation(self):
        """One command, then keep listening briefly for follow-ups without the wake word."""
        listen = self.config["listen"]
        followup = {**listen, "no_speech_timeout": listen.get("followup_seconds", 5)}
        first = True
        ignored = 0  # sentences in a row that weren't said to Jarvis

        while not self.stopping.is_set():
            if not first:
                self.stt.prepare()  # one-sentence GPU mode: load again while this follow-up is spoken
            saved = volume.duck() if listen.get("duck", True) else []  # music down while you speak
            try:
                window = {**listen, "no_speech_timeout": DICTATION_SILENCE} if self.dictating or self.coding \
                    else followup
                audio = record_utterance(self.mic, listen if first else window)
            finally:
                volume.restore(saved)
            if audio is None:
                self.stt.close()  # nobody spoke: free the GPU now, not after the helper's wait
                if self.dictating:  # a long quiet spell ends dictation: the next "Hi Jarvis" is a command again
                    self.dictating = False
                    log.info("Dictation off (quiet for %s s)", DICTATION_SILENCE)
                return  # silence: the caller plays the "back to sleep" chime

            self._set(State.THINKING)
            text = self.stt.transcribe(audio)
            if text.lower().strip(" .!?,") in _HALLUCINATIONS and not (self.dictating and text.strip()):
                if first:
                    self.speaker.say("Sorry, I didn't catch that.")
                return

            self.heard = dict(getattr(self.stt, "last", None) or {}) or None  # for the task log
            why = None if self.dictating else addressed.background_reason(
                text, (self.heard or {}).get("confidence"), followup=not first)
            if why:
                # 1 Oct: a Hindi talk in the room became 8 "requests". Not said to Jarvis: say nothing, and after
                # two of them go back to sleep.
                ignored += 1
                log.info("Ignoring %r: %s (%d in a row)", text[:80], why, ignored)
                tasklog.write({"said": text, "route": "ignored", "result": "ignored", "why": why, "seconds": 0,
                               **({"hearing": self.heard} if self.heard else {})})
                self.heard = None
                if ignored >= 2:
                    return
                first = False
                self.mic.drain()
                self._set(State.LISTENING)
                continue
            ignored = 0
            reply = self._handle_while_watching(text, self.stt.unsure)
            if reply:  # dictation types quietly
                self._set(State.SPEAKING)
                self.speaker.say(_NOT_DONE.sub("", reply))  # "Not done: X didn't connect." is said as a person would

            if self.skills.cancel.is_set():
                # "Hi Jarvis" while busy: stopped, now take the new command with a full listening window.
                self.skills.cancel.clear()
                self.mic.drain()
                self._set(State.LISTENING)
                self.speaker.chime("listen")
                self.mic.drain()
                first = True
                continue

            if not listen.get("followup_seconds") or self.gaming:
                return
            first = False
            self.mic.drain()  # drop our own voice before listening again
            self._set(State.LISTENING)

    def _handle_while_watching(self, text: str, unsure: bool = False) -> str:
        """Run the request, while a side thread keeps listening for "Hi Jarvis" so you can interrupt."""
        done = threading.Event()

        def watch():
            self.mic.drain()
            self.wake.reset()
            while not done.is_set():
                try:
                    frame = self.mic.read(timeout=0.2)
                except queue.Empty:
                    continue
                if self.wake.process(frame):
                    log.info("Wake word while busy: stopping the current task")
                    self.skills.cancel.set()
                    return

        watcher = threading.Thread(target=watch, name="interrupt-watch", daemon=True)
        watcher.start()
        try:
            return self.handle_text(text, unsure)
        finally:
            done.set()
            watcher.join(timeout=1)

    def stop(self):
        self.stopping.set()
