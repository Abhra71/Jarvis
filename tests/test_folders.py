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
        with mock.patch.object(fab.files, "open_path", return_value="Opened Downloads.") as op:
            self.assertEqual(fab.open_folder("download"), "Opened Downloads.")
        op.assert_called_once_with("downloads")

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
