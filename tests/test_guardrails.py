"""v3 Phase 1: guardrails against unasked actions, bad tool args and leaked labels."""

import unittest
from unittest import mock

import jarvis.usage


def setUpModule():
    jarvis.usage.usage.persist = False


def _skills():
    from jarvis.skills import Skills
    with mock.patch("jarvis.skills.AppLauncher"), mock.patch("jarvis.skills.Browser"):
        return Skills({"volume": {"step": 10}, "apps": {}}, announce=print)


class ActionBudgetTest(unittest.TestCase):
    def test_budget_matches_what_was_asked(self):
        from jarvis.skills import action_budget
        cases = {
            "click No thanks": 1,
            "move pawn e2 to e4": 1,
            "e4": 1,
            "knight takes on d5": 1,
            "Hey Jarvis, can you press the play button": 1,
            "type hello world": 2,
            "click the first video and then press full screen": 2,
            "click every checkbox": 3,
            "sign me up for the newsletter": 3,
            "": 1,
        }
        for text, want in cases.items():
            self.assertEqual(action_budget(text), want, text)

    def test_extra_moves_are_blocked_in_code(self):
        # 26 Sep: asked for one chess move, Jarvis played two.
        s = _skills()
        s.budget = 1
        with mock.patch("jarvis.skills.mouse.click_pair", return_value="Moved.") as pair, \
                mock.patch("jarvis.skills.desktop.screenshot_jpeg", return_value=b"jpg"), \
                mock.patch("jarvis.skills.desktop.front_window", return_value="chrome: chess"):
            s.call("look_at_screen", {})
            move = {"x": 100, "y": 800, "x2": 100, "y2": 600, "target": "pawn e2 to e4"}
            self.assertEqual(s.call("click_pair", move), "Moved.")
            s.call("look_at_screen", {})
            self.assertTrue(s.call("click_pair", {**move, "target": "pawn d2 to d4"}).startswith("Not done"))
        self.assertEqual(pair.call_count, 1)

    def test_looking_and_opening_are_not_counted(self):
        s = _skills()
        s.budget = 0
        with mock.patch("jarvis.skills.desktop.screenshot_jpeg", return_value=b"jpg"), \
                mock.patch("jarvis.skills.desktop.front_window", return_value=""):
            self.assertIsInstance(s.call("look_at_screen", {}), dict)
            s.browser.open.return_value = "Opened."
            self.assertEqual(s.call("open_website", {"url": "https://x.com"}), "Opened.")

    def test_brain_sets_and_clears_the_budget(self):
        from jarvis import brain
        skills = mock.Mock()
        skills.declarations.return_value = []
        skills.browser.profile_summary.return_value = ""
        with mock.patch.object(brain, "load_api_key", return_value=None):
            b = brain.Brain({}, skills)
        seen = {}
        b._ask_any = lambda text: seen.setdefault("budget", skills.budget) and "ok"
        b.groq = mock.Mock()
        b.ask("click No thanks")
        self.assertEqual(seen["budget"], 1)
        self.assertIsNone(skills.budget)


class ArgCheckTest(unittest.TestCase):
    def test_missing_arg_is_reported_not_crashed(self):
        # 26 Sep: click_pair without y2 crashed a chess move.
        s = _skills()
        s.screen_fresh = True
        with mock.patch("jarvis.skills.mouse.click_pair") as pair, \
                mock.patch("jarvis.skills.desktop.front_window", return_value=""):
            r = s.call("click_pair", {"x": 1, "y": 2, "x2": 3, "target": "pawn"})
        self.assertIn("missing y2", r)
        self.assertIn("required: x, y, x2, y2, target", r)
        pair.assert_not_called()
        self.assertTrue(s.screen_fresh)  # nothing happened, so the last look is still good

    def test_args_are_tidied(self):
        s = _skills()
        s.screen_fresh = True
        with mock.patch("jarvis.skills.mouse.click", return_value="Clicked.") as click, \
                mock.patch("jarvis.skills.desktop.front_window", return_value=""):
            s.call("click", {"x": "400", "y": 250.6, "target": "video", "button": "LEFT", "reason": "extra"})
        click.assert_called_once_with(400, 251, "left", False)

    def test_bad_values_are_explained(self):
        s = _skills()
        s.screen_fresh = True
        with mock.patch("jarvis.skills.desktop.front_window", return_value=""):
            self.assertIn("off screen", s.call("click", {"x": 1500, "y": 10, "target": "a"}))
            self.assertIn("must be a number", s.call("click", {"x": "left", "y": 10, "target": "a"}))
            self.assertIn("must be one of", s.call("volume", {"action": "louder"}))


class CleanTest(unittest.TestCase):
    def test_leaked_thought_labels_are_removed(self):
        from jarvis.brain import _clean
        self.assertEqual(_clean("atthought\n I don't see an auto-play mode."), "I don't see an auto-play mode.")
        self.assertEqual(_clean("thought\nDone."), "Done.")
        self.assertEqual(_clean("Thought: Done."), "Done.")
        self.assertEqual(_clean("thought"), "")
        self.assertEqual(_clean("I thought so too."), "I thought so too.")
        self.assertEqual(_clean("Thoughtful choice."), "Thoughtful choice.")

    def test_check_after_click_does_not_invite_more_steps(self):
        import inspect
        from jarvis import brain
        src = inspect.getsource(brain.Brain._ask_gemini)
        self.assertNotIn("carry on", src.split("This is the screen now")[1].split("inlineData")[0])


class SpokenAddressTest(unittest.TestCase):
    def test_spoken_addresses_open_the_site(self):
        from jarvis import nlu
        from jarvis.skills import site_url
        for said in ("open chess dot com", "Open chess.com.", "open chess com"):
            intent = nlu.parse(said)
            self.assertEqual(site_url(intent.slots["app"]), "https://www.chess.com", said)
        self.assertEqual(site_url(nlu.parse("open wikipedia dot org").slots["app"]), "https://www.wikipedia.org")
        self.assertEqual(site_url(nlu.parse("open physics wallah").slots["app"]), "https://www.pw.live")
        self.assertIsNone(site_url(nlu.parse("open sign in").slots["app"]))
        self.assertIsNone(site_url(nlu.parse("open notepad").slots["app"]))


if __name__ == "__main__":
    unittest.main()


class SecretsTest(unittest.TestCase):
    def test_secret_file_names(self):
        from jarvis.skills.files import is_secret
        for name in (".env", ".env.local", "server.pem", "id_rsa", "google-credentials.json", "my passwords.txt",
                     "api_keys.txt", ".env - Jarvis - Visual Studio Code", "Get API key | Google AI Studio"):
            self.assertTrue(is_secret(name), name)
        for name in ("notes.txt", "environment.md", "keyboard.txt", "YouTube - Google Chrome", "monkey.png"):
            self.assertFalse(is_secret(name), name)

    def test_secret_files_are_never_read_or_moved(self):
        import tempfile
        from pathlib import Path
        from jarvis.skills import files
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("GROQ_API_KEY=abc", encoding="utf-8")
            for fn in (lambda: files.read_text(str(env)), lambda: files.copy_path(str(env), d),
                       lambda: files.move_path(str(env), d), lambda: files.rename_path(str(env), "x.txt")):
                with self.assertRaises(PermissionError):
                    fn()
            self.assertTrue(env.exists())

    def test_no_screenshot_or_screen_reading_while_a_secret_file_is_in_front(self):
        s = _skills()
        with mock.patch("jarvis.skills.desktop.front_window", return_value="code: .env - Jarvis - Visual Studio Code"), \
                mock.patch("jarvis.skills.desktop.screenshot_jpeg", return_value=b"jpg") as shot, \
                mock.patch("jarvis.skills.elements.page_elements", return_value="[1] button") as items:
            self.assertTrue(s.call("look_at_screen", {}).startswith("Not allowed"))
            self.assertTrue(s.call("page_elements", {}).startswith("Not allowed"))
            with self.assertRaises(PermissionError):
                s.snapshot()
        shot.assert_not_called()
        items.assert_not_called()
