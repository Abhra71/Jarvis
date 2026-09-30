import unittest
from unittest import mock

from jarvis import notify


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.shown = []
        notify._shown.clear()
        notify._down.clear()
        notify.set_sink(lambda text, title: self.shown.append(text))
        self.patch = mock.patch.object(notify, "threading", mock.Mock(Thread=_Inline))
        self.patch.start()

    def tearDown(self):
        notify.set_sink(None)
        self.patch.stop()

    def test_back_popup_only_after_a_fallback(self):
        notify.recovered("voice", "back")
        self.assertEqual(self.shown, [])
        notify.fell_back("voice", "down")
        notify.fell_back("voice", "down")  # once a minute
        notify.recovered("voice", "back")
        notify.recovered("voice", "back")  # only once
        self.assertEqual(self.shown, ["down", "back"])

    def test_new_fallback_shows_again_after_recovery(self):
        notify.fell_back("hearing", "down")
        notify.recovered("hearing", "back")
        notify.fell_back("hearing", "down")
        self.assertEqual(self.shown, ["down", "back", "down"])



class _Inline:
    def __init__(self, target, args=(), **_):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


if __name__ == "__main__":
    unittest.main()
