"""The pipeline router: the proven-best model first, skipped while resting or out of budget (no real calls)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.llm import router as R
from jarvis.llm.providers import Reply


class _Clock:
    def __init__(self):
        self.t = 1_760_000_000.0

    def __call__(self):
        return self.t


class RouterTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = mock.patch.object(R, "STATE", Path(d.name) / "state.json")
        p.start()
        self.addCleanup(p.stop)
        self.clock = _Clock()
        self.r = R.Router({"understand": ["groq:a", "gemini:b", "nvidia:c"]}, clock=self.clock)

    def test_best_first_and_a_failing_model_is_rested_then_back(self):
        self.assertEqual(self.r.candidates("understand")[0], "groq:a")
        self.r.record(Reply("groq:a", error="server"))
        self.assertEqual(self.r.candidates("understand")[0], "gemini:b")
        self.clock.t += 31
        self.assertEqual(self.r.candidates("understand")[0], "groq:a")

    def test_switches_before_the_minute_token_limit_is_hit(self):
        for _ in range(5):
            self.r.record(Reply("groq:a", text="{}", tokens_in=1500, tokens_out=100))
        self.assertNotIn("groq:a", self.r.candidates("understand", tokens=1500))  # 8,000 a minute: 8,000 + 1,500 > 8,000
        self.clock.t += 61
        self.assertIn("groq:a", self.r.candidates("understand", tokens=1500))

    def test_cached_tokens_do_not_count(self):
        for _ in range(5):
            self.r.record(Reply("groq:a", text="{}", tokens_in=1500, tokens_out=100, cached=1400))
        self.assertIn("groq:a", self.r.candidates("understand", tokens=300))

    def test_what_groq_says_is_left_is_believed(self):
        self.r.record(Reply("groq:a", text="{}", tokens_in=10, extra={"limits": {"requests_left": 0}}))
        self.assertNotIn("groq:a", self.r.candidates("understand"))

    def test_run_falls_through_the_chain(self):
        def attempt(model):
            if model == "groq:a":
                return None, Reply(model, error="timeout")
            return {"kind": "ignore"}, Reply(model, text="{}")
        result, replies = self.r.run("understand", attempt)
        self.assertEqual(result, {"kind": "ignore"})
        self.assertEqual([r.model for r in replies], ["groq:a", "gemini:b"])


if __name__ == "__main__":
    unittest.main()
