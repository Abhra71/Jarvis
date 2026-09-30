"""Jarvis 4 layer 1: the ability catalog and phrase memory. Keys and Settings are faked."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import abilities


def fake_window():
    """A pretend front window that really moves when Win+Left/Right is pressed (never the real screen)."""
    w = abilities.windows
    state = {"rect": (100, 100, 900, 700)}

    def press(combo):
        if combo == "win+left":
            state["rect"] = (0, 0, 960, 1020)
        elif combo == "win+right":
            state["rect"] = (960, 0, 1920, 1020)

    press_mock = mock.Mock(side_effect=press)
    patches = [mock.patch.object(w.keys, "press", press_mock), mock.patch.object(w, "_front", return_value=1),
               mock.patch.object(w, "_rect", side_effect=lambda h: state["rect"]),
               mock.patch.object(w, "_work_area", return_value=(0, 0, 1920, 1020)),
               mock.patch.object(w.elements, "is_fullscreen", return_value=False),
               mock.patch.object(w.desktop, "_app_windows", return_value=[]),
               mock.patch.object(w.time, "sleep")]
    return patches, press_mock


class _FakeWindow:
    def __enter__(self):
        self.patches, press = fake_window()
        for p in self.patches:
            p.start()
        return press

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


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
        with _FakeWindow() as press:
            self.assertEqual(abilities.handle("snap left"), "Snapped left.")
        press.assert_called_once_with("win+left")
        with mock.patch.object(abilities.windows.os, "startfile") as start:
            self.assertEqual(abilities.handle("open night light settings"), "Opened night light settings.")
            start.assert_called_once_with("ms-settings:nightlight")
        with mock.patch.object(abilities.windows.os, "startfile"):
            self.assertIn("no Settings page", abilities.run("open_settings", "banana"))

    def test_snapping_is_checked(self):
        with _FakeWindow() as press:
            press.side_effect = None  # the window doesn't move (30 Sep: a full-screen video ignored the snap)
            self.assertEqual(abilities.run("snap_right"), "Not done: the window didn't move to the right half.")

    def test_newest_file_of_a_kind(self):
        import os
        from jarvis.abilities import files as af
        with tempfile.TemporaryDirectory() as d:
            for i, name in enumerate(["old.pdf", "new.pdf", "newer.png", "half.pdf.crdownload"]):
                (Path(d) / name).write_text("x")
                os.utime(Path(d) / name, (1000 + i, 1000 + i))
            with mock.patch.object(af.files, "resolve", return_value=Path(d)), \
                    mock.patch.object(af.files, "show_in_explorer") as show, \
                    mock.patch.object(af, "_wait_for_explorer", return_value=True):
                reply = abilities.handle("Open my Downloads and find the newest PDF")
                self.assertTrue(reply.startswith("The newest PDF in Downloads is new, from"), reply)
                self.assertTrue(reply.endswith("selected in File Explorer."))
                show.assert_called_once_with(str(Path(d) / "new.pdf"))
                self.assertIn("newer", abilities.handle("where is my latest download"))
                self.assertEqual(abilities.handle("find the newest video"), "There's no video in Downloads.")

    def test_catalog_for_the_ai_is_short(self):
        self.assertLess(len(abilities.catalog_text()), 380)  # ~20 chars per ability with a value (30 Sep: 11 of them)
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
        with _FakeWindow() as press:
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


class SystemSwitchesTest(unittest.TestCase):
    """30 Sep: Quick Settings switches, brightness and Bluetooth devices by voice."""

    def test_switch_phrases(self):
        from jarvis.abilities.system import _parse_switch
        cases = {"turn on night light": ("night light", True), "night light off": ("night light", False),
                 "turn off the bluetooth": ("bluetooth", False), "disable wi fi": ("wifi", False),
                 "switch bluetooth on": ("bluetooth", True), "turn on airplane mode": ("airplane mode", True)}
        for said, want in cases.items():
            ab, value = abilities.match(said)
            self.assertEqual(ab.name, "switch_setting", said)
            self.assertEqual(_parse_switch(value), want, said)
        self.assertIsNone(abilities.match("turn on the tv"))

    def test_brightness_phrases(self):
        for said, want in {"brightness 40": "40", "set brightness to 70 percent": "70", "brightness up": "up",
                           "dim the screen": "dim", "make the screen brighter": "brighter"}.items():
            self.assertEqual(abilities.match(said)[0].name, "set_brightness", said)
            self.assertEqual(abilities.match(said)[1], want, said)

    def test_brightness_steps_and_limits(self):
        from jarvis.abilities import system
        with mock.patch.object(system.quick, "brightness", return_value=46), \
                mock.patch.object(system.quick, "set_brightness", side_effect=lambda v: v) as setb:
            self.assertEqual(system.set_brightness("down"), 36)
            self.assertEqual(system.set_brightness("min"), 5)  # never a black screen
            self.assertEqual(system.set_brightness("max"), 100)

    def test_connect_phrases_never_mean_wifi(self):
        self.assertEqual(abilities.match("connect my rockerz headphones")[1], "rockerz")
        self.assertIsNone(abilities.match("connect to wifi"))
        self.assertIsNone(abilities.match("connect to the internet"))

    def test_a_device_is_never_guessed(self):
        from jarvis.skills.quick import _pick
        devs = [("Rockerz 480", "Rockerz 480, State Not connected", None)]
        self.assertEqual(_pick(devs, "headphones")[0], "Rockerz 480")  # the only one, called generically
        self.assertEqual(_pick(devs, "rockers")[0], "Rockerz 480")
        self.assertIsNone(_pick(devs, "jbl speaker"))


class UploadTest(unittest.TestCase):
    """30 Sep: 'upload my newest pdf' / 'upload the file called marksheet' pick the file in code, never a guess."""

    def test_phrases(self):
        self.assertEqual(abilities.match("upload my newest pdf")[0].name, "upload_file")
        self.assertEqual(abilities.match("attach the file called marksheet")[1], "marksheet")
        for said in ("select all", "choose file", "pick a color"):
            m = abilities.match(said)
            self.assertFalse(m and m[0].name == "upload_file", said)

    def test_finds_by_name_and_newest_never_guesses_or_picks_secrets(self):
        import tempfile
        from pathlib import Path
        from jarvis.abilities import upload
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "Class_10_Marksheet.pdf").write_text("x")
            (folder / "notes.txt").write_text("x")
            (folder / ".env").write_text("KEY=1")
            with mock.patch.object(upload.files, "resolve", side_effect=lambda f: folder):
                self.assertEqual(upload.find_file("marksheet", ("X",))[0].name, "Class_10_Marksheet.pdf")
                self.assertIsNone(upload.find_file("resume", ("X",))[0])
                self.assertIsNone(upload.find_file("env", ("X",))[0])
