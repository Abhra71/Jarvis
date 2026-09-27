"""Jarvis 4 layer 1: the ability catalog and phrase memory. Keys and Settings are faked."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import abilities


class MatchTest(unittest.TestCase):
    def _hit(self, said):
        hit = abilities.match(said)
        return (hit[0].name, hit[1]) if hit else None

    def test_phrases(self):
        cases = {
            "snap this window to the left": ("snap_left", None),
            "Hey Jarvis, snap it right": None,  # "it" isn't in the phrases: the AI gets it, then it's learned
            "snap right": ("snap_right", None),
            "maximize": ("maximize_front", None),
            "move this window to the other screen": ("other_screen", None),
            "new desktop": ("new_desktop", None),
            "next desktop": ("next_desktop", None),
            "open bluetooth settings": ("open_settings", "bluetooth"),
            "open the wi-fi settings": ("open_settings", "wi fi"),
            "open settings": ("open_settings", None),
            "maximize the brave screen": None,  # names an app: the window tool (AI) handles it
            "open notepad": None,
        }
        for said, want in cases.items():
            self.assertEqual(self._hit(said), want, said)

    def test_running_uses_windows_shortcuts_and_uris(self):
        with mock.patch.object(abilities.windows.keys, "press") as press:
            self.assertEqual(abilities.handle("snap left"), "Snapped left.")
        press.assert_called_once_with("win+left")
        with mock.patch.object(abilities.windows.os, "startfile") as start:
            self.assertEqual(abilities.handle("open night light settings"), "Opened night light settings.")
            start.assert_called_once_with("ms-settings:nightlight")
        with mock.patch.object(abilities.windows.os, "startfile"):
            self.assertIn("no Settings page", abilities.run("open_settings", "banana"))

    def test_catalog_for_the_ai_is_short(self):
        self.assertLess(len(abilities.catalog_text()), 200)
        self.assertIn("snap_left", abilities.declaration()["parameters"]["properties"]["ability"]["enum"])


class PhraseMemoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.mem = abilities.PhraseMemory(Path(self.dir.name) / "learned.json")
        patcher = mock.patch.object(abilities, "memory", self.mem)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.dir.cleanup)

    def test_learned_phrases_are_instant_next_time(self):
        self.assertIsNone(abilities.handle("put this on the left side"))
        self.mem.learn("put this on the left side", "snap_left", None)
        with mock.patch.object(abilities.windows.keys, "press") as press:
            self.assertEqual(abilities.handle("Put this on the left side."), "Snapped left.")
        press.assert_called_once_with("win+left")
        # it survives a restart
        again = abilities.PhraseMemory(self.mem.path)
        self.assertEqual(again.get("put this on the left side"), ("snap_left", None))

    def test_not_learned_when_unsure_unsafe_or_long(self):
        self.mem.learn("x " * 20, "snap_left", None)
        self.mem.learn("do the thing", "no_such_ability", None)
        self.assertEqual(self.mem.phrases, {})
        self.mem.learn("left side please", "snap_left", None)
        self.assertIsNone(abilities.handle("left side please", unsure=True))  # shaky speech: not trusted

    def test_brain_learns_from_a_single_ability_call(self):
        from jarvis import brain
        b = brain.Brain.__new__(brain.Brain)
        b.turn_calls = [("do", {"ability": "snap_right"}, "Snapped right.")]
        b._learn("throw this to the right", unsure=False)
        self.assertEqual(self.mem.get("throw this to the right"), ("snap_right", None))
        b.turn_calls = [("do", {"ability": "snap_right"}, "Snapped right."), ("click", {}, "Clicked.")]
        b._learn("do two things", unsure=False)
        self.assertIsNone(self.mem.get("do two things"))


if __name__ == "__main__":
    unittest.main()
