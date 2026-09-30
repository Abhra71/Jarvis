"""BlueJ 'create a new class called X' (30 Sep: the user asked four times and Jarvis got stuck each time)."""

import unittest
from unittest import mock

from jarvis import abilities
from jarvis.skills import editors


class NewClassTest(unittest.TestCase):
    def test_phrases(self):
        for said, value in [("Create a new class called Motivation.", "motivation"),
                            ("Create a new class and name it Motivation.", "motivation"),
                            ("make a class named digit sum check", "digit sum check"),
                            ("Create a new class called Motivation in BlueJ.", "motivation")]:
            hit = abilities.match(said)
            self.assertEqual((hit[0].name, hit[1]), ("bluej_new_class", value), said)
        self.assertEqual(abilities.match("create a new class")[0].name, "bluej_new_class")

    def test_class_names(self):
        self.assertEqual(editors.class_name("digit sum check"), "DigitSumCheck")
        self.assertEqual(editors.class_name("motivation"), "Motivation")
        self.assertIsNone(editors.class_name("2 fast"))
        self.assertIsNone(editors.class_name(""))

    def test_nothing_typed_without_a_bluej_project(self):
        with mock.patch.object(editors, "_project_window", return_value=(None, None)), \
                mock.patch.object(editors.desktop, "type_text") as typed:
            self.assertEqual(editors.new_class("motivation"), "Not done: no BlueJ project is open.")
        typed.assert_not_called()

    def test_existing_class_is_not_made_again(self):
        with mock.patch.object(editors, "_project_window", return_value=(1, "java")), \
                mock.patch.object(editors, "_class_buttons", return_value=[("Motivation", None)]), \
                mock.patch.object(editors.desktop, "type_text") as typed:
            self.assertEqual(editors.new_class("motivation"), "There's already a class called Motivation in java.")
        typed.assert_not_called()

    def test_types_only_into_bluejs_own_box(self):
        buttons = [[], [], [("Motivation", None)]]
        with mock.patch.object(editors, "_project_window", return_value=(1, "java")), \
                mock.patch.object(editors, "_class_buttons", side_effect=lambda h: buttons.pop(0) if buttons else []), \
                mock.patch.object(editors.desktop, "_focus"), mock.patch.object(editors.desktop, "_uia") as uia, \
                mock.patch.object(editors, "_centre_click"), mock.patch.object(editors.time, "sleep"), \
                mock.patch.object(editors.win32gui, "GetForegroundWindow", return_value=2), \
                mock.patch.object(editors.desktop, "_app_windows", return_value=[(2, "javaw", "BlueJ: New Class")]), \
                mock.patch.object(editors.desktop, "type_text") as typed, mock.patch.object(editors.keys, "press"):
            ui = mock.Mock()
            ui.ElementFromHandle.return_value.FindAll.return_value.Length = 1
            uia.return_value = (mock.Mock(), ui)
            self.assertEqual(editors.new_class("motivation"), "Created the class Motivation.")
        typed.assert_called_once_with("Motivation")

    def test_no_typing_when_the_box_never_opens(self):
        with mock.patch.object(editors, "_project_window", return_value=(1, "java")), \
                mock.patch.object(editors, "_class_buttons", return_value=[]), \
                mock.patch.object(editors.desktop, "_focus"), mock.patch.object(editors.desktop, "_uia") as uia, \
                mock.patch.object(editors, "_centre_click"), mock.patch.object(editors.time, "sleep"), \
                mock.patch.object(editors.time, "monotonic", side_effect=[0, 0, 1, 2, 4, 5, 6, 7]), \
                mock.patch.object(editors.win32gui, "GetForegroundWindow", return_value=1), \
                mock.patch.object(editors.desktop, "_app_windows", return_value=[(1, "javaw", "BlueJ: java")]), \
                mock.patch.object(editors.desktop, "type_text") as typed:
            ui = mock.Mock()
            ui.ElementFromHandle.return_value.FindAll.return_value.Length = 1
            uia.return_value = (mock.Mock(), ui)
            self.assertEqual(editors.new_class("motivation"), "Not done: BlueJ's New Class box didn't open.")
        typed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
