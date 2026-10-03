"""Coding mode end to end with a pretend editor (no screen): the user's 3 Oct session, undo, noise, AI with a yes."""

import unittest
from unittest import mock

from jarvis import codecheck, codemode
from jarvis.skills import editors


class FakeEditor(editors.Editor):
    """Holds the code and the cursor like BlueJ does; nothing on screen."""
    name = "BlueJ"
    lang = "java"
    cheap_read = True

    def __init__(self, text="", cursor=0, title="Test - Scratch", lang="java"):
        self.text_, self.cursor, self.title, self.lang = text, cursor, title, lang
        self.writes = 0

    @property
    def file_class(self):
        return self.title.split(" - ")[0]

    def read(self, keep_cursor=True):
        return self.text_, self.cursor

    def write(self, text, cursor):
        self.writes += 1
        self.text_, self.cursor = text, cursor
        return "ok"

    def place(self, line):
        self.cursor = line

    def insert_below(self, lines, up):
        ls = self.text_.split("\n")
        k = self.cursor + 1
        self.text_ = "\n".join(ls[:k] + lines + ls[k:])
        self.cursor = k + len(lines) - 1 - up
        return True


def say(cm, ed, text, unsure=False):
    with mock.patch.object(codemode, "_popup"):
        return cm.handle(text, ed, unsure)


class SessionTest(unittest.TestCase):
    def test_the_3_oct_session(self):
        ed, cm = FakeEditor(), codemode.CodeMode()
        self.assertEqual(say(cm, ed, "Create a class."), "Added the class Test.")
        self.assertEqual(say(cm, ed, "Create a main method."), "Added the main method.")
        self.assertEqual(say(cm, ed, "Initialize i is equal to 0."), "Added int i equals 0.")
        self.assertEqual(say(cm, ed, "Wrap this inside the main method."), "That's already inside main.")
        self.assertEqual(ed.text_.count("class Test"), 1)
        self.assertEqual(ed.text_.count("void main"), 1)
        self.assertEqual(say(cm, ed, "Print i."), "Added print line i.")
        self.assertIn("        System.out.println(i);", ed.text_)
        if codecheck.available("java"):
            self.assertEqual(codecheck.errors(ed.text_, "java"), ())
        # asked again: nothing is made twice
        self.assertIn("already", say(cm, ed, "Create a main method."))
        self.assertIn("already", say(cm, ed, "create a class called test"))

    def test_undo_takes_back_only_jarvis_last_change(self):
        ed, cm = FakeEditor(), codemode.CodeMode()
        say(cm, ed, "create a class")
        say(cm, ed, "create a main method")
        before = ed.text_
        say(cm, ed, "int sum equals 0")
        self.assertIn("int sum = 0;", ed.text_)
        self.assertEqual(say(cm, ed, "undo"), "Undone: added int sum equals 0.")
        self.assertEqual(ed.text_, before)
        self.assertEqual(say(cm, ed, "redo"), "Redone: added int sum equals 0.")
        self.assertIn("int sum = 0;", ed.text_)
        ed.text_ += "\n// the user's own edit"
        self.assertIn("won't undo over it", say(cm, ed, "undo"))

    def test_noise_is_never_code(self):
        """30 Sep: 'Ect.', 'Rongen.', 'VS Code.' became methods."""
        ed, cm = FakeEditor("public class Test\n{\n}", 1), codemode.CodeMode(think=mock.Mock())
        for noise in ("Ect.", "Rongen.", "Tshimun."):
            self.assertEqual(say(cm, ed, noise, unsure=True), "")
        self.assertEqual(ed.writes, 0)
        cm.think.assert_not_called()
        self.assertIsNone(say(cm, ed, "Open Chrome."))  # a normal request, not code

    def test_ai_code_is_offered_then_written_on_yes(self):
        method = ("public static boolean isPrime(int n)\n{\n    for (int i = 2; i < n; i++)\n    {\n"
                  "        if (n % i == 0)\n        {\n            return false;\n        }\n    }\n    return n > 1;\n}")
        ed = FakeEditor("public class Test\n{\n    public static void main(String[] args)\n    {\n        int i = 0;\n"
                        "    }\n}", 4)
        cm = codemode.CodeMode(think=lambda system, user: method)
        reply = say(cm, ed, "write a method that checks if a number is prime")
        self.assertIn("Shall I write it?", reply)
        self.assertNotIn("isPrime", ed.text_)
        self.assertEqual(say(cm, ed, "yes"), "Added the method isPrime.")
        main_end = ed.text_.index("    }\n", ed.text_.index("void main"))
        self.assertGreater(ed.text_.index("isPrime"), main_end)  # inside the class, after main, not in main
        if codecheck.available("java"):
            self.assertEqual(codecheck.errors(ed.text_, "java"), ())

    def test_no_drops_the_offer(self):
        ed = FakeEditor("public class Test\n{\n}", 1)
        cm = codemode.CodeMode(think=lambda s, u: "public void hello()\n{\n    System.out.println(\"hi\");\n}")
        say(cm, ed, "write a method called hello that prints hi")
        self.assertEqual(say(cm, ed, "no"), "Okay, I didn't write it.")
        self.assertNotIn("hello", ed.text_)

    @unittest.skipUnless(codecheck.available("java"), "no javac")
    def test_a_move_that_would_break_the_code_is_refused(self):
        code = ("public class Test\n{\n    public static void main(String[] args)\n    {\n        int i = 0;\n"
                "        System.out.println(i);\n    }\n\n    static void show()\n    {\n    }\n}")
        ed, cm = FakeEditor(code, 4), codemode.CodeMode()
        reply = say(cm, ed, "move line 5 into the show method")
        self.assertIn("would break the code", reply)
        self.assertEqual(ed.text_, code)

    def test_wrap_in_a_loop_and_rename(self):
        code = ("public class Test\n{\n    public static void main(String[] args)\n    {\n"
                "        System.out.println(\"hi\");\n    }\n}")
        ed, cm = FakeEditor(code, 4), codemode.CodeMode()
        self.assertIn("Put that inside", say(cm, ed, "put line 5 inside a for loop with i from 1 to 3"))
        self.assertIn("for (int i = 1; i <= 3; i++)", ed.text_)
        self.assertIn("Renamed i to k", say(cm, ed, "rename i to k"))
        self.assertIn("for (int k = 1; k <= 3; k++)", ed.text_)

    @unittest.skipUnless(codecheck.available("java"), "no javac")
    def test_fix_the_errors(self):
        code = "public class Test\n{\n    public static void main(String[] args)\n    {\n        int i = 0\n    }\n}"
        ed, cm = FakeEditor(code, 4), codemode.CodeMode()
        reply = say(cm, ed, "fix the errors")
        self.assertIn("semicolon", reply)
        self.assertIn("int i = 0;", ed.text_)
        self.assertEqual(say(cm, ed, "check my code"), "No errors. The code compiles.")

    def test_cursor_commands(self):
        code = ("public class Test\n{\n    public static void main(String[] args)\n    {\n"
                "        for (int i = 0; i < 3; i++)\n        {\n            i++;\n        }\n    }\n}")
        ed, cm = FakeEditor(code, 0), codemode.CodeMode()
        self.assertEqual(say(cm, ed, "move the cursor inside the main method"), "In main.")
        self.assertEqual(ed.cursor, 7)
        ed.cursor = 6
        self.assertEqual(say(cm, ed, "come out of the loop"), "After the for.")
        self.assertEqual(ed.cursor, 7)
        say(cm, ed, "print done")
        self.assertIn('        }\n        System.out.println("done");\n    }', ed.text_)

    def test_clear_needs_a_yes_and_can_be_undone(self):
        code = "public class Test\n{\n}"
        ed, cm = FakeEditor(code, 1), codemode.CodeMode()
        self.assertIn("Say yes", say(cm, ed, "delete everything"))
        self.assertEqual(ed.text_, code)
        say(cm, ed, "yes")
        self.assertEqual(ed.text_, "")
        say(cm, ed, "undo")
        self.assertEqual(ed.text_, code)


class ThirtySeptemberTest(unittest.TestCase):
    """Every sentence of the 30 Sep coding session (BlueJ, class 'test'), with what it must do now. Then it
    made methods out of noise ('Ect.' -> 'public void ect()'), and a second class and main for 'wrap this'."""

    NOISE = ["Tshimun.", "Ect.", "Rongen.", "Ssss.", "VS Code.", "Mines.", "Epsi.", "IOS Stream,"]
    NOT_CODE = ["Optimize the screen.", "Can you type something on my screen?"]

    def test_noise_and_requests_write_nothing(self):
        ed = FakeEditor("public class test\n{\n}", 1, title="test - java")
        cm = codemode.CodeMode(think=mock.Mock(side_effect=AssertionError("no AI for noise")))
        for said in self.NOISE:
            with self.subTest(said=said):
                self.assertEqual(say(cm, ed, said, unsure=True), "")
        for said in self.NOT_CODE:
            with self.subTest(said=said):
                self.assertIsNone(say(cm, ed, said))  # a normal request: Jarvis handles it as usual
        self.assertEqual(ed.writes, 0)
        self.assertEqual(ed.text_, "public class test\n{\n}")

    def test_the_session_builds_one_class_with_one_main(self):
        ed = FakeEditor("", 0, title="test - java")
        cm = codemode.CodeMode()
        say(cm, ed, "Create a class called Test.")
        say(cm, ed, "Public static void main.")
        say(cm, ed, "I want public static void main inside the class test.")
        self.assertEqual(say(cm, ed, "Move inside the main class or main method."), "In main.")
        self.assertEqual(say(cm, ed, "Move the cursor inside the main method."), "In main.")
        say(cm, ed, "Initialize variable i is equal to 0.")
        self.assertEqual(say(cm, ed, "Wrap this inside class test inside main method."), "That's already inside main.")
        say(cm, ed, "Now write a for loop where i is equal to 0, i is less than 10, i++.")
        say(cm, ed, "System. out. print IE")
        self.assertEqual(say(cm, ed, "Control plus A."), "Selected everything.")
        code = ed.text_
        self.assertEqual(code.count("class"), 1)
        self.assertEqual(code.count("void main"), 1)
        self.assertIn("int i = 0;", code)
        self.assertIn("for (i = 0; i < 10; i++)", code)
        self.assertIn('System.out.print("IE");', code)
        if codecheck.available("java"):
            self.assertEqual(codecheck.errors(code, "java"), ())


class ArraysAndNavigationTest(unittest.TestCase):
    """3 Oct, the user: 'create a 2D array of data type int with name ARR', and moving by line numbers."""

    CODE = ("public class Test\n{\n    public static void main(String[] args)\n    {\n        int i = 0;\n    }\n}")

    def test_2d_array_asks_the_size_then_writes_it(self):
        ed, cm = FakeEditor(self.CODE, 4), codemode.CodeMode()
        self.assertEqual(say(cm, ed, "Create a 2D array of data type int with name ARR."),
                         "How many rows and columns? Say it like: 2D int array arr with 3 rows and 4 columns.")
        self.assertEqual(ed.writes, 0)
        self.assertIn("Added", say(cm, ed, "3 rows and 4 columns"))
        self.assertIn("        int[][] ARR = new int[3][4];", ed.text_)

    def test_array_in_one_go_and_in_cpp(self):
        ed, cm = FakeEditor(self.CODE, 4), codemode.CodeMode()
        say(cm, ed, "make an int array called nums of size 5")
        self.assertIn("int[] nums = new int[5];", ed.text_)
        cpp = FakeEditor("int main() {\n    return 0;\n}", 0, title="a.cpp - Visual Studio Code", lang="cpp")
        say(cm, cpp, "create a 2d int array called grid with 3 rows and 3 columns")
        self.assertIn("    int grid[3][3];", cpp.text_)

    def test_navigation(self):
        ed, cm = FakeEditor(self.CODE, 4), codemode.CodeMode()
        ed.caret_line = lambda: ed.cursor + 1
        self.assertEqual(say(cm, ed, "go to the end of the file"), "At the end, line 7.")
        self.assertEqual(say(cm, ed, "go to the top"), "At the top.")
        self.assertEqual(say(cm, ed, "go down 4 lines"), "Line 5.")
        self.assertEqual(say(cm, ed, "next line"), "Line 6.")
        self.assertEqual(say(cm, ed, "previous line"), "Line 5.")
        self.assertEqual(say(cm, ed, "read line 5"), "Line 5: int i equals 0.")
        self.assertEqual(say(cm, ed, "what's on this line"), "Line 5: int i equals 0.")
        self.assertEqual(ed.writes, 0)


if __name__ == "__main__":
    unittest.main()
