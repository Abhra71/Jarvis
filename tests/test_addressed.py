"""Background speech is ignored (1 Oct, 21:23: a Hindi talk in the room became 8 "requests")."""

import json
import unittest
from unittest import mock

import numpy as np

from jarvis import addressed, assistant
from jarvis.config import ROOT

# Heard on 1 Oct, 21:23-21:26, with Whisper's confidence. None of it was said to Jarvis.
ROOM_TALK = [
    ("Ashwita Chhapya, Bhaari, Bidwa, Jidat, Nehi, Dekta, Munna, Svambe, Kumbhak, Mnuchichit, Aaptheg, Aadha, Drupal, "
     "Bhae, Nenge, Tjan, Vachka, Yudhna, Svachukka, Radhar, Kibid, Dvish, Sipudhar, Jhantan,", -1.38),
    ("Smebote, Merlite, Egerave, Malo, Beribato, Smebote.", -1.29),
    ("Kais, Kuch Nei, Xtos, Vier, Blach, Plox, Plox, Plox, Plox, Plox, Plox, Plox, Plox.", -0.45),
    ("Ska Sata Lui, Mishu, Hosh Kee, Dei, Beyo, Tsoe, Nen, Sopo, Nen. Now, Efin, Brahe, Sibing, Kuch, Nidok, Nave, "
     "Chara, Mhane Saag, Siparish, Chaita, Su, Pili, Garbi, Pagariji, Khaan, Khaan.", -0.37),
    ("I will come to the workshop alone. We will not be able to play anything. I will take care of you. I will go "
     "and do everything. I will go to the workshop. I will go. I do not go anywhere.", -1.58),
    ("Aapke saam ke, Aapche, Wabhola, Khutte, Girela, Tute, Girtol, Lillagin. Chhupi achcha nahi laga, leke, Aapke "
     "nahi sakte. Aapke nahi sakte. Chhupi aapke nahi laga, chhupi aapke nahi sakte.", -0.87),
    ("Nare, Vener, Jungle, Viral, Rave, Oral, Paisa, Kshudu, Vreem, All the tips, Oche, Ege, Jil, Nahi. Omini, "
     "Mnuchut, Tehri, Karne, Tere Vener, Faribol, Topic, Vitae, Rane, Pen, Pen, Tare, Pappe, Pappe, Naut, Hale.", -0.27),
    ("Graho.", -1.0),
]
NOISE = [("Tx.", -1.63)]  # 30 Sep, nothing was said
# 3 Oct: a lofi song on YouTube woke Jarvis (wake score 0.94) and its words were heard as requests.
SONG = [
    ("Moteur, Mnexia, Qoo, Mando, Gim, Dabu, Tadli, Tud.", -1.55),
    ("and Mundo Pocket 1v8, so this.", -1.31),
    ("And...", -0.35),
    ("Wapj, Oken.", -0.66),
    ("Xp, Xp, Xp, Xp, Xp.", -0.31),
]

# The user's real requests, including names that aren't English words and badly heard ones.
REQUESTS = [
    ("Search for Best Biryani in Kolkata.", -0.2),
    ("Connect Bluetooth to Rockerz 480.", -0.3),
    ("Open Khazana chemistry 2026.", -0.4),
    ("Open Ishq Jalakar.", -0.5),
    ("Open Clawd.", -0.7),
    ("Flipkart.", -0.4),
    ("Do you know Ranveer Singh?", -0.3),
    ("KMS 3, Khazana 2026.", -0.74),
    ("Whatever is there in the address bar, Cut it and Open Claude App.", -1.3),
    ("Curser and click on the placeholder which is named search for products brands and more.", -1.3),
    ("Apply all the coupons which is named here from Google Pay and Access Phone Pay Beam.", -1.3),
    ("On my screen, type that success is not the best form of revenge. It is the only form of revenge.", -1.3),
    ("I'm done. Yes.", -0.94),
    ("Close this tab and close the chess tab as well.", -0.9),
]


class BackgroundTest(unittest.TestCase):
    def test_the_room_talk_of_1_oct_is_ignored(self):
        for text, conf in ROOM_TALK:
            with self.subTest(text=text[:40]):
                self.assertIsNotNone(addressed.background_reason(text, conf, followup=True))

    def test_the_song_of_3_oct_is_ignored(self):
        for text, conf in SONG:
            with self.subTest(text=text):
                self.assertIsNotNone(addressed.background_reason(text, conf, followup=True))

    def test_real_requests_get_through(self):
        for text, conf in REQUESTS:
            with self.subTest(text=text):
                self.assertIsNone(addressed.background_reason(text, conf, followup=True))

    def test_right_after_hey_jarvis_only_clear_gibberish_is_dropped(self):
        self.assertIsNone(addressed.background_reason("Graho.", -1.0, followup=False))
        self.assertIsNotNone(addressed.background_reason(ROOM_TALK[1][0], -1.29, followup=False))

    def test_every_real_sentence_ever_said_with_its_real_confidence(self):
        """Regression: nothing the user said in a logged session (with the hearing it really had) is dropped,
        except the 1 Oct room talk."""
        room = {t for t, _ in ROOM_TALK + SONG + NOISE}
        history = ROOT / "data" / "heard-history.json"  # the logs before the 3 Oct trial, kept as sentences
        if not history.exists():
            self.skipTest("no data/heard-history.json on this PC")
        for e in json.loads(history.read_text(encoding="utf-8"))["tasks"]:
            if e["day"] > "2026-10-02":
                continue  # a fixed set: later days may hold new background talk (add it to the lists above)
            conf = e.get("confidence")
            if e.get("time", "").startswith("21:2") and e["day"] == "2026-10-01" or e.get("result") == "ignored":
                continue  # the room talk itself (some of it is cut short in ROOM_TALK)
            if e["said"] in room:
                continue
            with self.subTest(said=e["said"][:50]):
                self.assertIsNone(addressed.background_reason(e["said"], conf, followup=True))


class ConversationTest(unittest.TestCase):
    """The follow-up loop: ignored speech is never handled, and two in a row end the conversation."""

    def _run(self, heard: list[tuple[str, float]]):
        a = assistant.Assistant.__new__(assistant.Assistant)
        a.config = {"listen": {"followup_seconds": 5, "duck": False}}
        a.stopping, a.dictating, a.coding, a.gaming = mock.Mock(), False, False, False
        a.stopping.is_set.return_value = False
        a.mic, a.speaker, a.skills, a.state, a.on_state = mock.Mock(), mock.Mock(), mock.Mock(), None, lambda s: None
        a.skills.cancel.is_set.return_value = False
        a.stt = mock.Mock()
        queue = list(heard)

        def transcribe(_audio):
            text, conf = queue.pop(0)
            a.stt.last = {"source": "cloud", "confidence": conf, "unsure": conf < -0.35}
            a.stt.unsure = conf < -0.35
            return text

        a.stt.transcribe.side_effect = transcribe
        audio = [np.zeros(10, dtype=np.float32)] * len(heard) + [None]
        handled = []
        with mock.patch.object(assistant, "record_utterance", side_effect=audio), \
                mock.patch.object(assistant.tasklog, "write"), \
                mock.patch.object(a, "_handle_while_watching", side_effect=lambda t, u: handled.append(t) or "Done."):
            a._conversation()
        return handled, queue

    def test_two_ignored_in_a_row_go_back_to_sleep(self):
        handled, left = self._run([("Open Chrome.", -0.1)] + ROOM_TALK[:3])
        self.assertEqual(handled, ["Open Chrome."])
        self.assertEqual(len(left), 1)  # stopped listening after the second one

    def test_a_request_between_them_resets_the_count(self):
        handled, _ = self._run([("Open Chrome.", -0.1), ROOM_TALK[1], ("Close it.", -0.2), ROOM_TALK[1]])
        self.assertEqual(handled, ["Open Chrome.", "Close it."])


if __name__ == "__main__":
    unittest.main()


class BluetoothRouteTest(unittest.TestCase):
    """1 Oct: 'Connect Bluetooth to Rockerz 480' failed in code, then went to the AI and got stuck."""

    def test_the_device_name_is_clean(self):
        from jarvis import abilities
        for said in ("Connect Bluetooth to Rockerz 480.", "connect my bluetooth to rockers 480",
                     "connect to rockerz 480 via bluetooth"):
            with self.subTest(said=said):
                ab, value = abilities.match(said)
                self.assertEqual((ab.name, value.replace("rockers", "rockerz")), ("connect_bluetooth", "rockerz 480"))

    def test_a_failed_connect_is_the_answer_not_a_job_for_the_ai(self):
        from jarvis import abilities, corrections
        a = assistant.Assistant.__new__(assistant.Assistant)
        a.dictating, a.coding, a.gaming = False, False, False
        a.corrections = corrections.Corrections(None)
        a.last_request, a.fixed_request = "", None
        a.skills = mock.Mock()
        a.brain = mock.Mock(answer_agent=mock.Mock(return_value=None), agent=None)
        failed = "Not done: Rockerz 480 didn't connect. Is it switched on and near the laptop?"
        with mock.patch.object(assistant.sites, "handle", return_value=None), \
                mock.patch.object(abilities, "run", return_value=failed):
            route, reply = a._handle("Connect Bluetooth to Rockerz 480.")
        self.assertEqual((route, reply), ("ability", failed))
        a.brain.ask.assert_not_called()
