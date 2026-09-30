import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import tasklog
from jarvis.agent.run import Outcome


class TaskLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("LOG_DIR", Path(self.tmp.name)), ("FORCE", True)):
            p = mock.patch.object(tasklog, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_results_from_the_reply(self):
        c = tasklog.classify
        self.assertEqual(c("offline rules", "Volume 40."), "done")
        self.assertEqual(c("groq", "Which file do you mean?"), "asked")
        self.assertEqual(c("agent", "Chrome didn't close. What should I do?"), "stuck")
        self.assertEqual(c("agent", "I pressed Enter, but I can't tell if it worked."), "unconfirmed")
        self.assertEqual(c("ability", "Not done: no File Explorer folder is open."), "failed")
        self.assertEqual(c("stopped", "You moved the mouse, so I stopped."), "stopped")

    def test_an_agent_turn_is_written_with_its_outcome(self):
        o = Outcome("open clawed", source="ai", steps=0, ai_calls=1, result="needs_yes", detail="")
        turn = tasklog.Turn("Open Clawed.", {"source": "cloud", "confidence": -0.8, "unsure": True})
        e = turn.finish("agent", "I couldn't find Clawed. Did you mean Claude?", o)
        self.assertEqual((e["result"], e["ai_calls"], e["plan"]), ("asked", 1, "ai"))
        saved = [json.loads(x) for x in tasklog.path_for().read_text(encoding="utf-8").splitlines()]
        self.assertEqual(saved[0]["said"], "Open Clawed.")
        self.assertEqual(saved[0]["hearing"]["source"], "cloud")

    def test_summary_lists_what_went_wrong(self):
        for said, route, reply in [("volume 40", "offline rules", "Volume 40."),
                                   ("open x", "agent", "X didn't come up. What should I do?"),
                                   ("what", "groq", "Which one?")]:
            tasklog.Turn(said).finish(route, reply)
        s = tasklog.summary(tasklog.read())
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["worked_percent"], 33)
        self.assertEqual([e["said"] for e in s["wrong"]], ["open x"])

    def test_off_under_the_test_suite_by_default(self):
        with mock.patch.object(tasklog, "FORCE", None):
            tasklog.write({"said": "x", "result": "done", "route": "r", "seconds": 0})
        self.assertFalse(tasklog.path_for().exists())


if __name__ == "__main__":
    unittest.main()
