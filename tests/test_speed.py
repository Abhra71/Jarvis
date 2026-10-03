"""Block 3 (speed, 3 Oct): faster paths, checked without the screen."""

import unittest
from unittest import mock

from jarvis.skills.sites import pw


class PwSubjectFastTest(unittest.TestCase):
    """PW 'my batch, chemistry' took ~7 s (two pages clicked through). A subject opened once is remembered."""

    PLACE = {"subject:chemistry": {"url": "https://pw.live/study-v2/batches/b/subjects/chem?x=1",
                                   "name": "Chemistry by Sunil Sir", "other": "Chemistry by Sanya"}}

    def test_straight_to_the_remembered_page(self):
        with mock.patch.object(pw, "_places", return_value=self.PLACE), \
                mock.patch.object(pw, "_on_pw", return_value=True), \
                mock.patch.object(pw.desktop, "address_bar") as go, \
                mock.patch.object(pw.desktop, "current_url",
                                  return_value="https://pw.live/study-v2/batches/b/subjects/chem?y=2"), \
                mock.patch.object(pw, "_clear_notices"):
            self.assertEqual(pw.open_subject("chemistry"),
                             "Opened Chemistry by Sunil Sir. There's also Chemistry by Sanya.")
        go.assert_called_once_with(self.PLACE["subject:chemistry"]["url"])

    def test_the_long_way_when_it_didnt_open(self):
        with mock.patch.object(pw, "_places", return_value=self.PLACE), \
                mock.patch.object(pw, "_on_pw", return_value=True), \
                mock.patch.object(pw.desktop, "address_bar"), \
                mock.patch.object(pw.desktop, "current_url", return_value="https://pw.live/login"), \
                mock.patch.object(pw, "_wait", return_value=False), \
                mock.patch.object(pw, "_form_in_way", return_value=""), \
                mock.patch.object(pw, "_all_classes", return_value="Not done: All Classes didn't open.") as slow:
            self.assertEqual(pw.open_subject("chemistry"), "Not done: All Classes didn't open.")
        slow.assert_called_once()

    def test_nothing_remembered_goes_the_long_way(self):
        with mock.patch.object(pw, "_places", return_value={}), \
                mock.patch.object(pw, "_all_classes", return_value="Not done: x") as slow:
            pw.open_subject("physics")
        slow.assert_called_once()


class KhazanaFastTest(unittest.TestCase):
    def test_a_course_opened_before_opens_straight_away(self):
        place = {"khazana:chemistry:": {"url": "https://pw.live/x/khazana-topics/1", "name": "Chemistry 2026"}}
        with mock.patch.object(pw, "_places", return_value=place), \
                mock.patch.object(pw, "_on_pw", return_value=True), \
                mock.patch.object(pw.desktop, "address_bar") as go, \
                mock.patch.object(pw.desktop, "current_url", return_value="https://pw.live/x/khazana-topics/1"), \
                mock.patch.object(pw, "_clear_notices"), \
                mock.patch.object(pw, "_khazana_home") as home:
            self.assertEqual(pw.open_khazana("open khazana chemistry"), "Opened Khazana Chemistry 2026.")
        go.assert_called_once_with("https://pw.live/x/khazana-topics/1")
        home.assert_not_called()


class CloseThisAppTest(unittest.TestCase):
    """3 Oct speed pass: 'close this' with an app in front went to the AI (2-3 s)."""

    def test_an_app_window_is_closed_in_code(self):
        from jarvis.agent import plan as planmod
        p = planmod.code_plan("Close this.", "explorer: Downloads - File Explorer")
        self.assertEqual(p.steps[0].tool, "window")
        self.assertEqual(p.steps[0].args, {"app": "Downloads - File Explorer", "action": "close"})
        self.assertIsNotNone(p.steps[0].check)

    def test_editors_and_terminals_are_left_to_the_ai(self):
        from jarvis.agent import plan as planmod
        for front in ("code: main.cpp - Visual Studio Code", "notepad: notes.txt - Notepad", "claude: Claude"):
            with self.subTest(front=front):
                self.assertIsNone(planmod.code_plan("Close this.", front))
        self.assertIsNone(planmod.code_plan("Close this tab.", "explorer: Downloads - File Explorer"))


if __name__ == "__main__":
    unittest.main()
