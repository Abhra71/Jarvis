"""Failures said like a person (the real lines from the 30 Sep logs, before and after)."""

import unittest

from jarvis.agent import speech


class SpeechTest(unittest.TestCase):
    def test_stuck_lines_from_the_logs(self):
        cases = {
            "the page isn't https://www.clawedgame.com; it's https://pw.live/?redirectUrl=study-v2%2Fstudy.":
                "Clawedgame.com didn't open; I'm on pw.live. What should I do?",
            "CloudF isn't in front; explorer is.": "CloudF didn't come up. What should I do?",
            "WhatsApp isn't in front; chrome is.": "WhatsApp didn't come up; Chrome is in front. What should I do?",
            "the_brutal_revenge_not_ready isn't in front; explorer is.":
                "The brutal revenge not ready didn't come up. What should I do?",
            "chrome is still open.": "Chrome didn't close. What should I do?",
            "Nothing called 'Price: low to high' is on screen.":
                "I can't find Price: low to high on the screen. What should I do?",
            "I can't see Chemistry 2026 on screen in chrome.":
                "I can't see Chemistry 2026 on the screen. What should I do?",
            "the dialog box 'a dialog box' is still open.": "The box in front is still open. What should I do?",
            "A dialog box is open in front (a dialog box); it has to be answered first.":
                "There's a box open in front that needs an answer first. What should I do?",
            "the cursor isn't in a text box.": "I couldn't get into a text box. What should I do?",
            "the media is still playing.": "It's still playing. What should I do?",
            # 3 Oct live (BlueJ new class): the guard's note to the AI was read out.
            "Not done: the user didn't ask for more actions than you've already taken. Stop and report what "
            "happened; if something is still needed, ask the user first.":
                "That needed more steps than you asked for, so I stopped partway. What should I do?",
        }
        for why, said in cases.items():
            self.assertEqual(speech.stuck(why), said, why)

    def test_never_reads_lists_or_urls(self):
        said = speech.stuck('Not clicked: button "Maximize" isn\'t on screen any more. Current items: [1] link "x"')
        self.assertNotIn("[1]", said)
        said = speech.stuck("Sorry, I couldn't find an app called Clawed. Closest installed apps: claude, edge.")
        self.assertEqual(said, "I couldn't find an app called Clawed. What should I do?")
        self.assertNotIn("https", speech.problem("went to https://example.com/a?b=c instead"))

    def test_unconfirmed(self):
        self.assertEqual(speech.unconfirmed(["Pressed win+up."]), "I pressed Windows Up, but I can't tell if it worked.")
        self.assertEqual(speech.unconfirmed(["Pressed ctrl+a.", "Pressed delete."]),
                         "I pressed Delete, but I can't tell if it worked.")
        self.assertEqual(speech.unconfirmed(["Pressed alt+f4."]), "I pressed Alt F4, but I can't tell if it worked.")
        self.assertEqual(speech.unconfirmed(["Clicked the Edit menu item."]),
                         "I clicked Edit, but I can't tell if it worked.")
        self.assertEqual(speech.unconfirmed(["Typed it."]), "I typed it, but I can't tell if it worked.")


if __name__ == "__main__":
    unittest.main()
