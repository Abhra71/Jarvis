"""The main loop: IDLE (wake word) -> LISTENING -> THINKING -> SPEAKING -> IDLE."""

import logging
import queue
import re
import threading
import webbrowser
from enum import Enum
from typing import Callable

from . import nlu
from .audio import Mic, record_utterance
from .brain import Brain, BrainUnavailable
from .skills import Skills
from .skills.browser import SITES, find_profile
from .stt import Transcriber
from .tts import Speaker
from .usage import usage
from .wakeword import WakeWordDetector

log = logging.getLogger(__name__)

# Words that make an "open …" / "search …" request too rich for the offline rules.
_NEEDS_AI = re.compile(r"\b(profile|account|tabs?|window|and|then|close|in my|on my|on youtube|on amazon)\b")

# Things Whisper tends to "hear" in silence or background noise.
_HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "bye", "okay", "hmm"}


class State(Enum):
    LOADING = "Loading..."
    IDLE = "Waiting for 'Hey Jarvis'"
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
        self.dashboard_url = None
        self.stt = None
        self.wake = None
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
            return False  # "search it here", "…in the address bar": the AI handles context far better
        if intent.name == "open_profile":
            return find_profile(self.skills.browser.profiles, intent.slots["profile"]) is not None
        if intent.name == "open_app" and _NEEDS_AI.search(text.lower()):
            return False
        if intent.name == "open_app":
            app = intent.slots["app"]
            return app in SITES or self.skills.apps.find_exact(app) is not None
        return True

    def handle_text(self, text: str) -> str:
        """Text in, spoken reply out. Used by both voice mode and --text mode."""
        usage.begin_turn(text)
        route, reply = self._handle(text)
        usage.end_turn(route, reply)
        log.info("Handled by %s", route)
        return reply

    def _handle(self, text: str) -> tuple[str, str]:
        """Returns (who handled it, reply)."""
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
            reply = self.brain.ask(text)
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

    def open_dashboard(self) -> str:
        if not self.dashboard_url:
            return "The status page isn't running."
        webbrowser.open(self.dashboard_url)
        return "Here's the AI status page."

    def _on_tool(self, name: str):
        if name == "look_at_screen":
            self._set(State.LOOKING)
        elif name in ("click", "scroll", "hover"):
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
            return "Both Gemini and the backup AI are unavailable right now. Simple commands like volume, timers and opening apps still work."
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
        self.stt = Transcriber(self.config["stt"])
        self.wake = WakeWordDetector(self.config["wakeword"])
        self.mic = Mic(self.config["audio"]["sample_rate"], self.config["audio"]["input_device"])

    def start_dashboard(self):
        from . import dashboard
        self.dashboard_url = dashboard.start(self.brain.model_order)

    def run(self):
        try:
            self.start_dashboard()
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

        self._set(State.LISTENING)
        self.speaker.chime("listen")
        self.mic.drain()  # don't transcribe our own chime
        try:
            self._conversation()
        except Exception:
            log.exception("Turn failed")
            self.speaker.say("Sorry, something went wrong.")

        # Falling chime = "I've stopped listening; say Hey Jarvis to start again".
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

        while not self.stopping.is_set():
            audio = record_utterance(self.mic, listen if first else followup)
            if audio is None:
                return  # silence: the caller plays the "back to sleep" chime

            self._set(State.THINKING)
            text = self.stt.transcribe(audio)
            if text.lower().strip(" .!?,") in _HALLUCINATIONS:
                if first:
                    self.speaker.say("Sorry, I didn't catch that.")
                return

            reply = self.handle_text(text)
            self._set(State.SPEAKING)
            self.speaker.say(reply)

            if not listen.get("followup_seconds"):
                return
            first = False
            self.mic.drain()  # drop our own voice before listening again
            self._set(State.LISTENING)

    def stop(self):
        self.stopping.set()
