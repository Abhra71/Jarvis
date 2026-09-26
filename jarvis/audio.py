"""Microphone capture and end-of-speech detection."""

import logging
import queue

import numpy as np
import sounddevice as sd
import webrtcvad

log = logging.getLogger(__name__)

FRAME_SAMPLES = 1280  # 80 ms at 16 kHz, the chunk size openWakeWord wants
VAD_SAMPLES = 320     # 20 ms, one of the frame sizes webrtcvad accepts


def list_devices() -> str:
    return str(sd.query_devices())


# Bluetooth headphones have a high-quality music mode with no mic, and a "Hands-Free"
# headset mode with a mic but phone-call quality. Opening the headset mic switches ALL audio
# to phone-call quality, so Jarvis never listens through one; it uses the laptop mic.
_BLUETOOTH_MIC = ("hands-free", "hands free", "bthhfenum", "headset", "bluetooth", " ag audio")


def _is_bluetooth(name: str) -> bool:
    return any(marker in name.lower() for marker in _BLUETOOTH_MIC)


def pick_input_device(name: str = "") -> int | None:
    """A real, non-Bluetooth microphone (MME list, so each device appears once)."""
    mme = next(i for i, api in enumerate(sd.query_hostapis()) if api["name"] == "MME")
    mics = [(i, d) for i, d in enumerate(sd.query_devices())
            if d["hostapi"] == mme and d["max_input_channels"] > 0
            and "sound mapper" not in d["name"].lower() and not _is_bluetooth(d["name"])]
    if name:
        for i, d in mics:
            if name.lower() in d["name"].lower():
                return i
        log.warning("Mic %r not found (or it's a Bluetooth headset mic); picking another", name)
    default = sd.default.device[0]
    for i, d in mics:
        if i == default:
            return i
    if mics:
        return mics[0][0]
    log.warning("No non-Bluetooth microphone found; using the Windows default")
    return None


def pick_output_device() -> int | None:
    """Windows' "Sound Mapper": always plays on whatever the current default output is, so Jarvis's
    voice moves to your headphones when you connect them, with no restart."""
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and d["name"].lower().startswith("microsoft sound mapper - output"):
            return i
    return None


class Mic:
    """Continuous 16 kHz mono int16 stream, delivered as 80 ms frames through a queue."""

    def __init__(self, sample_rate: int = 16000, device: str = ""):
        self.sample_rate = sample_rate
        self.frames: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=pick_input_device(device),
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.debug("mic status: %s", status)
        self.frames.put(indata[:, 0].copy())

    def start(self):
        self._stream.start()
        log.info("Mic started: %s", sd.query_devices(self._stream.device, "input")["name"])

    def stop(self):
        self._stream.stop()
        self._stream.close()

    def read(self, timeout: float | None = None) -> np.ndarray:
        return self.frames.get(timeout=timeout)

    def drain(self):
        """Throw away buffered audio, e.g. whatever Jarvis heard while it was talking."""
        while True:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                return


def record_utterance(mic: Mic, cfg: dict) -> np.ndarray | None:
    """Record after the wake word until the user stops talking.

    Returns float32 audio in [-1, 1] for Whisper, or None if nothing was said.
    """
    vad = webrtcvad.Vad(cfg["vad_aggressiveness"])
    frame_sec = FRAME_SAMPLES / mic.sample_rate
    max_frames = int(cfg["max_seconds"] / frame_sec)
    silence_limit = int(cfg["silence_seconds"] / frame_sec)
    no_speech_limit = int(cfg["no_speech_timeout"] / frame_sec)

    chunks = []
    heard_speech = False
    silent_run = 0

    for i in range(max_frames):
        frame = mic.read(timeout=2)
        chunks.append(frame)

        # A frame counts as speech if most of its 20 ms slices are speech.
        pieces = frame.reshape(-1, VAD_SAMPLES)
        voiced = sum(vad.is_speech(p.tobytes(), mic.sample_rate) for p in pieces)
        is_speech = voiced >= len(pieces) // 2

        if is_speech:
            heard_speech = True
            silent_run = 0
        else:
            silent_run += 1

        if not heard_speech and i >= no_speech_limit:
            log.info("No speech after wake word")
            return None
        if heard_speech and silent_run >= silence_limit:
            break

    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    log.info("Recorded %.1fs", len(audio) / mic.sample_rate)
    return audio
