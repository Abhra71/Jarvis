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
    # Misheard in the user's session on 30 Sep ("Sema is all windows", "Time Chrome main profile"…).
    "Minimize all windows.", "Open Chrome in my main profile.", "Exit full screen and pause the video.",
    "Open Ishq Jalakar on YouTube.", "Play Rocky aur Rani Ki Prem Kahani full movie.", "Maximize the volume.",
    "Open Khazana chemistry.", "Open the file called the brutal revenge not ready.",
]
# Music in the room (30 Sep: a song played while the user spoke): another voice underneath.
NOISE_LINE = "Ishq jalakar, karvaan, dil ki baatein, raat bhar, yeh safar suhana hai, chalte rahe hum yahan"
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


def _with_music(audio: np.ndarray, music: np.ndarray, level: float = 0.35) -> np.ndarray:
    return (audio + np.resize(music, audio.shape) * level).astype(np.float32)


def _gpu_mb() -> int:
    import subprocess
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return -1


def main():
    from faster_whisper import WhisperModel
    load_cuda_libs()
    clean = [(t, v, asyncio.run(_speak(t, v))) for v in VOICES for t in COMMANDS]
    music = asyncio.run(_speak(NOISE_LINE, "hi-IN-MadhurNeural"))
    level = float(os.environ.get("MUSIC_LEVEL", "0.35"))  # 0.35 = loud room; Jarvis ducks apps to 12% of that
    noisy = [(t, v + "+music", _with_music(a, music, level)) for t, v, a in clean if v == VOICES[0]]
    clips = clean + noisy
    wanted = sys.argv[1:] or ["base.en", "small.en", "large-v3-turbo"]
    setups = [s for s in [("base.en cpu (fallback)", "base.en", "cpu", "int8"),
                          ("small.en gpu (now)", "small.en", "cuda", "int8_float16"),
                          ("large-v3-turbo gpu", "large-v3-turbo", "cuda", "int8_float16")] if s[1] in wanted]
    for label, name, device, ctype in setups:
        before = _gpu_mb()
        t_load = time.perf_counter()
        model = WhisperModel(name, device=device, compute_type=ctype, download_root=str(ROOT / "models" / "whisper"))
        load = time.perf_counter() - t_load
        model.transcribe(clips[0][2], language="en")  # warm up
        vram = _gpu_mb() - before if device == "cuda" else 0
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
        clean_err = 100 * sum(errors[:len(clean)]) / len(clean)
        noisy_err = 100 * sum(errors[len(clean):]) / max(1, len(noisy))
        print(f"\n== {label}: {exact}/{len(clips)} exact | word error clean {clean_err:.1f}%, with music "
              f"{noisy_err:.1f}% | median {1000 * sorted(times)[len(times) // 2]:.0f} ms | load {load:.1f}s | "
              f"GPU memory {vram} MB", flush=True)
        for w in wrong[:14]:
            print("   ", w)
        del model


if __name__ == "__main__":
    main()
