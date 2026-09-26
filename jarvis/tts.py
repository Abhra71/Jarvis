"""Spoken replies: Microsoft neural voice via edge-tts, falling back to the offline Windows voice."""

import asyncio
import logging
import threading
import time

import comtypes
import comtypes.client
import edge_tts
import miniaudio
import numpy as np
import sounddevice as sd

from .audio import pick_output_device
from .skills import volume

log = logging.getLogger(__name__)

_EDGE_RATE = 24000


def _tone(freqs, ms=90, rate=_EDGE_RATE, volume=0.25) -> np.ndarray:
    parts = []
    for f in freqs:
        t = np.arange(int(rate * ms / 1000)) / rate
        wave = np.sin(2 * np.pi * f * t) * np.hanning(len(t))
        parts.append(wave)
    return (np.concatenate(parts) * volume).astype(np.float32)


def _soft_chime(freqs, note_ms=130, step_ms=85, rate=_EDGE_RATE, volume=0.16) -> np.ndarray:
    """A gentle bell-like chime: soft attack, natural fade, notes overlapping slightly.

    Pure sine plus a faint octave overtone and a quick exponential decay, so it sounds
    like a small bell rather than a beep.
    """
    n_note = int(rate * note_ms / 1000)
    step = int(rate * step_ms / 1000)
    out = np.zeros(step * (len(freqs) - 1) + n_note)
    t = np.arange(n_note) / rate
    envelope = np.minimum(1.0, t / 0.006) * np.exp(-t / (note_ms / 1000 / 3.5))
    for i, f in enumerate(freqs):
        note = (np.sin(2 * np.pi * f * t) + 0.15 * np.sin(2 * np.pi * 2 * f * t)) * envelope
        out[i * step:i * step + n_note] += note
    out /= np.abs(out).max()
    return (out * volume).astype(np.float32)


# E5 -> A5 going up means "I'm listening"; A5 -> E5 going down means "back to sleep".
LISTEN_CHIME = _soft_chime([659.3, 880.0])
SLEEP_CHIME = _soft_chime([880.0, 659.3])


class Speaker:
    def __init__(self, cfg: dict):
        self.engine = cfg["engine"]
        self.voice = cfg["voice"]
        self.rate = cfg["rate"]
        self.wake_reply = cfg.get("wake_reply", "Yes, my lord?")
        self._lock = threading.Lock()  # timers can finish while Jarvis is already talking
        self._chimes = {"listen": LISTEN_CHIME, "sleep": SLEEP_CHIME}
        self._output = pick_output_device()  # follows the Windows default (headphones when connected)

    def prepare(self):
        """Pre-record the wake reply ("Yes, my lord?") at startup so it plays instantly, not after a network trip.
        If that fails (offline), the soft rising chime is used instead."""
        if self.engine != "edge" or not self.wake_reply:
            return
        try:
            self._chimes["listen"] = self._edge_audio(self.wake_reply)
        except Exception as e:
            log.warning("Couldn't pre-record the wake reply (%s); using a chime", e)

    def _play(self, audio: np.ndarray, rate: int = _EDGE_RATE):
        volume.ensure_jarvis_audible()  # a muted PC must not silence Jarvis itself
        sd.play(audio, rate, device=self._output)
        # Never wait forever: on 26 Sep Jarvis froze for 6 minutes while playing "Yes, my lord?" (likely the
        # sound device changed mid-play, and sd.wait() never returned). Give up after the clip's length + 2 s.
        deadline = time.monotonic() + len(audio) / rate + 2.0
        while time.monotonic() < deadline:
            try:
                if not sd.get_stream().active:
                    return
            except Exception:
                return
            time.sleep(0.05)
        log.warning("Audio playback got stuck; stopping it and carrying on")
        try:
            sd.stop()
        except Exception:
            log.debug("sd.stop failed", exc_info=True)

    def chime(self, kind: str = "listen"):
        """'listen' = "Yes, my lord?" after "Hey Jarvis"; 'sleep' = soft falling chime, back to waiting for "Hey Jarvis"."""
        log.info("Sound: %s", "wake reply" if kind == "listen" else "back-to-sleep chime")
        with self._lock:
            self._play(self._chimes.get(kind, SLEEP_CHIME))

    def say(self, text: str):
        log.info("Jarvis: %s", text)
        with self._lock:
            if self.engine == "beep":
                self._play(LISTEN_CHIME)
                return
            if self.engine == "edge":
                try:
                    self._play(self._edge_audio(text))
                    return
                except Exception as e:
                    log.warning("edge-tts failed (%s), using offline voice", e)
            self._say_offline(text)

    def _edge_audio(self, text: str) -> np.ndarray:
        async def fetch() -> bytes:
            mp3 = bytearray()
            async for chunk in edge_tts.Communicate(text, self.voice, rate=self.rate).stream():
                if chunk["type"] == "audio":
                    mp3.extend(chunk["data"])
            return bytes(mp3)

        async def fetch_with_limit() -> bytes:
            return await asyncio.wait_for(fetch(), timeout=8)  # a network hiccup mustn't freeze Jarvis

        mp3 = asyncio.run(fetch_with_limit())
        decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.FLOAT32,
                                   nchannels=1, sample_rate=_EDGE_RATE)
        return np.frombuffer(decoded.samples, dtype=np.float32)

    def _say_offline(self, text: str):
        comtypes.CoInitialize()
        comtypes.client.CreateObject("SAPI.SpVoice").Speak(text)
