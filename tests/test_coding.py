"""Coding mode (30 Sep): speech -> Java (BlueJ) / C++ (VS Code), the common patterns in code."""

import unittest

from jarvis.coding import CURSOR, identifiers, needs_scanner, translate

CODE = "int sum = 0; int n; int sumOfDigits;"


class TranslateTest(unittest.TestCase):
    def check(self, said, java, cpp):
        self.assertEqual(translate(said, "java", CODE), java, said)
        self.assertEqual(translate(said, "cpp", CODE), cpp, said)

    def test_print(self):
        self.check("print hello world", 'System.out.println("hello world");', 'cout << "hello world" << endl;')
        self.check("System out println Hello World", 'System.out.println("Hello World");',
                   'cout << "Hello World" << endl;')
        self.check("system out print sum", "System.out.print(sum);", "cout << sum;")
        self.check("print sum is then sum", 'System.out.println("sum is " + sum);', 'cout << "sum is " << sum << endl;')
        self.check("print sum of digits", "System.out.println(sumOfDigits);", "cout << sumOfDigits << endl;")

    def test_variables_and_input(self):
        self.check("int sum equals zero", "int sum = 0;", "int sum = 0;")
        self.check("declare a string name equals Abhra", 'String name = "Abhra";', 'string name = "Abhra";')
        self.check("input int x", "int x = sc.nextInt();", "int x;\ncin >> x;")
        self.check("input int n", "n = sc.nextInt();", "cin >> n;")

    def test_blocks_follow_the_users_style(self):
        self.assertEqual(translate("for i from 1 to 10", "java", CODE), f"for (int i = 1; i <= 10; i++)\n{{\n    {CURSOR}\n}}")
        self.assertEqual(translate("for i from 1 to 10", "cpp", CODE), f"for (int i = 1; i <= 10; i++) {{\n    {CURSOR}\n}}")
        self.assertEqual(translate("if n mod 2 equals 0", "cpp", CODE), f"if (n % 2 == 0) {{\n    {CURSOR}\n}}")
        self.assertEqual(translate("while n not equal to 0", "java", CODE), f"while (n != 0)\n{{\n    {CURSOR}\n}}")
        self.assertEqual(translate("for i from 10 down to 1", "cpp", CODE).split(" {")[0], "for (int i = 10; i >= 1; i--)")

    def test_small_statements(self):
        self.check("sum plus equals n mod 10", "sum += n % 10;", "sum += n % 10;")
        self.check("n equals n divided by 10", "n = n / 10;", "n = n / 10;")
        self.check("increase sum by 2", "sum += 2;", "sum += 2;")
        self.check("return sum", "return sum;", "return sum;")
        self.assertIsNone(translate("make a function that checks prime", "java", CODE))  # the AI's job

    def test_scanner_is_added_when_missing(self):
        self.assertEqual(needs_scanner("int n = sc.nextInt();", "public class A {}"), ["import", "scanner"])
        self.assertEqual(needs_scanner("int n = sc.nextInt();", "import java.util.*;\nScanner sc = new Scanner(System.in);"), [])
        self.assertEqual(identifiers("int a = 5; for (int i = 0;"), {"a", "i"})


if __name__ == "__main__":
    unittest.main()
