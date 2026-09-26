import unittest

from jarvis.nlu import Intent, parse, parse_duration, words_to_digits

CASES = {
    "Open Chrome.": Intent("open_app", {"app": "chrome"}),
    "Hey Jarvis, please open the file explorer": Intent("open_app", {"app": "file explorer"}),
    "Launch Spotify app": Intent("open_app", {"app": "spotify"}),
    "Set volume to 40%.": Intent("set_volume", {"level": 40}),
    "Volume twenty five": Intent("set_volume", {"level": 25}),
    "Turn the volume up": Intent("change_volume", {"direction": 1}),
    "Lower the volume": Intent("change_volume", {"direction": -1}),
    "Louder": Intent("change_volume", {"direction": 1}),
    "Mute.": Intent("mute", {"on": True}),
    "Unmute": Intent("mute", {"on": False}),
    "Search for Python tutorials": Intent("web_search", {"query": "python tutorials"}),
    "Google weather in Kolkata": Intent("web_search", {"query": "weather in kolkata"}),
    "Set a timer for 5 minutes.": Intent("set_timer", {"seconds": 300}),
    "Timer for one hour and thirty minutes": Intent("set_timer", {"seconds": 5400}),
    "Set a timer for a minute": Intent("set_timer", {"seconds": 60}),
    "Set a timer": Intent("set_timer", {"seconds": None}),
    "Cancel the timer": Intent("cancel_timer"),
    "What time is it?": Intent("tell_time"),
    "What's the time": Intent("tell_time"),
    "Tell me a joke": None,
    "": None,
}


class ParseTest(unittest.TestCase):
    def test_cases(self):
        for text, expected in CASES.items():
            with self.subTest(text=text):
                self.assertEqual(parse(text), expected)

    def test_words_to_digits(self):
        self.assertEqual(words_to_digits("set a timer for twenty five minutes"), "set a timer for 25 minutes")
        self.assertEqual(words_to_digits("a hundred"), "100")

    def test_duration(self):
        self.assertEqual(parse_duration("1 hour 2 minutes 3 seconds"), 3723)
        self.assertIsNone(parse_duration("no numbers"))


if __name__ == "__main__":
    unittest.main()
