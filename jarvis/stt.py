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

# Nudges Whisper towards the words our commands actually use.
HINT = "Open Chrome. Volume 40. Volume up. Mute. Search for Python tutorials. Set a timer for 5 minutes."


class Transcriber:
    def __init__(self, cfg: dict):
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
            beam_size=1,
            initial_prompt=HINT,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text for s in segments).strip()
        log.info("Heard: %r", text)
        return text
