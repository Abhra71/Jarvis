"""'Hi Jarvis' detection with openWakeWord (free, offline)."""

import logging
import sys
import time
import types

import numpy as np

# openwakeword/__init__.py imports its verifier-training helper, which pulls in
# scikit-learn. Windows Smart App Control blocks one of sklearn's DLLs on this PC,
# and we never train verifiers, so hand it an empty stand-in module instead.
if "openwakeword.custom_verifier_model" not in sys.modules:
    _stub = types.ModuleType("openwakeword.custom_verifier_model")
    _stub.train_custom_verifier = None
    sys.modules["openwakeword.custom_verifier_model"] = _stub

import openwakeword  # noqa: E402
import openwakeword.utils  # noqa: E402
from openwakeword.model import Model  # noqa: E402

log = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self, cfg: dict):
        self.threshold = cfg["threshold"]
        self.cooldown = cfg["cooldown_seconds"]
        self._last_trigger = 0.0

        # Downloads the shared feature models + pretrained wake words on first run.
        openwakeword.utils.download_models([cfg["model"]])
        self.model = Model(wakeword_models=[cfg["model"]], inference_framework="onnx")
        log.info("Wake word model loaded: %s", cfg["model"])

    def process(self, frame: np.ndarray) -> bool:
        """Feed one 80 ms int16 frame. Returns True when the wake word is heard."""
        scores = self.model.predict(frame)
        score = max(scores.values())
        if score < self.threshold:
            return False
        now = time.monotonic()
        if now - self._last_trigger < self.cooldown:
            return False
        self._last_trigger = now
        log.info("Wake word detected (score %.2f)", score)
        return True

    def reset(self):
        self.model.reset()
