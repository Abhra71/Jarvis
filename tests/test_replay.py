"""Real sentences from the user's sessions, and what Jarvis must do with them (from tools/replay.py, 1 Oct).
Each one was handled wrongly at least once."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import replay  # noqa: E402
from jarvis.agent import plan as planmod  # noqa: E402
from jarvis.skills import apps  # noqa: E402


def _apps():
    with mock.patch.object(apps, "_scan_start_apps", return_value={
            "claude": r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude", "google chrome": "chrome.lnk",
            "file explorer": "explorer.lnk", "visual studio code": "code.lnk", "whatsapp": "wa.lnk"}):
        return apps.AppLauncher({"chrome": "chrome", "cloud": r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude",
                                 "vs code": "code", "bluej": "bluej.exe"})


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.apps = _apps()
        patcher = mock.patch.object(replay.abilities, "memory", mock.Mock(get=lambda text: None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def route(self, said, unsure=False):
        return replay.route(said, unsure, self.apps)

    def test_routes(self):
        cases = [
            ("Open File Explorer.", "rules"),                      # was: open a VS Code file called "explorer"
            ("Open the file with size 37,272 kilobytes.", "ability", "open_file_here"),
            ("I want you to open YouTube in Brave's browser, Mute in Chrome.", "AI"),  # was: only muted
            ("Open Physics Voila.", "ability", "pw_batch"),
            ("Open Kazana.", "ability", "pw_khazana"),
            ("Open d football.", "ability", "start_game"),
            ("Open downloads.", "ability", "open_folder"),
            ("Maximize Claude.", "code plan", "maximize_front"),
            ("Open chess. com.", "rules", "chess.com"),
            ("Open Flipkart.", "rules", "flipkart.com"),
            ("Tmf, E. I. P, M1, Tmf, E. I. P. S, P, Mp, P. W, W,a, G,T, C, O,V,P, X,Y,O", "ignored"),
            ("It's not cloud. It's C-L-A-U-D-E.", "AI"),           # a spelling is speech, not noise
            ("Coding mode on.", "mode"),
            ("Stop.", "stop"),
        ]
        for said, want, *detail in cases:
            got, why = self.route(said)
            self.assertEqual(got, want, f"{said!r} -> {got} {why}")
            if detail:
                self.assertIn(detail[0], why, said)

    def test_clawed_asks_for_claude(self):
        got, why = self.route("Open Clawed.")
        self.assertIn("did you mean claude", why)

    def test_close_this_in_a_browser_is_the_tab(self):
        p = planmod.code_plan("Close this.", "chrome: Chess.com - Google Chrome")
        self.assertEqual([s.label() for s in p.steps], ["browser(action='close_tab')"])
        self.assertIsNone(planmod.code_plan("Close this.", "notepad: a.txt - Notepad"))


if __name__ == "__main__":
    unittest.main()
