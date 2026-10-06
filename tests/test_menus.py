"""Right-click menus in any app (5 Oct: 'delete the class Oval' in BlueJ could never work: no right-click, and the
menu is its own pop-up window). Deleting needs the user's yes but is never blocked. No real screen is touched."""

import unittest
from unittest import mock

import jarvis.usage
from jarvis.skills import elements
from jarvis.skills.elements import Element


def setUpModule():
    jarvis.usage.usage.persist = False


def _skills():
    from jarvis.skills import Skills
    with mock.patch("jarvis.skills.AppLauncher"), mock.patch("jarvis.skills.Browser"):
        return Skills({"volume": {"step": 10}, "apps": {}}, announce=print)


ITEMS = [Element("tab", "scratch", (0, 0, 50, 20)), Element("button", "scratch", (60, 0, 110, 20)),
         Element("list item", "scratch", (0, 100, 200, 120)), Element("button", "Oval Class: Uncompiled", (300, 300, 380, 360))]
MENU = [Element("menu item", "Open Editor", (0, 0, 9, 9)), Element("menu item", "Delete", (0, 10, 9, 19))]


class MatchKindTest(unittest.TestCase):
    def test_the_kind_picks_between_items_with_the_same_name(self):
        self.assertEqual(elements.match(ITEMS, "scratch", "file")[0].kind, "list item")
        self.assertEqual(elements.match(ITEMS, "scratch", "tab")[0].kind, "tab")
        self.assertEqual(elements.match(ITEMS, "Oval", "class")[0].name, "Oval Class: Uncompiled")


class MenuToolTest(unittest.TestCase):
    def setUp(self):
        self.s = _skills()
        self.s.budget = None
        for p in (mock.patch.object(elements, "read_front", return_value=ITEMS),
                  mock.patch.object(elements, "open_menu", return_value=MENU),
                  mock.patch.object(elements, "choose", return_value=(True, "Chose Delete.")),
                  mock.patch("jarvis.skills.desktop.front_window", return_value="javaw: BlueJ: JarvisScratch")):
            p.start()
            self.addCleanup(p.stop)

    def test_right_click_lists_the_menu(self):
        out = self.s.call("right_click", {"name": "Oval", "kind": "class"})
        self.assertIn("Delete", out)
        self.assertIn("Oval", out)

    def test_delete_asks_for_a_yes_then_is_done(self):
        self.s.call("right_click", {"name": "Oval", "kind": "class"})
        out = self.s.call("choose_menu_item", {"name": "Delete"})
        self.assertTrue(out.startswith("Needs confirmation"), out)
        elements.choose.assert_not_called()
        self.s.confirmed = True  # the user said yes
        self.assertEqual(self.s.call("choose_menu_item", {"name": "Delete"}), "Chose Delete.")

    def test_a_harmless_item_needs_no_yes(self):
        self.s.call("right_click", {"name": "Oval", "kind": "class"})
        self.s.call("choose_menu_item", {"name": "Open Editor"})
        elements.choose.assert_called_once_with("Open Editor")


if __name__ == "__main__":
    unittest.main()
