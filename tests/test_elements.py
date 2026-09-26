"""v3 step 4: the screen as text, and clicking by name."""

import json
import threading
import unittest
from unittest import mock

import jarvis.usage
from jarvis.skills import elements
from jarvis.skills.elements import Element


def setUpModule():
    jarvis.usage.usage.persist = False
    global _no_keys
    from jarvis import brain
    _no_keys = mock.patch.object(brain, "load_api_key", return_value=None)
    _no_keys.start()
    global _not_browser  # never depend on which window is in front on this PC
    _not_browser = mock.patch("jarvis.skills.elements.front_is_browser", return_value=False)
    _not_browser.start()


def tearDownModule():
    _no_keys.stop()
    _not_browser.stop()


POPUP = [
    Element("link", "Play Bots", (100, 100, 200, 130)),
    Element("button", "No thanks", (800, 500, 900, 540)),
    Element("button", "Try Premium", (950, 500, 1100, 540)),
    Element("button", "Send", (100, 900, 180, 940)),
]


class MatchTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(elements.match(POPUP, "no thanks")[0].name, "No thanks")
        self.assertEqual(elements.match(POPUP, "No, thanks")[0].name, "No thanks")
        self.assertEqual(elements.match(POPUP, "play bots")[0].name, "Play Bots")
        el, why = elements.match(POPUP, "resign")
        self.assertIsNone(el)
        self.assertIn("Nothing called", why)

    def test_ambiguous_names_ask(self):
        videos = [Element("link", "Aari Aari (Official Video)", (0, 0, 9, 9)),
                  Element("link", "Aari Aari (Lyric Video)", (0, 20, 9, 29))]
        el, why = elements.match(videos, "aari aari")
        self.assertIsNone(el)
        self.assertIn("More than one", why)

    def test_describe_is_short_and_numbered(self):
        text = elements.describe(POPUP)
        self.assertTrue(text.startswith('[1] link "Play Bots"; [2] button "No thanks"'))
        many = [Element("link", f"Video {i}", (0, i, 9, i + 9)) for i in range(80)]
        self.assertIn("+20 more", elements.describe(many))

    def test_ids_are_checked_against_the_screen_now(self):
        with mock.patch.object(elements, "read_front", return_value=POPUP):
            elements.page_elements()
        moved = [Element("button", "No thanks", (820, 480, 920, 520))]
        with mock.patch.object(elements, "read_front", return_value=moved):
            el, _ = elements.resolve(id=2)
        self.assertEqual(el.rect, (820, 480, 920, 520))  # clicked where it is now, not where it was
        with mock.patch.object(elements, "read_front", return_value=POPUP[:1]):
            el, why = elements.resolve(id=2)
        self.assertIsNone(el)
        self.assertIn("isn't on screen any more", why)
        self.assertIn("no item [9]", elements.resolve(id=9)[1])


class ClickElementTest(unittest.TestCase):
    def _skills(self):
        from jarvis.skills import Skills
        with mock.patch("jarvis.skills.AppLauncher"), mock.patch("jarvis.skills.Browser"):
            return Skills({"volume": {"step": 10}, "apps": {}}, announce=print)

    def test_click_by_name_needs_no_screenshot(self):
        s = self._skills()
        with mock.patch.object(elements, "read_front", return_value=POPUP), \
                mock.patch("jarvis.skills.mouse.click") as click, \
                mock.patch("jarvis.skills.desktop.front_window", return_value="chrome: chess"):
            self.assertEqual(s.call("click_element", {"name": "no thanks"}), "Clicked the No thanks button.")
        click.assert_called_once()

    def test_risky_items_need_a_yes_even_by_id(self):
        s = self._skills()
        with mock.patch.object(elements, "read_front", return_value=POPUP), \
                mock.patch("jarvis.skills.mouse.click") as click, \
                mock.patch("jarvis.skills.desktop.front_window", return_value="chrome: mail"):
            elements.page_elements()
            self.assertTrue(s.call("click_element", {"id": 4}).startswith("Needs confirmation"))  # [4] = Send
            click.assert_not_called()
            s.confirmed = True
            s.call("click_element", {"id": 4})
            click.assert_called_once()

    def test_counts_against_the_action_budget(self):
        s = self._skills()
        s.budget = 1
        with mock.patch.object(elements, "read_front", return_value=POPUP), \
                mock.patch("jarvis.skills.mouse.click") as click, \
                mock.patch("jarvis.skills.desktop.front_window", return_value=""):
            s.call("click_element", {"name": "no thanks"})
            self.assertTrue(s.call("click_element", {"name": "play bots"}).startswith("Not done"))
        self.assertEqual(click.call_count, 1)

    def test_needs_an_id_or_name(self):
        self.assertIn("give the item's id", self._skills().call("click_element", {}))


class ScreenAsTextRoutingTest(unittest.TestCase):
    def _brain(self, groq_http):
        from jarvis import brain
        from jarvis.groq_backup import GroqBackup
        skills = mock.MagicMock()
        skills.cancel = threading.Event()
        skills.declarations.return_value = []
        skills.browser.profile_summary.return_value = ""
        b = brain.Brain({"model": "g", "fallback_models": []}, skills)
        b.key = "k"
        b.groq = GroqBackup("k", {"groq_models": ["fast"]}, groq_http)
        b.http = mock.Mock()
        return b, skills

    def test_named_click_goes_to_groq_with_the_item_list(self):
        groq_http = mock.Mock()
        call = {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "click_element", "arguments": json.dumps({"id": 2})}}]}
        groq_http.post.return_value = mock.Mock(status_code=200, headers={},
                                                json=lambda: {"choices": [{"message": call}]})
        b, skills = self._brain(groq_http)
        skills.call.side_effect = lambda name, args: (elements.describe(POPUP) if name == "page_elements"
                                                      else "Clicked the No thanks button.")
        self.assertEqual(b.ask("click No thanks"), "Clicked the No thanks button.")  # fast finish, 1 request
        b.http.post.assert_not_called()  # no Gemini, no screenshot
        skills.snapshot.assert_not_called()
        sent = groq_http.post.call_args.kwargs["json"]["messages"][-3]["content"]
        self.assertIn('[2] button "No thanks"', sent)
        self.assertNotIn("[2] button", json.dumps(b.history))  # the list isn't kept (tokens)

    def test_open_x_on_a_page_means_the_link(self):
        from jarvis.router import thing_named
        self.assertEqual(thing_named("Hey Jarvis, open chemistry"), "chemistry")
        self.assertEqual(thing_named("volume 30"), "")
        pw = [Element("link", "Physics", (0, 0, 9, 9)), Element("link", "Chemistry", (0, 20, 9, 29))]
        b, skills = self._brain(mock.Mock())
        b.groq = None
        skills.call.side_effect = lambda name, args: (elements.page_elements() if name == "page_elements"
                                                      else "Clicked the Chemistry link.")
        b.http.post.return_value = mock.Mock(status_code=200, json=lambda: {"candidates": [{"content": {
            "role": "model", "parts": [{"text": "Opened Chemistry."}]}}]})
        with mock.patch.object(elements, "front_is_browser", return_value=True), \
                mock.patch.object(elements, "read_front", return_value=pw):
            b.ask("open chemistry")
        self.assertEqual(b.kind, "screen")
        sent = b.http.post.call_args.kwargs["json"]["contents"][-1]["parts"]
        self.assertIn('[2] link "Chemistry"', sent[1]["text"])
        with mock.patch.object(elements, "front_is_browser", return_value=True), \
                mock.patch.object(elements, "read_front", return_value=pw):
            b.ask("open notepad")
        self.assertEqual(b.kind, "action")  # not on the page: stays a normal command

    def test_board_moves_still_get_a_screenshot(self):
        b, skills = self._brain(mock.Mock())
        b.http.post.return_value = mock.Mock(status_code=200, json=lambda: {"candidates": [{"content": {
            "role": "model", "parts": [{"text": "Which pawn?"}]}}]})
        skills.snapshot.return_value = b"jpg"
        b.ask("pawn e2 to e4")
        skills.snapshot.assert_called_once()
        self.assertNotIn(mock.call("page_elements", {}), skills.call.call_args_list)

    def test_no_named_items_falls_back_to_gemini_and_a_screenshot(self):
        b, skills = self._brain(mock.Mock())
        skills.call.return_value = "No named items found in the front window."
        skills.snapshot.return_value = b"jpg"
        b.http.post.return_value = mock.Mock(status_code=200, json=lambda: {"candidates": [{"content": {
            "role": "model", "parts": [{"text": "Done."}]}}]})
        b.ask("click the red thing")
        skills.snapshot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
