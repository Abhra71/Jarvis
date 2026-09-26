"""Offline speech-to-text with faster-whisper."""

import logging
import os
import re

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
        "Open my main profile. Move the pawn from e2 to e4. Knight to f3. Bishop takes c4. Open chess.")

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


class Transcriber:
    def __init__(self, cfg: dict, vocabulary: list[str] | None = None):
        # Names of the user's installed apps, so e.g. "Claude" isn't heard as "Cloud".
        self.unsure = False  # was the last transcript a shaky guess?
        self.unsure_below = cfg.get("unsure_below", -0.35)
        self.hint = HINT + (" Apps: " + ", ".join(w.title() for w in vocabulary) + "." if vocabulary else "")
        log.info("Loading Whisper model %s (first run downloads it)...", cfg["model"])
        self.model = WhisperModel(
            cfg["model"],
            device="cpu",
            compute_type=cfg["compute_type"],
            download_root=str(MODELS_DIR / "whisper"),
        )
        log.info("Whisper ready")

    def transcribe(self, audio: np.ndarray) -> str:
        self.unsure = False
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=3,  # weighs a few alternatives; measured at no extra time on this PC
            initial_prompt=self.hint,
            condition_on_previous_text=False,
        )
        segments = list(segments)
        text = clean_transcript(" ".join(s.text for s in segments).strip())
        if not segments:
            log.info("Heard: ''")
            return ""
        # Whisper's own scores. Measured 26 Sep: pure noise = no-speech ~0.85 (and it "hears" its own hint,
        # e.g. "Open the pawn from e2 to e4"); real speech <= 0.2. Clear speech = confidence ~ -0.05,
        # misheard ("Look at that" for "What's the capital of Japan?") = -0.4 to -0.8.
        confidence = min(s.avg_logprob for s in segments)
        no_speech = max(s.no_speech_prob for s in segments)
        if no_speech > 0.6 and confidence < -0.5:
            log.info("Ignoring %r: sounds like noise, not speech (no-speech %.2f)", text, no_speech)
            return ""
        self.unsure = confidence < self.unsure_below
        log.info("Heard: %r (confidence %.2f%s)", text, confidence, ", unsure" if self.unsure else "")
        return text
