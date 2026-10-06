"""The new brain end to end with a fake model and fake hands: act, ask, ignore, and a yes before deleting."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.llm import brain2, router as R
from jarvis.llm.providers import Reply


class FakeSkills:
    def __init__(self):
        self.calls, self.confirmed = [], False

    def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "choose_menu_item" and not self.confirmed:
            return "Needs confirmation: this would click 'Remove'. Nothing was done."
        return "Done."


class NewBrainTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for p in (mock.patch.object(R, "STATE", Path(d.name) / "s.json"),
                  mock.patch("jarvis.llm.brain2.desktop.front_window", return_value="javaw: BlueJ: JarvisScratch")):
            p.start()
            self.addCleanup(p.stop)
        self.answers = []
        self.skills = FakeSkills()
        self.brain = brain2.NewBrain(self.skills, R.Router({"understand": ["groq:x"]}), screen=lambda: "front: BlueJ")

    def _model(self, *meanings):
        it = iter(meanings)
        return mock.patch("jarvis.llm.brain2.U.understand", side_effect=lambda *a, **k: (next(it), Reply("groq:x", text="{}")))

    def test_act_says_the_short_reply(self):
        with self._model({"kind": "act", "steps": [{"do": "tab", "action": "close"}], "say": "Closing this tab."}):
            self.assertEqual(self.brain.handle("close this tab"), ("brain2", "Closing this tab."))

    def test_noise_gets_silence(self):
        with self._model({"kind": "ignore", "steps": []}):
            self.assertEqual(self.brain.handle("Ws."), ("ignored", None))

    def test_deleting_asks_then_does_it_after_yes(self):
        delete = {"kind": "act", "steps": [{"do": "bluej", "action": "delete_class", "name": "Oval"}], "say": "Deleting Oval."}
        with self._model(delete, {"kind": "control", "control": "yes", "steps": []}):
            route, reply = self.brain.handle("delete the class Oval")
            self.assertIn("Should I", reply)
            self.assertIn("Remove", reply)
            self.assertEqual(self.brain.handle("yes"), ("brain2", "Done."))
        self.assertEqual([t for t, _ in self.skills.calls][-2:], ["right_click", "choose_menu_item"])
        self.assertFalse(self.skills.confirmed)  # the yes covered that one action only

    def test_no_drops_the_waiting_action(self):
        delete = {"kind": "act", "steps": [{"do": "bluej", "action": "delete_class", "name": "Oval"}], "say": "x"}
        with self._model(delete, {"kind": "control", "control": "no", "steps": []}):
            self.brain.handle("delete the class Oval")
            self.assertEqual(self.brain.handle("no"), ("brain2", "Okay, I left it."))
        self.assertIsNone(self.brain.pending)

    def test_a_failed_step_is_said_plainly(self):
        self.skills.call = lambda tool, args: "Not clicked: Nothing called 'Lecture 3' is on screen."
        with self._model({"kind": "act", "steps": [{"do": "click", "target": "Lecture 3"}], "say": "Opening it."}):
            self.assertEqual(self.brain.handle("open lecture 3")[1], "I couldn't find Lecture 3 on the screen.")


if __name__ == "__main__":
    unittest.main()


class SwitchTest(unittest.TestCase):
    """config [ai] brain = "new" sends sentences to the new brain; "old" (the default) keeps the old path."""

    def _assistant(self, brain):
        from jarvis import assistant, corrections
        a = assistant.Assistant.__new__(assistant.Assistant)
        a.dictating, a.coding, a.gaming = False, False, False
        a.corrections = corrections.Corrections(None)
        a.last_request, a.fixed_request = "", None
        a.skills = mock.Mock()
        a.brain = mock.Mock(answer_agent=mock.Mock(return_value=None), agent=None)
        a.config = {"ai": {"brain": brain}}
        a.newbrain = mock.Mock()
        return a

    def test_new_brain_gets_the_sentence_and_noise_is_silent(self):
        a = self._assistant("new")
        a.newbrain.handle.return_value = ("ignored", None)
        self.assertEqual(a._handle("Ego, WP, Aps,"), ("ignored", ""))
        a.newbrain.handle.return_value = ("control", "coding_on")
        self.assertEqual(a._handle("coding mode, please")[0], "coding")
        self.assertTrue(a.coding)

    def test_old_brain_stays_by_default(self):
        a = self._assistant("old")
        with mock.patch("jarvis.assistant.sites.handle", return_value=None), \
                mock.patch("jarvis.assistant.abilities.handle", return_value="Opened Downloads."):
            self.assertEqual(a._handle("open downloads"), ("ability", "Opened Downloads."))
        a.newbrain.handle.assert_not_called()
