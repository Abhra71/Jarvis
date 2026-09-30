"""1 Oct bug hunt: when the first AI fails partway through a request, the backup carries on; it doesn't redo it."""

import unittest
from unittest import mock

from jarvis import brain


class MidwayFallbackTest(unittest.TestCase):
    def test_backup_is_told_what_was_done(self):
        b = brain.Brain.__new__(brain.Brain)
        b.turn_calls, b.on_backup, b.groq, b.key, b.cfg = [], False, object(), "k", {}
        b._chain = lambda: ["groq", "gemini"]
        seen = {}

        def groq(text):
            b.turn_calls.append(("open_app", {"name": "Notepad"}, "Opening Notepad."))
            raise brain.BrainUnavailable("both AI services failed")

        def gemini(text, handoff=None):
            seen["text"] = text
            return "Typed it."

        b._ask_groq, b._ask_gemini = groq, gemini
        with mock.patch.object(brain, "popup"), mock.patch.object(brain.usage, "set_activity"):
            self.assertEqual(b._ask_any("open notepad and type hello"), "Typed it.")
        self.assertIn("Already done for this request", seen["text"])
        self.assertIn("open_app(name='Notepad')", seen["text"])

    def test_no_note_when_nothing_was_done(self):
        b = brain.Brain.__new__(brain.Brain)
        b.turn_calls, b.on_backup, b.groq, b.key, b.cfg = [], False, object(), "k", {}
        b._chain = lambda: ["groq", "gemini"]
        seen = {}
        b._ask_groq = mock.Mock(side_effect=brain.BrainUnavailable("limit"))
        b._ask_gemini = lambda text, handoff=None: seen.setdefault("text", text) and "ok"
        with mock.patch.object(brain, "popup"), mock.patch.object(brain.usage, "set_activity"):
            b._ask_any("what time is it")
        self.assertEqual(seen["text"], "what time is it")


if __name__ == "__main__":
    unittest.main()
