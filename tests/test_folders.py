"""'Open downloads' is instant (1 Oct speed report: it went to the AI, 2 calls, 6 s)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import abilities
from jarvis.abilities import files as fab


class OpenFolderTest(unittest.TestCase):
    def test_phrases(self):
        for said, value in [("open downloads", "downloads"), ("open my downloads folder", "downloads"),
                            ("go to documents", "documents"), ("open desktop", "desktop"),
                            ("show my pictures folder", "pictures"), ("open screenshots", "screenshots")]:
            hit = abilities.match(said)
            self.assertEqual((hit[0].name, hit[1]), ("open_folder", value), said)
        self.assertIsNone(abilities.match("show me my desktop"))  # that's "minimise everything", not a folder
        self.assertEqual(abilities.match("open the downloads and find the newest pdf")[0].name, "find_newest")

    def test_opens_the_folder(self):
        with mock.patch.object(fab.files, "open_path", return_value="Opened Downloads.") as op,                 mock.patch.object(fab.files, "resolve", return_value=Path("C:/Users/x/Downloads")),                 mock.patch.object(fab.desktop, "_app_windows", return_value=[(7, "explorer.exe", "Downloads - File Explorer")]),                 mock.patch.object(fab.desktop, "front_hwnd", return_value=9),                 mock.patch.object(fab.desktop, "_focus") as focus:
            self.assertEqual(fab.open_folder("download"), "Opened Downloads.")
        op.assert_called_once_with("downloads")
        focus.assert_called_once_with(7)  # 3 Oct: it opened behind Chrome
        self.assertEqual(fab.desktop.just_opened[:2], (7, "the Downloads folder"))
        fab.desktop.just_opened = None


class CloseItTest(unittest.TestCase):
    """3 Oct reliability run: 'Open downloads.' 'Close it.' closed a Physics Wallah tab (the AI's guess)."""

    def _assistant(self):
        from jarvis import assistant, corrections
        a = assistant.Assistant.__new__(assistant.Assistant)
        a.dictating, a.coding, a.gaming = False, False, False
        a.corrections = corrections.Corrections(None)
        a.last_request, a.fixed_request = "Open downloads", None
        a.skills = mock.Mock()
        a.brain = mock.Mock(answer_agent=mock.Mock(return_value=None), agent=None)
        return a, assistant

    def test_close_it_closes_what_was_just_opened(self):
        a, assistant = self._assistant()
        with mock.patch.object(assistant.desktop, "just_opened", (7, "the Downloads folder", 0.0)),                 mock.patch.object(assistant.desktop, "close_just_opened", return_value="Closed the Downloads folder."):
            self.assertEqual(a._handle("Close it."), ("offline rules", "Closed the Downloads folder."))
        a.brain.ask.assert_not_called()

    def test_only_the_very_next_request(self):
        a, assistant = self._assistant()
        assistant.desktop.just_opened = (7, "the Downloads folder", 0.0)
        with mock.patch.object(a, "_handle", return_value=("offline rules", "Volume 30.")),                 mock.patch.object(assistant.tasklog, "write"), mock.patch.object(assistant.usage, "begin_turn"),                 mock.patch.object(assistant.usage, "end_turn"):
            a.handle_text("volume 30")
        self.assertIsNone(assistant.desktop.just_opened)

    def test_screenshots_folder_may_be_numbered(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Screenshots 1").mkdir()
            (Path(d) / "Saved Pictures").mkdir()
            with mock.patch.object(fab.files, "resolve", return_value=Path(d)):
                self.assertEqual(fab._screenshots(), "pictures/Screenshots 1")
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(fab.files, "resolve", return_value=Path(d)):
                self.assertEqual(fab._screenshots(), "pictures")


if __name__ == "__main__":
    unittest.main()
