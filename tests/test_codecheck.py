"""The compiler check (real javac / g++ when this PC has them; skipped otherwise). No screen."""

import unittest

from jarvis import codecheck as cc

GOOD = "public class Test\n{\n    public static void main(String[] args)\n    {\n        int i = 0;\n    }\n}"


@unittest.skipUnless(cc.available("java"), "no javac")
class JavaCheckTest(unittest.TestCase):
    def test_good_code_has_no_errors(self):
        self.assertEqual(cc.errors(GOOD, "java"), ())

    def test_missing_semicolon_found_and_fixed(self):
        bad = GOOD.replace("int i = 0;", "int i = 0")
        errs = cc.errors(bad, "java")
        self.assertEqual(errs[0].line, 5)
        self.assertEqual(errs[0].plain(), "line 5: a semicolon is missing")
        fixed, said = cc.quick_fix(bad, "java")
        self.assertEqual(fixed, GOOD)
        self.assertIn("line 5", said)

    def test_only_new_errors_count(self):
        theirs = GOOD.replace("int i = 0;", "int i = 0;\n        x = 1;")  # the student's own error
        mine = theirs.replace("int i = 0;", "int i = 0;\n        System.out.println(i);")
        self.assertEqual(cc.new_errors(theirs, mine, "java"), [])
        broke = theirs.replace("int i = 0;", "int i = 0;\n        y = 2;")
        self.assertEqual(len(cc.new_errors(theirs, broke, "java")), 1)

    def test_missing_brace_fixed(self):
        bad = GOOD[:-2]
        fixed, said = cc.quick_fix(bad, "java")
        self.assertEqual(cc.errors(fixed, "java"), ())


@unittest.skipUnless(cc.available("cpp"), "no g++")
class CppCheckTest(unittest.TestCase):
    def test_semicolon(self):
        bad = "#include <iostream>\nusing namespace std;\nint main() {\n    int i = 0\n    cout << i;\n}"
        self.assertTrue(cc.errors(bad, "cpp"))
        fixed, _ = cc.quick_fix(bad, "cpp")
        self.assertIn("int i = 0;", fixed)
        self.assertEqual(cc.errors(fixed, "cpp"), ())


if __name__ == "__main__":
    unittest.main()
