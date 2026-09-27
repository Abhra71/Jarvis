"""v3 step 5b: the YouTube pack. The front window and the page are faked; nothing touches the screen."""

import unittest
from unittest import mock

from jarvis.skills.sites import youtube


class VideoTitleTest(unittest.TestCase):
    def test_real_videos_end_with_their_length(self):
        # Names as UI Automation read them from a real results page (27 Sep).
        self.assertEqual(youtube.video_title("1 A.M Study Session 📚 [lofi hip hop] 1 hour, 1 minute"),
                         "1 A.M Study Session 📚 [lofi hip hop]")
        self.assertEqual(youtube.video_title("O Maahi - Lofi Mix | Slowed + Reverb 4 minutes, 37 seconds"),
                         "O Maahi - Lofi Mix | Slowed + Reverb")
        self.assertEqual(youtube.video_title("Bedtime Lofi 💤 8 hours of relaxing beats to sleep to 8 hours"),
                         "Bedtime Lofi 💤 8 hours of relaxing beats to sleep to")
        for not_a_video in ("Mochi's Garden Reading | lofi hip hop study / relax / focus",  # an ad
                            "Top 5 Indian Lo-Fi Songs #shorts #ytshorts",                   # a Short
                            "Go to channel Lofi Girl", "lofi hip hop radio 📚 beats to relax/study to"):  # live
            self.assertIsNone(youtube.video_title(not_a_video), not_a_video)


class CommandTest(unittest.TestCase):
    def _run(self, text, front="lofi music - YouTube - Google Chrome", buttons=("Pause keyboard shortcut k",), unsure=False):
        pressed, keys = [], []

        def press(hwnd, *prefixes):
            for p in prefixes:
                for b in buttons:
                    if b.lower().startswith(p.lower()):
                        pressed.append(b)
                        return b
            return None

        def has(hwnd, *prefixes):
            return any(b.lower().startswith(p.lower()) for p in prefixes for b in buttons)

        with mock.patch.object(youtube.win32gui, "GetForegroundWindow", return_value=1), \
                mock.patch.object(youtube, "has_button", side_effect=has), \
                mock.patch.object(youtube.win32gui, "GetWindowText", return_value=front), \
                mock.patch.object(youtube.desktop, "_process_name", return_value="chrome.exe"), \
                mock.patch.object(youtube, "press_button", side_effect=press), \
                mock.patch.object(youtube, "_keys", side_effect=lambda h, k, n=1: keys.append((k, n))), \
                mock.patch.object(youtube, "play", side_effect=lambda q, h, b: f"PLAY {q} {'here' if h else 'new'}"), \
                mock.patch.object(youtube, "play_nth", side_effect=lambda h, n: f"NTH {n}"), \
                mock.patch.object(youtube.desktop, "address_bar") as bar:
            reply = youtube.handle(text, browser=None, unsure=unsure)
        return reply, pressed, keys, bar

    def test_player_controls(self):
        # Button names as read from the real player, 27 Sep.
        self.assertEqual(self._run("pause")[:2], ("Paused.", ["Pause keyboard shortcut k"]))
        self.assertEqual(self._run("Hey Jarvis, pause the video.")[0], "Paused.")
        play = ("Play keyboard shortcut k",)
        self.assertEqual(self._run("resume", buttons=play)[:2], ("Playing.", ["Play keyboard shortcut k"]))
        self.assertEqual(self._run("pause", buttons=play)[:2], ("It's already paused.", []))  # nothing pressed
        self.assertEqual(self._run("play")[:2], ("It's already playing.", []))
        self.assertEqual(self._run("skip the ad", buttons=("Skip Ad",))[:2], ("Skipped the ad.", ["Skip Ad"]))
        self.assertIn("don't see a skip button", self._run("skip ad", buttons=())[0])
        self.assertEqual(self._run("full screen", buttons=("Full screen (f)",))[0], "Full screen.")
        self.assertEqual(self._run("next video", buttons=("Next",))[0], "Next video.")

    def test_no_button_falls_back_to_youtube_keys(self):
        reply, _, keys, _ = self._run("mute the video", buttons=())
        self.assertEqual((reply, keys), ("Muted the video.", [("m", 1)]))

    def test_seeking_and_speed(self):
        self.assertEqual(self._run("forward 30 seconds")[2], [("l", 3)])
        self.assertEqual(self._run("go back 10 seconds")[2], [("j", 1)])
        self.assertEqual(self._run("rewind")[2], [("j", 1)])
        self.assertEqual(self._run("forward 2 minutes")[2], [("l", 12)])
        self.assertEqual(self._run("speed up")[2], [("+.", 1)])
        self.assertIsNone(self._run("go back")[0])  # the browser's back, not seeking

    def test_play_and_search(self):
        self.assertEqual(self._run("play aari aari")[0], "PLAY aari aari here")
        self.assertEqual(self._run("play the second video")[0], "NTH 2")
        self.assertEqual(self._run("play the next video", buttons=("Next",))[0], "Next video.")
        reply, _, _, bar = self._run("search for python tutorials")
        self.assertIn("python tutorials", reply)
        self.assertIn("search_query=python+tutorials", bar.call_args.args[0])

    def test_only_when_youtube_is_in_front_unless_it_is_named(self):
        gmail = "Inbox - Gmail - Google Chrome"
        self.assertIsNone(self._run("pause", front=gmail)[0])
        self.assertIsNone(self._run("play lofi", front=gmail)[0])  # could mean Spotify: the AI decides
        self.assertEqual(self._run("play lofi on youtube", front=gmail)[0], "PLAY lofi new")
        self.assertEqual(self._run("play lo fi on you tube", front=gmail)[0], "PLAY lo fi new")

    def test_context_and_shaky_speech_go_to_the_ai(self):
        # 27 Sep: "Search it, but in this channel, in this page…" was searched word for word.
        self.assertIsNone(self._run("search it but in this channel in this page")[0])
        self.assertIsNone(self._run("play that one again")[0])
        reply, _, _, bar = self._run("search for a nice runviercing polygood song", unsure=True)
        self.assertIsNone(reply)
        bar.assert_not_called()
        self.assertEqual(self._run("pause", unsure=True)[0], "Paused.")  # controls are still fine

    def test_unknown_requests_go_to_the_ai(self):
        self.assertIsNone(self._run("what is this video about")[0])
        self.assertIsNone(self._run("subscribe to this channel")[0])


if __name__ == "__main__":
    unittest.main()
