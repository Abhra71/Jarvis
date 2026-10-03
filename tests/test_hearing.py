"""Hearing: the GPU model only during a conversation, with the CPU model as the fallback. No real models."""

import unittest
from unittest import mock

import numpy as np

from jarvis import stt


class FakeSegment:
    def __init__(self, text, logprob=-0.1, no_speech=0.01):
        self.text, self.avg_logprob, self.no_speech_prob = text, logprob, no_speech


def _transcriber(gpu_result):
    with mock.patch.object(stt, "WhisperModel") as cpu_cls:
        cpu_cls.return_value.transcribe.return_value = ([FakeSegment("heard on the cpu")], None)
        t = stt.Transcriber({"model": "base.en", "compute_type": "int8", "gpu_model": "small.en"})
    t.gpu = mock.Mock()
    t.gpu.transcribe.return_value = gpu_result
    return t


class HearingTest(unittest.TestCase):
    def test_gpu_answer_is_used(self):
        t = _transcriber({"text": "Open Physics Wallah.", "segments": 1, "confidence": -0.1, "no_speech": 0.0})
        self.assertEqual(t.transcribe(np.zeros(16000, dtype=np.float32)), "Open Physics Wallah.")
        t.model.transcribe.assert_not_called()

    def test_cpu_takes_over_when_the_gpu_is_not_ready_or_fails(self):
        t = _transcriber(None)
        self.assertEqual(t.transcribe(np.zeros(16000, dtype=np.float32)), "heard on the cpu")

    def test_wake_word_starts_the_gpu_and_nothing_before(self):
        with mock.patch.object(stt, "WhisperModel"), mock.patch.object(stt.subprocess, "Popen") as popen:
            t = stt.Transcriber({"model": "base.en", "compute_type": "int8", "gpu_model": "small.en"})
            popen.assert_not_called()  # the user's rule: no GPU while Jarvis just waits
            with mock.patch.object(stt.threading, "Thread"):
                t.prepare()
            popen.assert_called_once()
            self.assertIn("jarvis.stt_worker", popen.call_args.args[0])

    def test_no_gpu_model_configured_means_cpu_only(self):
        with mock.patch.object(stt, "WhisperModel"):
            t = stt.Transcriber({"model": "base.en", "compute_type": "int8"})
        self.assertIsNone(t.gpu)
        t.prepare()  # nothing to start

    def test_stopping_a_loading_gpu_is_not_a_failure(self):
        g = stt.GpuHearing("small.en", 0)
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.stdout.readline.return_value = b""  # killed while loading
        g.proc = proc
        g.stop()
        g._wait_ready(proc)
        self.assertFalse(g.failed)

    def test_a_broken_gpu_is_not_retried_all_session(self):
        g = stt.GpuHearing("small.en", 120)
        proc = mock.Mock()
        proc.stdout.readline.return_value = b'{"error": "cublas64_12.dll not found"}\n'
        g.proc = proc
        g._wait_ready(proc)
        self.assertTrue(g.failed)
        with mock.patch.object(stt.subprocess, "Popen") as popen:
            g.start()
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class GreetingTest(unittest.TestCase):
    """3 Oct: the wake phrase is "Hi Jarvis"; heard again at the start, it must not hide the command from the code."""

    def test_the_wake_phrase_is_dropped_from_the_request(self):
        from jarvis.stt import strip_greeting
        for said in ("Hi Jarvis, open Chrome", "High Jarvis, open Chrome", "Hi, Jarvis. open Chrome",
                     "Hey Jarvis open Chrome", "hai jarvis, open Chrome"):
            self.assertEqual(strip_greeting(said), "open Chrome", said)
        self.assertEqual(strip_greeting("Hi Jarvis."), "Hi Jarvis.")  # nothing after it: kept
        self.assertEqual(strip_greeting("Jarvis is a film"), "Jarvis is a film")
