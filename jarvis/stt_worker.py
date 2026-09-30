"""Speech-to-text on the GPU, in its own process, only during a conversation.

The user's rule (27 Sep): GPU memory may be used only while they're talking to Jarvis, never
continuously. So Jarvis starts this process when it hears "Hey Jarvis" (stt.py), and the process
exits by itself after `idle` seconds without a request. Only a process exit gives the GPU memory
back completely: NVIDIA's own context (~90 MB) stays until the process ends.

Protocol on stdin/stdout, one request at a time:
    request:  a JSON line {"samples": n, "prompt": "..."} followed by n float32 samples (16 kHz mono)
    reply:    a JSON line {"text": "...", "confidence": -0.1, "no_speech": 0.02, "seconds": 0.2}
First line out is {"ready": true, "load_seconds": 1.9} (or {"error": "..."}).

    python -m jarvis.stt_worker small.en 120
"""

import ctypes
import glob
import json
import os
import queue
import sys
import threading
import time

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def _load_cuda_libs():
    """NVIDIA's cuBLAS/cuDNN come as pip packages; the speech engine doesn't look in their folders, so load
    them up front (by full path) and it finds them already in the process."""
    for path in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin", "*.dll")):
        try:
            ctypes.WinDLL(path)
        except OSError:
            pass


FIRST_WAIT = 30.0  # seconds to wait for the sentence in one-sentence mode


def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else "small.en"
    idle = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    models_dir = sys.argv[3] if len(sys.argv) > 3 else None
    t0 = time.monotonic()
    try:
        import numpy as np
        _load_cuda_libs()
        from faster_whisper import WhisperModel
        model = WhisperModel(model_name, device="cuda", compute_type="int8_float16", download_root=models_dir)
    except Exception as e:  # no GPU, missing libraries, blocked DLL: Jarvis falls back to the CPU
        _send({"error": f"{type(e).__name__}: {e}"})
        return
    _send({"ready": True, "load_seconds": round(time.monotonic() - t0, 2)})

    requests: queue.Queue = queue.Queue()
    stdin = sys.stdin.buffer

    def reader():
        while True:
            line = stdin.readline()
            if not line:
                requests.put(None)  # Jarvis closed the pipe (it quit): stop
                return
            header = json.loads(line)
            data = stdin.read(4 * header["samples"])
            requests.put((header, data))

    threading.Thread(target=reader, daemon=True).start()
    # idle 0 = one sentence, then exit (the user's rule, 30 Sep: the GPU is on only while they speak and it
    # hears them, never while Jarvis thinks, talks or waits). It still waits a while for that one sentence.
    once = idle <= 0
    while True:
        try:
            item = requests.get(timeout=FIRST_WAIT if once else idle)
        except queue.Empty:
            return  # a quiet spell: exit, which frees all GPU memory
        if item is None:
            return
        header, data = item
        started = time.monotonic()
        try:
            audio = np.frombuffer(data, dtype=np.float32)
            segments, _ = model.transcribe(audio, language="en", beam_size=3, initial_prompt=header.get("prompt"),
                                           condition_on_previous_text=False)
            segments = list(segments)
            _send({"text": " ".join(s.text for s in segments).strip(),
                   "confidence": min((s.avg_logprob for s in segments), default=0.0),
                   "no_speech": max((s.no_speech_prob for s in segments), default=1.0),
                   "segments": len(segments), "seconds": round(time.monotonic() - started, 3)})
        except Exception as e:
            _send({"error": f"{type(e).__name__}: {e}"})
        if once:
            return  # exiting frees every byte of GPU memory


if __name__ == "__main__":
    main()
