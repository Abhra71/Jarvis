"""v3 steps 2-3: smaller requests (tools and prompt per kind of job) and Groq-first routing."""

import json
import threading
import unittest
from unittest import mock

import jarvis.usage


def setUpModule():
    jarvis.usage.usage.persist = False
    global _no_keys  # never find the real keys in .env
    from jarvis import brain
    _no_keys = mock.patch.object(brain, "load_api_key", return_value=None)
    _no_keys.start()
    global _not_browser  # never depend on which window is in front on this PC
    _not_browser = mock.patch("jarvis.skills.elements.front_is_browser", return_value=False)
    _not_browser.start()


def tearDownModule():
    _no_keys.stop()
    _not_browser.stop()


def _skills():
    """Real tool declarations, fake actions."""
    from jarvis.skills import Skills
    with mock.patch("jarvis.skills.AppLauncher"), mock.patch("jarvis.skills.Browser"):
        real = Skills({"volume": {"step": 10}, "apps": {}}, announce=print)
    skills = mock.MagicMock()
    skills.cancel = threading.Event()
    skills.declarations.side_effect = real.declarations
    skills.browser.profile_summary.return_value = "1. Work [folder: Profile 2]"
    skills.snapshot.return_value = b"jpg"
    return skills


def _brain(skills, gemini=True, groq=None):
    from jarvis import brain
    with mock.patch.object(brain, "load_api_key", return_value=None):
        b = brain.Brain({"model": "g", "fallback_models": []}, skills)
    b.key = "k" if gemini else None
    b.groq = groq
    b.http = mock.Mock()
    return b


def _gemini(parts):
    return mock.Mock(status_code=200, json=lambda: {"candidates": [{"content": {"role": "model", "parts": parts}}]})


def _groq_msg(msg):
    return mock.Mock(status_code=200, json=lambda: {"choices": [{"message": msg}]}, headers={})


def _tool_call(name, args):
    return {"role": "assistant", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        from jarvis.router import classify
        cases = {
            "what's the capital of peru": "chat",
            "who won the latest IPL final": "live",
            "open youtube": "action",
            "volume 30": "action",
            "close this tab": "action",
            "press enter": "action",
            "click No thanks": "screen",
            "pawn e2 to e4": "screen",
            "what's on my screen": "screen",
            "play the second video": "screen",
            "find my resume in downloads": "files",
            "create a folder called trips on the desktop": "files",
            "Hey Jarvis, can you tell me a joke": "chat",
        }
        for text, kind in cases.items():
            self.assertEqual(classify(text), kind, text)

    def test_tool_subsets(self):
        from jarvis.router import missing_groups, tool_names
        self.assertEqual(tool_names("chat"), ["web_search"])
        self.assertNotIn("click", tool_names("action"))
        self.assertIn("click_pair", tool_names("screen"))
        self.assertNotIn("copy_file", tool_names("screen"))
        self.assertIn("copy_file", tool_names("screen", {"files"}))
        self.assertEqual(missing_groups("screen"), ["system", "files"])
        self.assertEqual(missing_groups("screen", request="pause it"), ["files"])
        self.assertEqual(missing_groups("files", {"screen", "system", "keys"}), [])


class SmallRequestTest(unittest.TestCase):
    def test_requests_carry_only_what_their_kind_needs(self):
        from jarvis import brain
        b = _brain(_skills())
        b.http.post.return_value = _gemini([{"text": "Lima."}])
        with mock.patch.object(brain.desktop, "front_window", return_value="Chrome"), \
                mock.patch.object(brain.desktop, "list_open_windows", return_value="Chrome; Notepad"):
            b.ask("what's the capital of peru")
            chat = b.http.post.call_args.kwargs["json"]
            b.ask("open youtube in my work profile")
            action = b.http.post.call_args.kwargs["json"]
        chat_tools = [d["name"] for d in chat["tools"][0]["functionDeclarations"]]
        self.assertEqual(chat_tools, ["web_search", "more_tools"])
        prompt = chat["system_instruction"]["parts"][0]["text"]
        self.assertNotIn("Open windows", prompt)
        self.assertNotIn("Chrome profiles", prompt)
        action_prompt = action["system_instruction"]["parts"][0]["text"]
        self.assertIn("Chrome profiles", action_prompt)  # "work profile" was mentioned
        self.assertIn("Open windows: Chrome; Notepad", action_prompt)
        # A typical command is well under the old ~2,900 tokens of prompt + all 30 tools.
        size = len(action_prompt) + len(json.dumps(action["tools"]))
        self.assertLess(size / 4, 1500)

    def test_more_tools_adds_a_group_mid_request(self):
        skills = _skills()
        skills.call.return_value = "Found resume.pdf in Downloads."
        b = _brain(skills)
        b.http.post.side_effect = [
            _gemini([{"functionCall": {"name": "more_tools", "args": {"group": "files"}}}]),
            _gemini([{"functionCall": {"name": "find_files", "args": {"name": "resume"}}}]),
            _gemini([{"text": "It's in Downloads."}]),
        ]
        self.assertEqual(b.ask("where's my cv? open it"), "It's in Downloads.")
        first, second = [c.kwargs["json"]["tools"][0]["functionDeclarations"] for c in b.http.post.call_args_list[:2]]
        self.assertNotIn("find_files", [d["name"] for d in first])
        self.assertIn("find_files", [d["name"] for d in second])
        skills.call.assert_called_once_with("find_files", {"name": "resume"})  # more_tools isn't a real tool


class RoutingTest(unittest.TestCase):
    def setUp(self):
        from jarvis.usage import usage
        from datetime import date
        usage._load(date.today())

    def _groq(self, http):
        from jarvis.groq_backup import GroqBackup
        return GroqBackup("k", {"groq_models": ["fast"]}, http)

    def test_commands_go_to_groq_first(self):
        groq_http = mock.Mock()
        groq_http.post.return_value = _groq_msg({"role": "assistant", "content": "Lima."})
        b = _brain(_skills(), groq=self._groq(groq_http))
        self.assertEqual(b.ask("what's the capital of peru"), "Lima.")
        b.http.post.assert_not_called()  # Gemini wasn't needed
        self.assertEqual(b.answered_by, "groq")

    def test_screen_requests_go_to_gemini_first(self):
        groq_http = mock.Mock()
        b = _brain(_skills(), groq=self._groq(groq_http))
        b.http.post.return_value = _gemini([{"text": "There's a pop-up asking about cookies."}])
        b.ask("what's on my screen")
        groq_http.post.assert_not_called()
        self.assertEqual(b.answered_by, "gemini")

    def test_groq_hands_over_to_gemini_when_it_needs_to_see(self):
        skills = _skills()

        def call(name, args):
            if name == "look_at_screen":
                return {"text": "Screenshot attached.", "image_jpeg": b"shot"}
            return "Opened YouTube search results for lofi."
        skills.call.side_effect = call
        groq_http = mock.Mock()
        groq_http.post.side_effect = [
            _groq_msg(_tool_call("web_search", {"query": "lofi", "site": "youtube"})),
            _groq_msg(_tool_call("more_tools", {"group": "screen"})),
            _groq_msg(_tool_call("look_at_screen", {})),
        ]
        b = _brain(skills, groq=self._groq(groq_http))
        b.http.post.return_value = _gemini([{"text": "Playing the first lofi video."}])
        self.assertEqual(b.ask("search lofi on youtube and play one"), "Playing the first lofi video.")
        parts = b.http.post.call_args.kwargs["json"]["contents"][-1]["parts"]
        self.assertIn("web_search: Opened YouTube search results", parts[1]["text"])  # not repeated
        self.assertEqual(parts[2]["inlineData"]["data"], "c2hvdA==")  # Groq's screenshot, passed on
        self.assertEqual(sum(c.args[0] == "web_search" for c in skills.call.call_args_list), 1)

    def test_groq_needing_to_see_without_gemini_says_so(self):
        skills = _skills()
        skills.call.return_value = {"text": "Screenshot attached.", "image_jpeg": b"shot"}
        groq_http = mock.Mock()
        groq_http.post.return_value = _groq_msg(_tool_call("look_at_screen", {}))
        b = _brain(skills, gemini=False, groq=self._groq(groq_http))
        self.assertIn("need to see the screen", b.ask("tell me a joke"))

    def test_gemini_failing_falls_back_to_groq(self):
        groq_http = mock.Mock()
        groq_http.post.return_value = _groq_msg({"role": "assistant", "content": "Nothing unusual."})
        b = _brain(_skills(), groq=self._groq(groq_http))
        b.http.post.return_value = mock.Mock(status_code=503, text="busy")
        # The switch to the backup is announced once (the user asked for this, 27 Sep)…
        self.assertEqual(b.ask("what's on my screen"), "The main AI is busy, so I'm using the backup. Nothing unusual.")
        self.assertEqual(b.answered_by, "groq")
        # …not on every reply while it lasts.
        self.assertEqual(b.ask("what's on my screen"), "Nothing unusual.")


if __name__ == "__main__":
    unittest.main()
