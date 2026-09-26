"""Offline speech-to-text with faster-whisper."""

import logging
import os

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
        "Open my main profile.")


class Transcriber:
    def __init__(self, cfg: dict, vocabulary: list[str] | None = None):
        # Names of the user's installed apps, so e.g. "Claude" isn't heard as "Cloud".
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
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=3,  # weighs a few alternatives; measured at no extra time on this PC
            initial_prompt=self.hint,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text for s in segments).strip()
        log.info("Heard: %r", text)
        return text
