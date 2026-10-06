"""The executor: the new brain's steps -> the existing tools (pure mapping, no screen)."""

import unittest

from jarvis.llm import act


class CallsTest(unittest.TestCase):
    def test_everyday_steps(self):
        self.assertEqual(act.calls({"do": "tab", "action": "close", "which": "current"}),
                         [("browser", {"action": "close_tab", "times": 1})])
        self.assertEqual(act.calls({"do": "tab", "action": "close_matching", "which": "chess"}),
                         [("close_tab_named", {"name": "chess", "all": True})])
        self.assertEqual(act.calls({"do": "open_site", "site": "youtube.com", "browser": "Brave"}),
                         [("open_app", {"name": "brave"}), ("address_bar", {"text": "youtube.com"})])
        self.assertEqual(act.calls({"do": "open_site", "site": "chess.com", "profile": "main"}),
                         [("open_website", {"url": "https://chess.com", "profile": "main"})])
        self.assertEqual(act.calls({"do": "volume", "mute": True}), [("volume", {"action": "mute"})])
        self.assertEqual(act.calls({"do": "volume", "level": 40}), [("volume", {"action": "set", "level": 40})])
        self.assertEqual(act.calls({"do": "window", "action": "snap", "target": "Chrome", "side": "left"}),
                         [("window", {"app": "Chrome", "action": "focus"}), ("do", {"ability": "snap_left"})])

    def test_youtube_goes_to_the_youtube_pack_when_it_is_in_front(self):
        self.assertEqual(act.calls({"do": "media", "action": "pause"}, "chrome: Lofi - YouTube"),
                         [("youtube", {"command": "pause"})])
        self.assertEqual(act.calls({"do": "media", "action": "seek", "seconds": 42}, "chrome: x - YouTube"),
                         [("youtube", {"command": "forward 42 seconds"})])

    def test_a_site_in_front_uses_its_own_search_box(self):
        self.assertEqual(act.calls({"do": "search", "query": "drones under 2000", "site": "flipkart"},
                                   "chrome: Flipkart - Online Shopping"), [("site_search", {"query": "drones under 2000"})])
        self.assertEqual(act.calls({"do": "search", "query": "boots", "site": "amazon"}),
                         [("web_search", {"query": "boots", "site": "amazon"})])

    def test_deleting_a_bluej_class_is_right_click_then_remove(self):
        self.assertEqual(act.calls({"do": "bluej", "action": "delete_class", "name": "Oval"}),
                         [("right_click", {"name": "Oval", "kind": "class"}), ("choose_menu_item", {"name": "Remove"})])

    def test_what_cannot_be_done_yet_is_said_plainly(self):
        self.assertIsInstance(act.calls({"do": "chess", "move": "e2e4"}), str)
        self.assertIsInstance(act.calls({"do": "fly"}), str)


class RunTest(unittest.TestCase):
    class FakeSkills:
        def __init__(self, answers):
            self.answers, self.calls = answers, []

        def call(self, tool, args):
            self.calls.append(tool)
            return self.answers.get(tool, "Done.")

    def test_stops_at_the_first_step_that_did_not_happen(self):
        s = self.FakeSkills({"right_click": "Not clicked: Nothing called 'Oval' is on screen."})
        ok, said = act.run([{"do": "bluej", "action": "delete_class", "name": "Oval"}], s)
        self.assertFalse(ok)
        self.assertEqual(s.calls, ["right_click"])
        self.assertIn("Oval", said[-1])

    def test_a_needed_yes_stops_it(self):
        s = self.FakeSkills({"choose_menu_item": "Needs confirmation: this would click 'Remove'."})
        ok, said = act.run([{"do": "bluej", "action": "delete_class", "name": "Oval"}], s)
        self.assertFalse(ok)
        self.assertTrue(said[-1].startswith("Needs confirmation"))


if __name__ == "__main__":
    unittest.main()
