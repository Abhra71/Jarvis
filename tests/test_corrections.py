"""'No, I meant Claude.' fixes the last request and is remembered (Phase 5)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import corrections


class ParseTest(unittest.TestCase):
    def test_meant(self):
        for said, word in [("No, I meant Claude.", "Claude"), ("no I said Claude app", "Claude"),
                           ("I meant the Claude app", "Claude"), ("No, it's Claude, not clawed.", "Claude"),
                           ("Not clawed, Claude.", "Claude")]:
            self.assertEqual(corrections.meant(said), word, said)
        for said in ("No.", "Open Claude.", "no I meant open chrome in my main profile and then play a song"):
            self.assertIsNone(corrections.meant(said), said)

    def test_only_sound_alike_words_are_mishearings(self):
        c = corrections.Corrections(None)
        self.assertEqual(c.fix("Open Clawed.", "No, I meant Claude."), ("Open Claude.", "Clawed"))
        self.assertEqual(c.fix("Open Physics Voila.", "no I meant physics wallah"),
                         ("Open physics wallah.", "Physics Voila"))
        self.assertIsNone(c.fix("Open Edge.", "No, I meant Chrome."))  # a change of mind, not a mishearing
        self.assertIsNone(c.fix("Open Claude.", "no I meant Claude"))  # heard right the first time


class LearnTest(unittest.TestCase):
    def test_learned_pairs_fix_what_is_heard_and_can_be_forgotten(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "corrections.json"
            c = corrections.Corrections(path)
            c.learn("Clawed", "Claude")
            again = corrections.Corrections(path)  # kept on disk
            self.assertEqual(again.apply("Open Clawed."), "Open Claude.")
            self.assertEqual(again.apply("Open the clawed app"), "Open the Claude app")
            self.assertEqual(again.words(), ["Claude"])
            self.assertEqual(c.forget_last(), "clawed means Claude")
            self.assertEqual(c.apply("Open Clawed."), "Open Clawed.")


class AssistantTest(unittest.TestCase):
    def _assistant(self):
        from jarvis import assistant
        a = assistant.Assistant.__new__(assistant.Assistant)
        a.dictating, a.coding, a.gaming, a.last_code = False, False, False, ""
        a.corrections = corrections.Corrections(None)
        a.last_request, a.fixed_request = "Open Clawed.", None
        a.skills = mock.Mock()
        a.brain = mock.Mock(answer_agent=mock.Mock(return_value=None), agent=None)
        return a

    def test_correction_redoes_the_request_and_learns(self):
        a = self._assistant()
        with mock.patch("jarvis.assistant.sites.handle", return_value=None), \
                mock.patch("jarvis.assistant.abilities.handle",
                           side_effect=lambda text, unsure=False: "Opening Claude." if text == "Open Claude." else None):
            route, reply = a._handle("No, I meant Claude.")
        self.assertEqual((route, reply), ("ability", "Opening Claude."))
        self.assertEqual(a.corrections.pairs, {"clawed": "Claude"})
        self.assertEqual(a.fixed_request, "Open Claude.")

    def test_forget_that(self):
        a = self._assistant()
        a.corrections.learn("Clawed", "Claude")
        self.assertEqual(a._handle("Forget that.")[1], "Okay, I've forgotten that clawed means Claude.")
        self.assertEqual(a.corrections.pairs, {})


if __name__ == "__main__":
    unittest.main()
