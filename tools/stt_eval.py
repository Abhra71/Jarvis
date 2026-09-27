"""Hearing benchmark: which Whisper setup understands Jarvis commands best, and how fast.

Speaks a set of real commands (including words misheard in live sessions) with edge-tts voices,
then transcribes them with each setup and reports word errors and time. Synthetic voices are
cleaner than a real room, so real-world error is higher, but the ranking holds.

    .venv\\Scripts\\python tools\\stt_eval.py
"""

import asyncio
import ctypes
import glob
import io
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import edge_tts  # noqa: E402
import miniaudio  # noqa: E402
import numpy as np  # noqa: E402

from jarvis.stt import HINT  # noqa: E402

COMMANDS = [
    "Open Physics Wallah.", "Connect to my Rockerz 480 headphones.", "Close this tab.", "Open a new tab.",
    "Only Gemini and Groq will be used.", "Open the Claude app.", "Play Aari Aari on YouTube.",
    "Minimize the browser.", "Snap this window to the left.", "Open Bluetooth settings.", "Knight to f3.",
    "Message Mom on WhatsApp: I'll be late.", "Start dictation.", "Go to line forty two.",
    "Compile the program in BlueJ.", "Start eFootball.", "Turn the brightness down to thirty percent.",
    "Skip the ad.", "Search for a nice Bollywood song.", "Scroll down a bit.",
]
VOICES = ["en-IN-PrabhatNeural", "en-IN-NeerjaNeural", "en-US-GuyNeural"]


def _words(s: str) -> list[str]:
    s = s.lower().replace("forty two", "42").replace("thirty", "30")
    return re.findall(r"[a-z0-9']+", s)


def wer(ref: str, hyp: str) -> float:
    r, h = _words(ref), _words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)] / max(1, len(r))


async def _speak(text: str, voice: str) -> np.ndarray:
    mp3 = b"".join([c["data"] async for c in edge_tts.Communicate(text, voice).stream() if c["type"] == "audio"])
    pcm = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1, sample_rate=16000)
    return np.frombuffer(pcm.samples.tobytes(), dtype=np.float32)


def load_cuda_libs():
    for p in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin", "*.dll")):
        try:
            ctypes.WinDLL(p)
        except OSError:
            pass


def main():
    from faster_whisper import WhisperModel
    load_cuda_libs()
    clips = [(t, v, asyncio.run(_speak(t, v))) for v in VOICES for t in COMMANDS]
    setups = [("base.en cpu (now)", "base.en", "cpu", "int8"),
              ("small.en gpu", "small.en", "cuda", "int8_float16")]
    for label, name, device, ctype in setups:
        model = WhisperModel(name, device=device, compute_type=ctype, download_root=str(ROOT / "models" / "whisper"))
        model.transcribe(clips[0][2], language="en")  # warm up
        errors, times, wrong = [], [], []
        for text, voice, audio in clips:
            t0 = time.perf_counter()
            segs, _ = model.transcribe(audio, language="en", beam_size=3, initial_prompt=HINT, vad_filter=False)
            heard = " ".join(s.text for s in segs).strip()
            times.append(time.perf_counter() - t0)
            e = wer(text, heard)
            errors.append(e)
            if e > 0:
                wrong.append(f"{text!r} -> {heard!r}")
        exact = sum(e == 0 for e in errors)
        print(f"\n== {label}: {exact}/{len(clips)} exact, word error {100 * sum(errors) / len(errors):.1f}%, "
              f"median {1000 * sorted(times)[len(times) // 2]:.0f} ms")
        for w in wrong[:12]:
            print("   ", w)
        del model


if __name__ == "__main__":
    main()
