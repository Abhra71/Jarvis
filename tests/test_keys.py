"""Keyboard control: any shortcut, safely; everyday shortcuts offline; long text pasted."""

import unittest
from unittest import mock

from jarvis import nlu
from jarvis.skills import keys


class ComboTest(unittest.TestCase):
    def test_combos(self):
        cases = {
            "ctrl+enter": ["^{ENTER}"],                  # 26 Sep: Ctrl+Enter wasn't possible
            "Ctrl + Shift + T": ["^+t"],
            "alt+tab": ["%{TAB}"],
            "win+d": ["{VK_LWIN down}d{VK_LWIN up}"],
            "ctrl+k ctrl+s": ["^k", "^s"],              # VS Code chord
            "ctrl++": ["^{+}"],
            "f5": ["{F5}"],
            "select_all": ["^a"],                       # the old key names still work
        }
        for combo, want in cases.items():
            self.assertEqual(keys.parse(combo), want, combo)
        for bad in ("ctrl+banana", "", "a+b"):
            with self.assertRaises(keys.BadKeys):
                keys.parse(bad)

    def test_safety(self):
        self.assertIn("never", keys.check("shift+delete", "chrome: x")[0])
        self.assertIn("deleting is turned off", keys.check("delete", "explorer: Downloads")[0])
        self.assertEqual(keys.check("delete", "code: notes.txt"), (None, None))  # deleting text is fine
        self.assertIn("sends the message", keys.check("ctrl+enter", "whatsapp: Mom")[1])
        self.assertIn("lock", keys.check("win+l", "")[1])

    def test_tool_refuses_and_explains(self):
        from jarvis.skills import Skills
        with mock.patch("jarvis.skills.AppLauncher"), mock.patch("jarvis.skills.Browser"):
            s = Skills({"volume": {"step": 10}, "apps": {}}, announce=print)
        with mock.patch("jarvis.skills.desktop.front_window", return_value="explorer: Downloads"), \
                mock.patch.object(keys.keyboard, "send_keys") as send:
            self.assertTrue(s.call("press_key", {"key": "shift+delete"}).startswith("Not allowed"))
            self.assertIn("Examples", s.call("press_key", {"key": "ctrl+banana"}))
            self.assertEqual(s.call("press_key", {"key": "ctrl+shift+n"}), "Pressed ctrl+shift+n.")
        send.assert_called_once_with("^+n", with_spaces=True, vk_packet=False)  # real key presses (30 Sep)


class OfflineShortcutTest(unittest.TestCase):
    def test_everyday_phrases_are_one_key_press(self):
        cases = {
            "Open a new tab.": "ctrl+t", "close this tab": "ctrl+w", "reopen the last closed tab": "ctrl+shift+t",
            "go back": "alt+left", "copy that": "ctrl+c", "paste it": "ctrl+v", "undo": "ctrl+z",
            "select all": "ctrl+a", "save the file": "ctrl+s", "switch window": "alt+tab",
            "show desktop": "win+d", "take a screenshot": "win+shift+s",
            "press control shift t": "ctrl+shift+t", "press enter": "enter", "press alt f4": "alt+f4",
            "use the shortcut control k control s": "ctrl+k ctrl+s", "hit the escape key": "esc",
        }
        for said, combo in cases.items():
            intent = nlu.parse(said)
            self.assertEqual((intent.name, intent.slots["keys"]), ("shortcut", combo), said)
        for not_a_shortcut in ("open notepad", "go back 10 seconds", "copy the file to downloads"):
            intent = nlu.parse(not_a_shortcut)
            self.assertFalse(intent and intent.name == "shortcut", not_a_shortcut)


class PasteTest(unittest.TestCase):
    def test_long_text_is_pasted_short_text_typed(self):
        from jarvis.skills import desktop
        with mock.patch.object(desktop, "_paste", return_value=True) as paste, \
                mock.patch.object(desktop.keyboard, "send_keys") as send:
            desktop.type_text("hi there")
            paste.assert_not_called()
            desktop.type_text("# For now, no backups: only Gemini and Groq are used.")
            paste.assert_called_once()
        self.assertEqual(send.call_count, 1)  # only the short one was typed key by key


if __name__ == "__main__":
    unittest.main()
