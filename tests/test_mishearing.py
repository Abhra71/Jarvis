"""The 30 Sep session: "Open Claude" heard as "Open Clawed" / "Open CloudF", and noise heard as letters."""

import tempfile
import unittest
from unittest import mock

from jarvis.agent import checks
from jarvis.skills import apps
from jarvis.stt import clean_transcript
from test_agent import FakeDesktop, _agent


def _launcher():
    with mock.patch.object(apps, "_scan_start_apps", return_value={
            "claude": r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude", "google chrome": "chrome.lnk",
            "clock": "clock.lnk", "notepad": "notepad.exe"}):
        return apps.AppLauncher({"cloud": r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"})


class SoundsLikeTest(unittest.TestCase):
    def test_misheard_names_suggest_the_real_app(self):
        a = _launcher()
        self.assertEqual(apps.sound_key("Clawed"), apps.sound_key("Claude"))
        self.assertEqual(a.suggest("clawed"), "claude")
        self.assertEqual(a.suggest("cloudf"), "claude")
        self.assertIsNone(a.suggest("steam"))      # nothing sounds like it: no guess
        self.assertIsNone(a.suggest("x"))

    def test_open_asks_did_you_mean(self):
        a = _launcher()
        with mock.patch.object(apps, "_allow_foreground"):
            self.assertEqual(a.open("Clawed"), "Not done: there's no app called Clawed. Did you mean Claude?")

    def test_store_app_alias_is_called_by_its_real_name(self):
        a = _launcher()
        with mock.patch.object(apps, "_allow_foreground"), mock.patch.object(apps.subprocess, "Popen"):
            self.assertEqual(a.open("cloud"), "Opening Claude.")


class LetterSoupTest(unittest.TestCase):
    def test_letters_are_noise(self):
        self.assertEqual(clean_transcript("Tmf, E. I. P, M1, Tmf, E. I. P. S, P, Mp, P. W, W,a, G,T, C, O,V,P"), "")

    def test_real_speech_with_short_words_stays(self):
        for said in ("Set a timer for 5 minutes.", "Go to line 12 and comment it.", "Open VS Code in C drive",
                     "Move the pawn from e2 to e4."):
            self.assertEqual(clean_transcript(said), said)


class AgentMishearingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_did_you_mean_asks_and_yes_opens_the_real_app(self):
        desk = FakeDesktop()

        def open_app(args):
            if args["name"] == "Clawed":
                return "Not done: there's no app called Clawed. Did you mean Claude?"
            desk.open("Claude")
            return "Opening Claude."

        desk.effects["open_app"] = open_app
        plan = {"steps": [{"do": "open_app", "args": {"name": "Clawed"}, "expect": "window: Clawed"}],
                "reply": "Opened Clawed."}
        agent, think = _agent(desk, [plan], self.tmp.name)
        self.assertEqual(agent.run("open clawed"), "I couldn't find Clawed. Did you mean Claude?")
        self.assertEqual(think.call_count, 1)  # no repair improvising a web search
        self.assertTrue(agent.has_pending())
        reply = agent.resume()
        self.assertEqual(desk.calls[-1], ("open_app", {"name": "Claude"}))
        self.assertEqual(agent.last.result, "done", reply)

    def test_open_is_checked_for_the_app_that_really_opened(self):
        desk = FakeDesktop()

        def open_app(args):
            desk.open("Claude")
            return "Opening Claude."

        desk.effects["open_app"] = open_app
        plan = {"steps": [{"do": "open_app", "args": {"name": "CloudF"}, "expect": "window: CloudF"}],
                "reply": "Opened it."}
        agent, _ = _agent(desk, [plan], self.tmp.name)
        agent.run("open cloudf in desktop")
        self.assertEqual(agent.last.result, "done")

    def test_a_guessed_site_after_a_search_is_not_a_check(self):
        c = checks.auto_check("web_search", {"query": "clawed"}, checks.Check("url", "www.clawedgame.com"), None)
        self.assertIsNone(c)
        c = checks.auto_check("web_search", {"query": "x"}, checks.Check("url", "google.com/search"), None)
        self.assertIsNotNone(c)


if __name__ == "__main__":
    unittest.main()
