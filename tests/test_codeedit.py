"""Coding mode's structure edits (no screen): the 3 Oct complaint and the 30 Sep session's sentences."""

import unittest

from jarvis import codeedit as ce
from jarvis.skills.editors import CURSOR

TEST_CLASS = """public class Test
{
    public static void main(String[] args)
    {
        int i = 0;
    }
}"""


def lines_of(e):
    return e.text.split("\n")


class ReadTest(unittest.TestCase):
    def test_blocks(self):
        bl = ce.blocks(TEST_CLASS)
        self.assertEqual([(b.kind, b.name, b.head, b.open, b.close) for b in bl],
                         [("class", "Test", 0, 1, 6), ("method", "main", 2, 3, 5)])

    def test_brackets_in_strings_and_comments_dont_count(self):
        code = 'class A {\n    void f() {\n        String s = "}{";  // }\n        char c = \'{\';\n    }\n}'
        self.assertIsNone(ce.problem(code))
        self.assertEqual([b.name for b in ce.blocks(code)], ["A", "f"])

    def test_unbalanced(self):
        self.assertIn("never closed", ce.problem("class A {\n void f() {\n}"))
        with self.assertRaises(ce.Unbalanced):
            ce.blocks("class A {\n void f() {\n}")

    def test_style(self):
        self.assertTrue(ce.allman(TEST_CLASS, "cpp"))
        self.assertFalse(ce.allman("int main() {\n    return 0;\n}", "java"))
        self.assertTrue(ce.allman("", "java"))
        self.assertFalse(ce.allman("", "cpp"))


class TheUsersSessionTest(unittest.TestCase):
    """3 Oct: 'create a class, create a main method, initialize i equals 0, then wrap this inside the main
    method' made a second class and main. Now each step finds what's there."""

    def test_class_main_variable_wrap(self):
        e = ce.ensure_class("", "Test", "java")
        self.assertEqual(e.text, "public class Test\n{\n    \n}")
        self.assertEqual(e.cursor, 2)
        e = ce.ensure_main(e.text, "java", "Test")
        self.assertEqual(e.text.count("class Test"), 1)
        self.assertEqual(e.text.count("void main"), 1)
        self.assertIsNone(ce.problem(e.text))
        e = ce.insert(e.text, e.cursor, "int i = 0;", "java", "Test")
        self.assertEqual(e.text, TEST_CLASS)
        self.assertEqual(e.said, "Added int i equals 0.")
        # "wrap this inside the main method": it's already there; nothing new is made
        w = ce.move_into(e.text, e.lines, "main", "java", "Test")
        self.assertFalse(w.changed)
        self.assertEqual(w.said, "That's already inside main.")
        # asked twice: still one class, one main
        self.assertFalse(ce.ensure_class(e.text, "test", "java").changed)
        self.assertFalse(ce.ensure_main(e.text, "java", "Test").changed)

    def test_a_statement_outside_any_method_goes_into_main(self):
        code = "public class Test\n{\n    \n}"
        e = ce.insert(code, 2, "int i = 0;", "java", "Test")
        self.assertIn("public static void main(String[] args)", e.text)
        self.assertEqual(e.text.count("int i = 0;"), 1)
        self.assertIsNone(ce.problem(e.text))
        self.assertEqual(e.said, "Added int i equals 0 in a new main method.")
        main = ce.find(e.text, "method", "main")
        self.assertTrue(main.open < e.cursor < main.close)

    def test_wrap_a_class_level_line_into_main(self):
        code = "public class Test\n{\n    int i = 0;\n\n    public static void main(String[] args)\n    {\n    }\n}"
        e = ce.move_into(code, (2, 2), "main", "java", "Test")
        self.assertEqual(e.text, "public class Test\n{\n    public static void main(String[] args)\n    {\n"
                                 "        int i = 0;\n    }\n}")
        self.assertEqual(e.said, "Moved int i equals 0 into main.")

    def test_wrap_into_main_that_doesnt_exist_makes_one(self):
        code = "public class Test\n{\n    int i = 0;\n}"
        e = ce.move_into(code, (2, 2), "main", "java", "Test")
        self.assertEqual(e.text.count("void main"), 1)
        self.assertEqual(e.text.count("int i = 0;"), 1)
        main = ce.find(e.text, "method", "main")
        self.assertTrue(main.open < e.text.split("\n").index("        int i = 0;") < main.close)

    def test_a_file_with_no_class_gets_the_editors_class(self):
        e = ce.insert("", 0, "System.out.println(i);", "java", "Shape")
        self.assertTrue(e.text.startswith("public class Shape\n{"))
        self.assertIn("        System.out.println(i);", e.text)
        self.assertIsNone(ce.problem(e.text))


class InsertTest(unittest.TestCase):
    def test_at_the_cursor_inside_a_method(self):
        e = ce.insert(TEST_CLASS, 4, "System.out.println(i);", "java")
        self.assertEqual(lines_of(e)[5], "        System.out.println(i);")
        self.assertEqual(e.cursor, 5)

    def test_on_a_blank_line_it_goes_on_that_line(self):
        code = TEST_CLASS.replace("        int i = 0;", "        int i = 0;\n        ")
        e = ce.insert(code, 5, "i++;", "java")
        self.assertEqual(lines_of(e)[5], "        i++;")
        self.assertEqual(len(lines_of(e)), len(code.split("\n")))

    def test_a_loop_puts_the_cursor_inside(self):
        e = ce.insert(TEST_CLASS, 4, f"for (int k = 1; k <= 10; k++)\n{{\n    {CURSOR}\n}}", "java")
        ls = lines_of(e)
        self.assertEqual(ls[5:9], ["        for (int k = 1; k <= 10; k++)", "        {", "            ", "        }"])
        self.assertEqual(e.cursor, 7)
        e2 = ce.insert(e.text, e.cursor, "System.out.println(k);", "java")
        self.assertEqual(lines_of(e2)[7], "            System.out.println(k);")

    def test_cursor_on_a_loop_header_goes_inside_it(self):
        code = "class A\n{\n    void f()\n    {\n        for (int k = 0; k < 3; k++)\n        {\n        }\n    }\n}"
        e = ce.insert(code, 4, "k++;", "java")
        self.assertEqual(lines_of(e)[6], "            k++;")

    def test_cursor_on_a_closing_brace_goes_after_it(self):
        code = "class A\n{\n    void f()\n    {\n        while (x)\n        {\n            x = false;\n        }\n    }\n}"
        e = ce.insert(code, 7, "return;", "java")
        self.assertEqual(lines_of(e)[8], "        return;")

    def test_cpp_style_and_main_return(self):
        code = "#include <iostream>\nusing namespace std;\n\nint main() {\n    return 0;\n}"
        e = ce.insert(code, None, "int n;\ncin >> n;", "cpp", last_method="main")
        self.assertEqual(lines_of(e)[4:7], ["    int n;", "    cin >> n;", "    return 0;"])
        e = ce.insert(e.text, 5, f"for (int i = 0; i < n; i++) {{\n    {CURSOR}\n}}", "cpp")
        self.assertIn("    for (int i = 0; i < n; i++) {", e.text)

    def test_java_snippet_restyled_for_a_same_line_file(self):
        code = "public class A {\n    void f() {\n        int x = 1;\n    }\n}"
        e = ce.insert(code, 2, f"if (x > 0)\n{{\n    {CURSOR}\n}}", "java")
        self.assertIn("        if (x > 0) {", e.text)
        self.assertIsNone(ce.problem(e.text))

    def test_a_method_goes_in_the_class_not_in_main(self):
        e = ce.insert(TEST_CLASS, 4, "public static int square(int x)\n{\n    return x * x;\n}", "java")
        sq = ce.find(e.text, "method", "square")
        main = ce.find(e.text, "method", "main")
        cls = ce.find(e.text, "class")
        self.assertTrue(main.close < sq.head and sq.close < cls.close)
        self.assertEqual(e.said, "Added the method square.")
        self.assertIsNone(ce.problem(e.text))

    def test_a_method_that_exists_isnt_made_again(self):
        e = ce.insert(TEST_CLASS, 4, f"public static void main(String[] args)\n{{\n    {CURSOR}\n}}", "java")
        self.assertFalse(e.changed)

    def test_cpp_function_goes_before_main(self):
        code = "int main() {\n    return 0;\n}"
        e = ce.insert(code, 1, "int square(int x) {\n    return x * x;\n}", "cpp")
        self.assertTrue(e.text.startswith("int square(int x) {"))
        self.assertLess(e.text.index("square"), e.text.index("main"))


class OtherEditsTest(unittest.TestCase):
    def test_wrap_in_a_loop(self):
        e = ce.wrap_in(TEST_CLASS, (4, 4), "for (int k = 0; k < 3; k++)", "java")
        self.assertEqual(lines_of(e)[4:8], ["        for (int k = 0; k < 3; k++)", "        {",
                                            "            int i = 0;", "        }"])

    def test_extract_method(self):
        e = ce.extract_method(TEST_CLASS, (4, 4), "setUp", "java")
        self.assertIn("        setUp();", e.text)
        self.assertIn("    public static void setUp()", e.text)
        self.assertIsNone(ce.problem(e.text))

    def test_rename_skips_strings(self):
        code = 'int sum = 0;\nSystem.out.println("sum is " + sum);'
        e = ce.rename(code, "sum", "total")
        self.assertEqual(e.text, 'int total = 0;\nSystem.out.println("sum is " + total);')

    def test_delete_never_leaves_a_lone_bracket(self):
        with self.assertRaises(ValueError):
            ce.delete_lines(TEST_CLASS, (6, 6))
        e = ce.delete_lines(TEST_CLASS, (4, 4))
        self.assertNotIn("int i", e.text)

    def test_block_span(self):
        self.assertEqual(ce.block_span(TEST_CLASS, 2), (2, 5))
        self.assertEqual(ce.block_span(TEST_CLASS, 4), (4, 4))


if __name__ == "__main__":
    unittest.main()


class CppHeadersTest(unittest.TestCase):
    """3 Oct live: a new C++ file's main had no includes, so cin 'wasn't declared'."""

    def test_added_when_needed(self):
        code = "int main() {\n    int n;\n    cin >> n;\n    return 0;\n}"
        out, added = ce.cpp_headers(code)
        self.assertEqual(out.split("\n")[:3], ["#include <iostream>", "using namespace std;", ""])
        self.assertEqual(added, 3)

    def test_nothing_twice(self):
        code = "#include <iostream>\nusing namespace std;\n\nint main() {\n    string s;\n    cout << s;\n}"
        self.assertEqual(ce.cpp_headers(code), (code, 0))
        self.assertEqual(ce.cpp_headers("int main() {\n    return 0;\n}")[1], 0)
        self.assertEqual(ce.cpp_headers("#include <bits/stdc++.h>\nint main() { cout << 1; }")[1], 0)
