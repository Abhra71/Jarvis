import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jarvis.usage
from jarvis.skills.browser import Profile, find_profile, load_profiles


def setUpModule():
    # Tests get a throwaway, never-saved copy of the usage stats instead of your real ones.
    jarvis.usage.usage.persist = False


def _fresh_usage():
    from datetime import date
    jarvis.usage.usage._load(date.today())

PROFILES = [
    Profile("Default", "ABHRA", "abhra@gmail.com"),
    Profile("Profile 1", "Abhra", "other@gmail.com"),
    Profile("Profile 2", "Work", "work.me@gmail.com"),
    Profile("Profile 3", "Miscellaneous", "misc@gmail.com"),
]


class ProfileTest(unittest.TestCase):
    def test_load_sorted_like_chrome_picker(self):
        # Mirrors this PC: Chrome's picker lists profiles alphabetically, ties in creation order.
        state = {"profile": {"info_cache": {
            "Default": {"name": "ABHRA", "gaia_name": "ABHRA CHAKRABORTY"},
            "Profile 1": {"name": "Abhra", "gaia_name": "Abhra"},
            "Profile 2": {"name": "Work", "gaia_name": "Error", "user_name": "w@x.com"},
            "Profile 3": {"name": "Miscellaneous"},
            "Profile 4": {"name": "Abhra", "gaia_name": "Abhra Chakraborty"},
            "Profile 6": {"name": "largelanguage"},
        }, "profiles_order": ["Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4", "Profile 6"]}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "Local State"
            path.write_text(json.dumps(state), encoding="utf-8")
            got = load_profiles(path)
        self.assertEqual([p.directory for p in got],
                         ["Default", "Profile 1", "Profile 4", "Profile 6", "Profile 3", "Profile 2"])
        self.assertEqual(got[2].full_name, "Abhra Chakraborty")
        self.assertEqual(got[5].full_name, "")  # "Error" is ignored
        self.assertEqual(find_profile(got, "third").directory, "Profile 4")

    def test_missing_file(self):
        self.assertEqual(load_profiles(Path("nope/Local State")), [])

    def test_find(self):
        cases = {
            "work": "Profile 2",
            "my work profile": "Profile 2",
            "third profile": "Profile 2",
            "second": "Profile 1",
            "Profile 3": "Profile 3",
            "miscellaneous": "Profile 3",
            "misc account": "Profile 3",
        }
        for spoken, directory in cases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(find_profile(PROFILES, spoken).directory, directory)
        self.assertIsNone(find_profile(PROFILES, "banana"))
        self.assertIsNone(find_profile(PROFILES, None))


def _fake_skills():
    skills = mock.MagicMock()
    skills.declarations.return_value = []
    skills.browser.profile_summary.return_value = "1. Work [folder: Profile 2]"
    skills.call.return_value = "Opened youtube.com in the Work profile."
    return skills


def _response(parts):
    return mock.Mock(status_code=200, json=lambda: {"candidates": [{"content": {"role": "model", "parts": parts}}]},
                     raise_for_status=lambda: None)


class BrainTest(unittest.TestCase):
    def setUp(self):
        _fresh_usage()
        from jarvis import brain
        self.brain_mod = brain
        patcher = mock.patch.object(brain, "load_api_key",
                                    side_effect=lambda name="GEMINI_API_KEY": "test-key" if name == "GEMINI_API_KEY" else None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tool_loop_then_answer(self):
        skills = _fake_skills()
        b = self.brain_mod.Brain({"model": "gemini-test"}, skills)
        b.http = mock.Mock()
        b.http.post.side_effect = [
            _response([{"functionCall": {"name": "open_website",
                                         "args": {"url": "https://www.youtube.com", "profile": "Profile 2"}}}]),
            _response([{"text": "Done, **YouTube** is open in your Work profile."}]),
        ]
        # multi-step wording, so the AI (not the fast finish) writes the reply
        reply = b.ask("open youtube in my work profile and tell me when it's ready")
        self.assertEqual(reply, "Done, YouTube is open in your Work profile.")
        skills.call.assert_called_once_with("open_website", {"url": "https://www.youtube.com", "profile": "Profile 2"})
        # The second request must carry the function call and its result back to Gemini.
        second_body = b.http.post.call_args_list[1].kwargs["json"]
        roles = [c["role"] for c in second_body["contents"]]
        self.assertEqual(roles, ["user", "model", "user"])
        self.assertIn("functionResponse", second_body["contents"][2]["parts"][0])
        # History remembers the whole exchange for follow-ups like "close it".
        self.assertEqual(len(b.history), 4)

    def test_quota_raises_unavailable(self):
        b = self.brain_mod.Brain({"model": "gemini-test"}, _fake_skills())
        b.http = mock.Mock()
        b.http.post.return_value = mock.Mock(status_code=429, text="quota")
        with self.assertRaises(self.brain_mod.BrainUnavailable):
            b.ask("what is the capital of peru")

    def test_busy_model_falls_back(self):
        b = self.brain_mod.Brain({"model": "main", "fallback_models": ["backup"]}, _fake_skills())
        b.http = mock.Mock()
        b.http.post.side_effect = [mock.Mock(status_code=503, text="busy"), _response([{"text": "Lima."}])]
        self.assertEqual(b.ask("capital of peru"), "Lima.")
        self.assertIn("/models/backup:", b.http.post.call_args_list[1].args[0])

    def test_all_busy_says_busy(self):
        b = self.brain_mod.Brain({"model": "main", "fallback_models": ["backup"]}, _fake_skills())
        b.http = mock.Mock()
        b.http.post.return_value = mock.Mock(status_code=503, text="busy")
        with self.assertRaisesRegex(self.brain_mod.BrainUnavailable, "busy"):
            b.ask("capital of peru")

    def test_screenshot_is_attached(self):
        skills = _fake_skills()
        skills.call.return_value = {"text": "Screenshot attached.", "image_jpeg": b"\xff\xd8jpeg"}
        b = self.brain_mod.Brain({"model": "m"}, skills)
        b.http = mock.Mock()
        b.http.post.side_effect = [_response([{"functionCall": {"name": "look_at_screen", "args": {}}}]),
                                   _response([{"text": "You're on YouTube."}])]
        self.assertEqual(b.ask("what's on my screen"), "You're on YouTube.")
        parts = b.http.post.call_args_list[1].kwargs["json"]["contents"][2]["parts"]
        self.assertIn("functionResponse", parts[0])
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/jpeg")
        # …but it's dropped from memory before the next request.
        b._trim_history()
        self.assertFalse(any("inlineData" in p for c in b.history for p in c["parts"]))


class GroqBackupTest(unittest.TestCase):
    def setUp(self):
        _fresh_usage()

    def test_gemini_out_of_quota_uses_groq_with_tools(self):
        from jarvis import brain
        from jarvis.groq_backup import GroqBackup

        skills = _fake_skills()
        skills.declarations.return_value = [
            {"name": "open_website", "description": "Open a site.",
             "parameters": {"type": "OBJECT", "properties": {"url": {"type": "STRING"}}, "required": ["url"]}},
            {"name": "cancel_timers", "description": "Cancel timers."},
        ]
        with mock.patch.object(brain, "load_api_key", side_effect=lambda name="GEMINI_API_KEY": "k"):
            b = brain.Brain({"model": "g", "fallback_models": []}, skills)
        b.http = mock.Mock()
        b.http.post.return_value = mock.Mock(status_code=429, text="quota")

        groq_http = mock.Mock()
        tool_msg = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "open_website", "arguments": '{"url": "https://www.youtube.com"}'}}]}
        final = {"role": "assistant", "content": "YouTube is open."}
        groq_http.post.side_effect = [mock.Mock(status_code=200, json=lambda: {"choices": [{"message": tool_msg}]}),
                                      mock.Mock(status_code=200, json=lambda: {"choices": [{"message": final}]})]
        b.groq = GroqBackup("k", {"groq_models": ["some-model"]}, groq_http)

        self.assertEqual(b.ask("open youtube and tell me when it's ready"), "YouTube is open.")
        skills.call.assert_called_once_with("open_website", {"url": "https://www.youtube.com"})
        sent = groq_http.post.call_args_list[0].kwargs["json"]
        self.assertEqual(sent["tools"][0]["function"]["parameters"]["properties"]["url"]["type"], "string")
        self.assertEqual(sent["tools"][1]["function"]["parameters"], {"type": "object", "properties": {}})
        roles = [m["role"] for m in groq_http.post.call_args_list[1].kwargs["json"]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])  # list is shared, so includes the final reply
        # Shared memory gets the exchange, so Gemini sees it next time.
        self.assertEqual(b.history[-1]["parts"][0]["text"], "YouTube is open.")


class GroqModelsTest(unittest.TestCase):
    def setUp(self):
        _fresh_usage()

    def test_rate_limited_model_moves_on_and_screenshot_uses_vision_model(self):
        from jarvis.groq_backup import GroqBackup

        ok = lambda msg: mock.Mock(status_code=200, json=lambda: {"choices": [{"message": msg}]})
        look = {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "look_at_screen", "arguments": "{}"}}]}
        http = mock.Mock()
        http.post.side_effect = [
            mock.Mock(status_code=429, text="rate limit"),               # fast model is rate-limited…
            ok(look),                                                   # …second model asks for a screenshot
            ok({"role": "assistant", "content": "You're on YouTube."}),  # vision model answers
        ]
        g = GroqBackup("k", {"groq_models": ["fast", "second"], "groq_vision_model": "eyes"}, http)
        tool = mock.Mock(return_value={"text": "Screenshot attached.", "image_jpeg": b"jpg"})
        reply, _ = g.ask("sys", [], "what's on my screen", [], tool)

        self.assertEqual(reply, "You're on YouTube.")
        used = [c.kwargs["json"]["model"] for c in http.post.call_args_list]
        self.assertEqual(used, ["fast", "second", "eyes"])
        last_user = http.post.call_args_list[2].kwargs["json"]["messages"][-2]
        self.assertEqual(last_user["content"][1]["type"], "image_url")


class UsageTest(unittest.TestCase):
    def setUp(self):
        _fresh_usage()

    def test_counts_routes_models_screenshots_and_limits(self):
        from jarvis.usage import usage

        usage.begin_turn("what's on my screen")
        usage.api_call("gemini", "lite", 429, 0.5)
        usage.api_call("gemini", "flash", 200, 2.0, 1000, 20)
        usage.action("look_at_screen")
        usage.end_turn("gemini", "You're on YouTube.")
        usage.begin_turn("volume 30")
        usage.end_turn("offline rules", "Volume set to 30 percent.")

        s = usage.snapshot()
        self.assertEqual(s["routes"]["gemini"], 1)
        self.assertEqual(s["routes"]["offline rules"], 1)
        self.assertEqual(s["screenshots"]["count"], 1)
        self.assertEqual(s["ai_requests"], 2)
        latest = s["turns"][1]  # newest first
        self.assertEqual(latest["screenshots"], 1)
        self.assertEqual(latest["models"], ["lite → 429", "flash → 200"])
        self.assertTrue(usage.is_limited("gemini:lite"))
        self.assertFalse(usage.is_limited("gemini:flash"))
        spoken = usage.spoken_summary(["gemini:lite", "gemini:flash"])
        self.assertIn("Right now I'd use flash", spoken)
        self.assertIn("lite is at the limit", spoken)

    def test_limited_gemini_model_is_skipped(self):
        from jarvis import brain
        from jarvis.usage import usage

        usage.api_call("gemini", "lite", 429, 0.1)  # hit its limit moments ago
        with mock.patch.object(brain, "load_api_key", side_effect=lambda name="GEMINI_API_KEY": "k" if name == "GEMINI_API_KEY" else None):
            b = brain.Brain({"model": "lite", "fallback_models": ["flash"]}, _fake_skills())
        b.http = mock.Mock()
        b.http.post.return_value = _response([{"text": "Lima."}])
        self.assertEqual(b.ask("capital of peru"), "Lima.")
        self.assertEqual(b.http.post.call_count, 1)
        self.assertIn("/models/flash:", b.http.post.call_args.args[0])


class SpeedTest(unittest.TestCase):
    def setUp(self):
        _fresh_usage()

    def _brain(self, cfg):
        from jarvis import brain
        with mock.patch.object(brain, "load_api_key", side_effect=lambda name="GEMINI_API_KEY": "k" if name == "GEMINI_API_KEY" else None):
            return brain.Brain(cfg, _fake_skills())

    def test_hung_request_is_hedged_to_the_reliable_model(self):
        import threading
        import time as t

        b = self._brain({"model": "lite", "fallback_models": [], "hedge_model": "steady",
                         "hedge_after_seconds": 0.2, "timeout_seconds": 5})
        release = threading.Event()
        urls = []

        def post(url, **k):
            urls.append(url)
            if "/models/lite:" in url:
                release.wait(5)  # the main model "hangs", like the newest Gemini Lite models often do
            return _response([{"text": "Paris."}])

        b.http = mock.Mock()
        b.http.post.side_effect = post
        start = t.monotonic()
        self.assertEqual(b.ask("capital of france"), "Paris.")
        self.assertLess(t.monotonic() - start, 2)  # didn't wait for the hung one
        self.assertIn("/models/steady:", urls[1])  # the second copy went to the reliable model
        release.set()

    def test_fast_finish_skips_the_extra_round_trip(self):
        b = self._brain({"model": "lite", "fallback_models": []})
        b.skills.call.return_value = "Done."
        b.http = mock.Mock()
        b.http.post.return_value = _response([
            {"text": "Closed the tab."}, {"functionCall": {"name": "browser", "args": {"action": "close_tab"}}}])
        self.assertEqual(b.ask("close this tab"), "Closed the tab.")
        self.assertEqual(b.http.post.call_count, 1)  # no second request just to say "Done"
        self.assertEqual(b.history[-1], {"role": "model", "parts": [{"text": "Closed the tab."}]})

    def test_no_fast_finish_when_the_action_failed(self):
        b = self._brain({"model": "lite", "fallback_models": []})
        b.skills.call.return_value = "No browser window is open."
        b.http = mock.Mock()
        b.http.post.side_effect = [
            _response([{"text": "Closed the tab."}, {"functionCall": {"name": "browser", "args": {"action": "close_tab"}}}]),
            _response([{"text": "There's no browser open."}])]
        self.assertEqual(b.ask("close this tab"), "There's no browser open.")
        self.assertEqual(b.http.post.call_count, 2)  # the AI hears about the failure and answers honestly

    def test_after_gemini_stalls_groq_goes_first(self):
        from jarvis import brain

        with mock.patch.object(brain, "load_api_key", side_effect=lambda name="GEMINI_API_KEY": "k"):
            b = brain.Brain({"model": "lite", "fallback_models": []}, _fake_skills())
        b.http = mock.Mock()
        b.http.post.return_value = mock.Mock(status_code=503, text="busy")  # Gemini stalling
        b.groq = mock.Mock()
        b.groq.ask.return_value = ("Lima.", [])

        self.assertEqual(b.ask("capital of peru"), "Lima.")  # Gemini failed, Groq answered
        gemini_calls = b.http.post.call_count
        self.assertEqual(b.ask("capital of chile"), "Lima.")  # next request: straight to Groq
        self.assertEqual(b.http.post.call_count, gemini_calls)  # Gemini wasn't tried again yet

    def test_click_must_be_checked_before_claiming_success(self):
        b = self._brain({"model": "lite", "fallback_models": []})

        def call(name, args):
            if name == "look_at_screen":
                return {"text": "Screenshot attached.", "image_jpeg": b"jpg"}
            return "Left-clicked."

        b.skills.call.side_effect = call
        b.http = mock.Mock()
        b.http.post.side_effect = [
            _response([{"functionCall": {"name": "click", "args": {"x": 400, "y": 300}}}]),
            _response([{"text": "Chemistry 2026 is open."}]),         # tries to claim without looking…
            _response([{"text": "Complete Chemistry 2024 opened."}]),  # …after the forced look: the truth
        ]
        self.assertEqual(b.ask("open chemistry 2026"), "Complete Chemistry 2024 opened.")
        self.assertIn(mock.call("look_at_screen", {}), b.skills.call.call_args_list)
        third = b.http.post.call_args_list[2].kwargs["json"]["contents"][-1]["parts"]
        self.assertIn("inlineData", third[1])

    def test_fast_reply_rules(self):
        from jarvis.brain import fast_reply

        # single simple action that worked: speak the tool's own sentence
        self.assertEqual(fast_reply("close this tab", ["browser"], ["Closed the tab."]), "Closed the tab.")
        # multi-step request: let the AI continue ("…and search lofi")
        self.assertIsNone(fast_reply("open youtube and search lofi", ["open_website"], ["Opened youtube.com."]))
        # looking / clicking needs the AI to judge the result
        self.assertIsNone(fast_reply("play the second video", ["click"], ["Left-clicked at 400,300."]))
        # failed action: the AI must hear about it
        self.assertIsNone(fast_reply("close notepad", ["window"], ["I don't see notepad open."]))
        # the AI's own reply wins when it sent one
        self.assertEqual(fast_reply("mute", ["mute"], ["Muted."], "Muted it."), "Muted it.")

    def test_daily_limit_parks_model_for_an_hour(self):
        from jarvis.brain import _limit_seconds

        daily = mock.Mock(json=lambda: {"error": {"details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
             "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "32s"}]}})
        per_minute = mock.Mock(json=lambda: {"error": {"details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12.5s"}]}})
        self.assertEqual(_limit_seconds(daily), 3600)
        self.assertEqual(_limit_seconds(per_minute), 13)
        self.assertEqual(_limit_seconds(mock.Mock(json=lambda: {})), 60)


class RoutingTest(unittest.TestCase):
    """Which requests stay offline (instant) and which go to Gemini."""

    def setUp(self):
        _fresh_usage()
        from jarvis import assistant
        with mock.patch.object(assistant, "Speaker"), mock.patch.object(assistant, "Skills") as skills_cls, \
                mock.patch("jarvis.brain.load_api_key", return_value="k"):
            skills_cls.return_value.apps.find_exact.side_effect = lambda a: ("notepad", "x") if a == "notepad" else None
            skills_cls.return_value.browser.profiles = PROFILES
            skills_cls.return_value.run.return_value = "rules"
            self.a = assistant.Assistant({"tts": {}, "ai": {}, "volume": {"step": 10}})
        self.a.brain.ask = mock.Mock(return_value="ai")

    def test_routes(self):
        cases = {
            "volume 30": "rules",
            "mute": "rules",
            "set a timer for 5 minutes": "rules",
            "what time is it": "rules",
            "open notepad": "rules",
            "open youtube": "rules",
            "open the third account": "rules",
            "open chrome work profile": "rules",
            "search for python tutorials": "ai",
            "search for youtube here": "ai",
            "open youtube in my work profile": "ai",
            "search lofi music on youtube": "ai",
            "open a new tab": "ai",
            "close chrome": "ai",
            "what's the capital of peru": "ai",
            "open spotify and play some music": "ai",
            "which model are you using": "status",
            "ai status": "status",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                reply = self.a.handle_text(text)
                if expected == "status":
                    self.assertIn("Today:", reply)  # spoken summary, answered offline
                else:
                    self.assertEqual(reply, expected)

    def test_ai_failing_midway_does_not_run_offline_rules(self):
        from jarvis.brain import BrainUnavailable

        self.a.skills.calls_made = 0

        def act_then_fail(text):
            self.a.skills.calls_made += 1  # the AI already clicked/typed something…
            raise BrainUnavailable("Gemini is busy")

        self.a.brain.ask = act_then_fail
        self.a.skills.run.reset_mock()
        reply = self.a.handle_text("search for lofi hip hop here")
        self.assertIn("partway", reply)
        self.a.skills.run.assert_not_called()  # …so no Google search for "lofi hip hop here"

    def test_no_key_falls_back_to_rules(self):
        self.a.brain.key = None
        self.a.brain.groq = None
        del self.a.brain.ask  # use the real ask(), which refuses without a key
        with mock.patch("jarvis.brain.load_api_key", return_value=None):  # don't find the real .env key
            self.assertEqual(self.a.handle_text("volume 30"), "rules")
            self.assertIn("Gemini key", self.a.handle_text("what's the capital of peru"))


if __name__ == "__main__":
    unittest.main()
