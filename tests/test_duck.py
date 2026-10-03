"""Ducking: apps go down while Jarvis listens and ALL of their sound comes back up (3 Oct: Chrome stuck at 12%)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.skills import volume


class _Vol:
    def __init__(self, level):
        self.level = level

    def GetMasterVolume(self):
        return self.level

    def SetMasterVolume(self, level, _):
        self.level = level


class _Proc:
    def __init__(self, name, pid=1):
        self._name, self.pid = name, pid

    def name(self):
        return self._name


class _Session:
    def __init__(self, name, level):
        self.Process, self.SimpleAudioVolume = _Proc(name), _Vol(level)


class DuckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "ducked.json"
        patcher = mock.patch.object(volume, "_DUCKED", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_sound_that_started_while_ducked_comes_back_up(self):
        old = _Session("chrome.exe", 1.0)
        sessions = [old]
        with mock.patch.object(volume.AudioUtilities, "GetAllSessions", lambda: sessions):
            saved = volume.duck()
            self.assertAlmostEqual(old.SimpleAudioVolume.level, 0.12)
            new = _Session("chrome.exe", 0.12)  # YouTube's new tab started playing while Jarvis listened
            sessions.append(new)
            volume.restore(saved)
        self.assertEqual(old.SimpleAudioVolume.level, 1.0)
        self.assertEqual(new.SimpleAudioVolume.level, 1.0)
        self.assertFalse(self.file.exists())

    def test_a_jarvis_stopped_while_ducked_puts_the_sound_back_at_start(self):
        chrome = _Session("chrome.exe", 0.8)
        with mock.patch.object(volume.AudioUtilities, "GetAllSessions", lambda: [chrome]):
            volume.duck()  # …and Jarvis is killed here
            self.assertTrue(self.file.exists())
            volume.recover()
        self.assertAlmostEqual(chrome.SimpleAudioVolume.level, 0.8)
        self.assertFalse(self.file.exists())

    def test_other_apps_are_left_alone(self):
        spotify = _Session("spotify.exe", 0.3)
        with mock.patch.object(volume.AudioUtilities, "GetAllSessions", lambda: [spotify]):
            volume.restore([(_Vol(0.12), 1.0, "chrome.exe")])
        self.assertEqual(spotify.SimpleAudioVolume.level, 0.3)


if __name__ == "__main__":
    unittest.main()
