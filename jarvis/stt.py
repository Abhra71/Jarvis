"""Offline speech-to-text with faster-whisper."""

import json
import logging
import os
import re
import subprocess
import sys
import threading

# Windows without Developer Mode can't symlink; the HF cache works fine without it.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

from .config import MODELS_DIR  # noqa: E402

log = logging.getLogger(__name__)

# Nudges Whisper towards the words our commands actually use. The second line holds commands it
# misheard on 26 Sep ("Close this one" -> "North this one", "Scroll" -> "Scrawl").
HINT = ("Open Chrome. Volume 40. Volume up. Mute. Search for Python tutorials. Set a timer for 5 minutes. "
        "Close this one. Close this tab. Close both of them. Scroll to the bottom. Go back. Next tab. "
        "Open my main profile. Move the pawn from e2 to e4. Knight to f3. Bishop takes c4. Open chess. "
        # The user's own names, misheard in sessions and in tools/stt_eval.py (27 Sep): "Physics Voila",
        # "Groke", "cloud app", "rocker's", "your football".
        "Physics Wallah, Groq, Gemini, Claude, Rockerz 480, eFootball, BlueJ, WhatsApp, VS Code, YouTube. "
        # Misheard by every model on 30 Sep: "Kazana", "Skip the end".
        "Open Khazana chemistry. Skip the ad. Minimize all windows. Exit full screen.")

_SENTENCE = re.compile(r"[^.!?]+[.!?]*")


def clean_transcript(text: str) -> str:
    """Whisper sometimes "hears" a phrase over and over in noise, often one from its own hint
    ("Open Chrome. Open Chrome. Open Chrome. Open Chrome." on 26 Sep, when nobody said it).
    Three or more of the same sentence = noise, not speech. A doubled sentence is kept once."""
    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
    keys = [s.lower().strip(" .!?,") for s in sentences]
    if len(keys) >= 3 and len(set(keys)) == 1:
        log.info("Ignoring %r: the same phrase repeated is a speech-recognition glitch", text)
        return ""
    kept = [s for i, s in enumerate(sentences) if i == 0 or keys[i] != keys[i - 1]]
    return " ".join(kept)


class GpuHearing:
    """The small.en model on the GPU, in a helper process that only lives during a conversation
    (the user's rule: no GPU memory while Jarvis is just waiting). See stt_worker.py."""

    def __init__(self, model: str, idle_seconds: float):
        self.model, self.idle = model, idle_seconds
        self.load_wait = 0.5  # how long a finished sentence may wait for the model to finish loading
        self.proc: subprocess.Popen | None = None
        self.ready = threading.Event()
        self.failed = False
        self.lock = threading.Lock()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        """Called on "Hey Jarvis": load the model while Jarvis answers and you start talking."""
        with self.lock:
            if self.alive() or self.failed:
                return
            self.ready.clear()
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "jarvis.stt_worker", self.model, str(self.idle), str(MODELS_DIR / "whisper")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=str(MODELS_DIR.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            threading.Thread(target=self._wait_ready, args=(self.proc,), daemon=True).start()

    def _wait_ready(self, proc: subprocess.Popen):
        line = proc.stdout.readline()
        try:
            msg = json.loads(line) if line else {"error": "the helper exited"}
        except ValueError:
            msg = {"error": f"unexpected output {line[:80]!r}"}
        if proc is not self.proc:
            return  # stopped on purpose (no follow-up speech): not a failure
        if msg.get("ready"):
            log.info("GPU hearing ready (%s, loaded in %.1fs)", self.model, msg.get("load_seconds", 0))
            self.ready.set()
        else:
            log.warning("GPU hearing unavailable, using the CPU: %s", msg.get("error"))
            from .notify import fell_back
            fell_back("hearing-gpu", "Hearing: GPU model unavailable → CPU model")
            self.failed = True  # e.g. no NVIDIA libraries: don't keep trying this session
            proc.kill()

    def transcribe(self, audio: np.ndarray, prompt: str, timeout: float = 8.0) -> dict | None:
        """{"text", "confidence", "no_speech", "segments"} or None (then the CPU model is used)."""
        if not self.alive():
            self.start()
        # Still loading (a very short first sentence)? Don't make the user wait: the CPU model takes this
        # one (~0.65 s) and the GPU takes the next.
        if not self.ready.wait(self.load_wait) or not self.alive():
            log.info("GPU hearing still loading; the CPU takes this sentence")
            from .notify import popup
            popup("Hearing: GPU still loading → CPU model this time", "hearing-cpu-wait")
            return None
        proc = self.proc
        result: dict = {}

        def talk():
            try:
                data = np.ascontiguousarray(audio, dtype=np.float32).tobytes()
                proc.stdin.write((json.dumps({"samples": len(data) // 4, "prompt": prompt}) + "\n").encode())
                proc.stdin.write(data)
                proc.stdin.flush()
                result.update(json.loads(proc.stdout.readline()))
            except (OSError, ValueError) as e:
                result["error"] = str(e)

        t = threading.Thread(target=talk, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or "error" in result or "text" not in result:
            log.warning("GPU hearing failed (%s); using the CPU this time", result.get("error", "timed out"))
            proc.kill()
            return None
        if self.idle <= 0:
            self.proc = None  # one sentence per helper: it has exited (or is exiting) and freed the GPU
        return result

    def stop(self):
        # 30 Sep log: stopping a helper that was still loading looked like "the helper exited", so the GPU was
        # switched off for the rest of the session. Forget it first, so its reader knows it was on purpose.
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.kill()


class CloudHearing:
    """Groq's hosted Whisper large-v3: the user's laptop never switches its GPU on for hearing (30 Sep).

    Measured on the 112-clip test: 6.1% word errors in a quiet room, 7.4% with ducked music, 0.34 s, no model
    to load. Free tier: 2,000 requests a day, 20 a minute. When it's down, rate-limited or slow, the local
    models take the sentence and the cloud is left alone for a minute."""

    URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, model: str, key: str, timeout: float):
        import httpx
        self.model, self.key, self.timeout = model, key, timeout
        self.http = httpx.Client(timeout=timeout)
        self.resting_until = 0.0
        self.was_down = False

    def usable(self) -> bool:
        import time
        return time.monotonic() >= self.resting_until

    def transcribe(self, audio: np.ndarray, prompt: str) -> dict | None:
        import io
        import time
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        t0 = time.monotonic()
        try:
            r = self.http.post(self.URL, headers={"Authorization": f"Bearer {self.key}"},
                               files={"file": ("speech.wav", buf.getvalue(), "audio/wav")},
                               data={"model": self.model, "language": "en", "prompt": prompt[:800],
                                     "response_format": "verbose_json", "temperature": "0"})
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            log.warning("Cloud hearing failed (%s); the local model takes this sentence",
                        f"HTTP {status}" if status else type(e).__name__)
            self.resting_until = time.monotonic() + 60
            self.was_down = True
            from .notify import fell_back
            fell_back("hearing-cloud", "Hearing: cloud unavailable → local model")
            return None
        segments = data.get("segments") or []
        log.info("Cloud hearing in %.2fs", time.monotonic() - t0)
        if self.was_down:
            self.was_down = False
            from .notify import recovered
            recovered("hearing-cloud", "Hearing: back on the cloud (Groq Whisper)")
        return {"text": (data.get("text") or "").strip(), "segments": len(segments),
                "confidence": min((s.get("avg_logprob", 0.0) for s in segments), default=0.0),
                "no_speech": max((s.get("no_speech_prob", 1.0) for s in segments), default=1.0)}


class Transcriber:
    def __init__(self, cfg: dict, vocabulary: list[str] | None = None):
        # Names of the user's installed apps, so e.g. "Claude" isn't heard as "Cloud".
        self.unsure = False  # was the last transcript a shaky guess?
        self.unsure_below = cfg.get("unsure_below", -0.35)
        self.hint = HINT + (" Apps: " + ", ".join(w.title() for w in vocabulary) + "." if vocabulary else "")
        # The CPU model is always there (RAM only, no GPU): the fallback, and the whole thing without a GPU.
        log.info("Loading Whisper model %s (first run downloads it)...", cfg["model"])
        self.model = WhisperModel(
            cfg["model"],
            device="cpu",
            compute_type=cfg["compute_type"],
            download_root=str(MODELS_DIR / "whisper"),
        )
        gpu_model = cfg.get("gpu_model")
        self.gpu = GpuHearing(gpu_model, cfg.get("gpu_idle_seconds", 120)) if gpu_model else None
        if self.gpu:
            self.gpu.load_wait = cfg.get("gpu_load_wait", 0.5)
        self.cloud = None
        if cfg.get("cloud_model"):
            from .brain import load_api_key
            key = load_api_key("GROQ_API_KEY")
            if key:
                self.cloud = CloudHearing(cfg["cloud_model"], key, cfg.get("cloud_timeout", 3.0))
        log.info("Whisper ready%s%s", f" (cloud {cfg.get('cloud_model')} first)" if self.cloud else "",
                 f" (GPU {gpu_model} on demand)" if self.gpu else "")

    def prepare(self):
        """About to listen: get the GPU model loading while the user speaks (only when the cloud isn't used)."""
        if self.cloud and self.cloud.usable():
            return  # the GPU stays off
        if self.gpu:
            self.gpu.start()

    def close(self):
        if self.gpu:
            self.gpu.stop()

    def transcribe(self, audio: np.ndarray) -> str:
        self.unsure = False
        result = None
        if self.cloud and self.cloud.usable():
            result = self.cloud.transcribe(audio, self.hint)  # None: the CPU model takes it (no loading wait)
        elif self.gpu:
            result = self.gpu.transcribe(audio, self.hint)
        if result is None:
            segments, _ = self.model.transcribe(
                audio,
                language="en",
                beam_size=3,  # weighs a few alternatives; measured at no extra time on this PC
                initial_prompt=self.hint,
                condition_on_previous_text=False,
            )
            segments = list(segments)
            result = {"text": " ".join(s.text for s in segments).strip(), "segments": len(segments),
                      "confidence": min((s.avg_logprob for s in segments), default=0.0),
                      "no_speech": max((s.no_speech_prob for s in segments), default=1.0)}
        text = clean_transcript(result["text"])
        if not result["segments"]:
            log.info("Heard: ''")
            return ""
        # Whisper's own scores. Measured 26 Sep: pure noise = no-speech ~0.85 (and it "hears" its own hint,
        # e.g. "Open the pawn from e2 to e4"); real speech <= 0.2. Clear speech = confidence ~ -0.05,
        # misheard ("Look at that" for "What's the capital of Japan?") = -0.4 to -0.8.
        confidence, no_speech = result["confidence"], result["no_speech"]
        if no_speech > 0.6 and confidence < -0.5:
            log.info("Ignoring %r: sounds like noise, not speech (no-speech %.2f)", text, no_speech)
            return ""
        self.unsure = confidence < self.unsure_below
        log.info("Heard: %r (confidence %.2f%s)", text, confidence, ", unsure" if self.unsure else "")
        return text
