"""The coding gold set: what was said, the file it was said on, and what the result must be.

    .venv\\Scripts\\python tools\\gold_coding.py        # writes data/gold/coding.jsonl

Two sources, always marked:
- "user": the user's REAL coding sentences from the 3 and 5 Oct sessions (BlueJ and VS Code), on the file they
  had at that moment.
- "written": Java/C++ requests phrased the way a student says them (strings, arrays, loops, conditions, input,
  methods, classes, edits). Written by the builder to cover what the user said they will ask for ("everything
  about Java I know"); replaced by real sentences as the user's trials add them.

Each case is checked by the REAL compiler (javac / g++) and by patterns the result must (has) or must not (not)
contain. "expect": "ask" means the right answer is a question (unclear, or it would break the code, e.g. a
variable declared twice). "cursor" cases expect only a cursor move.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gold" / "coding.jsonl"


def jm(body: str = "", members: str = "", cls: str = "Main", imports: str = "") -> tuple[str, int]:
    """A BlueJ-style Java file (braces on their own lines) with main; the cursor on the last line of main's body."""
    head = (imports + "\n\n" if imports else "")
    lines = [f"public class {cls}", "{"]
    if members:
        lines += ["    " + m if m else "" for m in members.split("\n")] + [""]
    lines += ["    public static void main(String[] args)", "    {"]
    body_lines = ["        " + b if b else "" for b in body.split("\n")] if body else []
    lines += body_lines
    cursor = len(head.split("\n")) - 1 + len(lines) if body_lines else len(head.split("\n")) - 1 + len(lines) + 1
    lines += ["    }", "}"]
    text = head + "\n".join(lines) + "\n"
    return text, cursor


def jc(cls: str = "Main", members: str = "") -> tuple[str, int]:
    """A class with no main."""
    lines = [f"public class {cls}", "{"] + (["    " + m if m else "" for m in members.split("\n")] if members else []) + ["}"]
    return "\n".join(lines) + "\n", 3


def cpp(body: str = "", top: str = "#include <iostream>\nusing namespace std;\n") -> tuple[str, int]:
    lines = top.rstrip("\n").split("\n") + ["", "int main()", "{"]
    lines += ["    " + b if b else "" for b in body.split("\n")] if body else []
    cur = len(lines) + (0 if body else 1)
    lines += ["    return 0;", "}"]
    return "\n".join(lines) + "\n", cur


C = []


def case(src, said, file, expect="edit", has=(), not_=(), lang="java", prev=(), note=""):
    text, cursor = file
    C.append({"id": len(C), "source": src, "lang": lang, "said": said, "file": text, "cursor": cursor,
              "previous": list(prev), "expect": expect, "has": list(has), "not": list(not_), "note": note})


E = ("", 1)  # an empty file
MAIN = jm()

# ---- the user's real sentences (3 and 5 Oct) ------------------------------------------------------------
case("user", "Create a class called Test.", E, has=[r"class\s+Test\b"])
case("user", "Public static void main.", jc("Test"), has=[r"public\s+static\s+void\s+main\s*\(\s*String"])
case("user", "I want public static void main inside the class test.", jc("Test"),
     has=[r"class\s+Test", r"static\s+void\s+main"], not_=[r"class\s+Main\b"])
case("user", "Move the cursor inside the main method.", jm(cls="Test"), expect="cursor")
case("user", "Initialize variable i.", jm(cls="Test"), has=[r"\bint\s+i\b"])
case("user", "Initialize variable i is equal to 0.", jm(cls="Test"), has=[r"\bint\s+i\s*=\s*0\s*;"])
case("user", "Wrap this inside class test inside main method.",
     ("int i = 0;\npublic class Test\n{\n}\n", 1), has=[r"static\s+void\s+main[\s\S]*int\s+i\s*=\s*0"],
     not_=[r"^int\s+i"])
case("user", "Now write a for loop where i is equal to 0, i is less than 10, i++.", jm("int i = 0;", cls="Test"),
     has=[r"for\s*\(\s*(int\s+)?i\s*=\s*0\s*;\s*i\s*<\s*10\s*;\s*i\+\+\s*\)"], note="i exists: 'for (int i' would not compile")
case("user", "System. out. print IE", jm("int i = 0;\nfor (i = 0; i < 10; i++)\n{\n}", cls="Test"),
     has=[r"System\.out\.print(ln)?\s*\(\s*i\s*\)"], note="said inside the loop")
case("user", "Include iOS stream.", ("", 1), lang="cpp", has=[r"#include\s*<iostream>"])
case("user", "Public Class Motivation,", E, has=[r"public\s+class\s+Motivation"])
case("user", "Class Motivation.", E, has=[r"class\s+Motivation"])
case("user", "Create a main method.", jc("Motivation"), has=[r"static\s+void\s+main"])
case("user", "Public Glass, Main.", E, has=[r"public\s+class\s+Main"])
case("user", "Public Class, Main.", E, has=[r"public\s+class\s+Main"])
case("user", "Public Static Void Main.", jc("Main"), has=[r"public\s+static\s+void\s+main"])
case("user", "EW, Static, Public, Public static void main.", jc("Main"), has=[r"static\s+void\s+main"])
case("user", "Initialize variable v.", MAIN, has=[r"\b(int|String|double)\s+v\b"])
case("user", "Change v to a string variable.", jm("int v = 0;"), has=[r"\bString\s+v\b"], not_=[r"\bint\s+v\b"])
case("user", "Create a variable string V and store capital A, capital E, I, O, U and the small versions.", MAIN,
     has=[r"String\s+[vV]\s*=\s*\"AEIOUaeiou\""])
case("user", "Create a string variable v.", jm("int v = 0;"), expect="ask",
     note="v already exists as int: ask (change its type, or use another name?)")
case("user", "Delete variable V as int.", jm("int v = 0;\nString s;"), not_=[r"\bint\s+v\b"], has=[r"String\s+s"])
case("user", "Ok, Store AEIOU in string V.", jm("String v;"), has=[r"v\s*=\s*\"AEIOU"])
case("user", "Last index of V.", jm('String v = "AEIOUaeiou";'), expect="ask", note="last index of WHAT in v?")
case("user", "Whatever is written in this code, remove all the code.", jm('String v = "AEIOUaeiou";'), expect="ask",
     note="removes the user's whole file: confirm first")

# ---- strings --------------------------------------------------------------------------------------------
S = jm('String name = "Abhra";')
case("written", "print the length of name", S, has=[r"System\.out\.print(ln)?\s*\(\s*name\.length\(\)\s*\)"])
case("written", "store the last index of a in v in an int called pos", jm('String v = "AEIOUaeiou";'),
     has=[r"int\s+pos\s*=\s*v\.lastIndexOf\s*\(\s*['\"]a['\"]\s*\)"])
case("written", "find the index of e in word and print it", jm('String word = "hello";'),
     has=[r"word\.indexOf\s*\(\s*['\"]e['\"]\s*\)"])
case("written", "convert name to upper case and print it", S, has=[r"name\.toUpperCase\(\)"])
case("written", "print the first character of name", S, has=[r"name\.charAt\s*\(\s*0\s*\)"])
case("written", "take the substring of name from 1 to 3 and store it in part", S,
     has=[r"String\s+part\s*=\s*name\.substring\s*\(\s*1\s*,\s*3\s*\)"])
case("written", "if name equals abhra ignoring case print yes", S,
     has=[r"if\s*\(\s*name\.equalsIgnoreCase\s*\(\s*\"abhra\"\s*\)\s*\)", r"\"yes\""])
case("written", "reverse the string s using a for loop and store it in rev", jm('String s = "java";'),
     has=[r"String\s+rev\s*=\s*\"\"", r"for\s*\(", r"charAt"])
case("written", "count the vowels in v and print the count", jm('String v = "programming";'),
     has=[r"for\s*\(", r"count|vowels"])
case("written", "replace every a with b in s", jm('String s = "banana";'), has=[r"s\.replace\s*\(\s*['\"]a['\"]\s*,\s*['\"]b['\"]\s*\)"])
case("written", "split sentence into words by space", jm('String sentence = "I like java";'),
     has=[r"String\s*\[\s*\]\s*\w+\s*=\s*sentence\.split\s*\(\s*\" \"\s*\)"])
case("written", "trim the string input", jm('String input = "  hi  ";'), has=[r"input\.trim\(\)"])
case("written", "join first and last with a space into full", jm('String first = "Abhra";\nString last = "C";'),
     has=[r"String\s+full\s*=\s*first\s*\+\s*\"\s\"\s*\+\s*last"])
case("written", "compare a and b using compareTo and print the result", jm('String a = "apple";\nString b = "mango";'),
     has=[r"a\.compareTo\s*\(\s*b\s*\)"])
case("written", "convert the string num to an int called n", jm('String num = "42";'),
     has=[r"int\s+n\s*=\s*Integer\.parseInt\s*\(\s*num\s*\)"])
case("written", "convert the int x to a string called sx", jm("int x = 5;"),
     has=[r"String\s+sx\s*=\s*(String\.valueOf\s*\(\s*x\s*\)|Integer\.toString\s*\(\s*x\s*\)|\"\"\s*\+\s*x|x\s*\+\s*\"\")"])
case("written", "check if the character ch is a digit", jm("char ch = '5';"), has=[r"Character\.isDigit\s*\(\s*ch\s*\)"])
case("written", "last index of", jm('String v = "AEIOUaeiou";'), expect="ask")

# ---- arrays ---------------------------------------------------------------------------------------------
A = jm("int[] arr = {4, 9, 1, 7, 3};")
case("written", "create an int array arr of size 5", MAIN, has=[r"int\s*\[\s*\]\s*arr\s*=\s*new\s+int\s*\[\s*5\s*\]"])
case("written", "create an array marks with 90 80 70 60 50", MAIN,
     has=[r"int\s*\[\s*\]\s*marks\s*=\s*(new\s+int\s*\[\s*\]\s*)?\{\s*90\s*,\s*80\s*,\s*70\s*,\s*60\s*,\s*50\s*\}"])
case("written", "print every element of arr with a for each loop", A, has=[r"for\s*\(\s*int\s+\w+\s*:\s*arr\s*\)"])
case("written", "find the sum of arr and print it", A, has=[r"\bsum\b", r"for\s*\("])
case("written", "find the largest element in arr", A, has=[r"for\s*\(", r">"])
case("written", "sort arr", A, has=[r"Arrays\.sort\s*\(\s*arr\s*\)", r"import\s+java\.util\.(Arrays|\*)\s*;"])
case("written", "create a 2D int array called ARR with 3 rows and 4 columns", MAIN,
     has=[r"int\s*\[\s*\]\s*\[\s*\]\s*ARR\s*=\s*new\s+int\s*\[\s*3\s*\]\s*\[\s*4\s*\]"])
case("written", "create a 2D int array matrix", MAIN, expect="ask", note="no size said")
case("written", "print the matrix row by row", jm("int[][] matrix = {{1, 2}, {3, 4}};"),
     has=[r"for\s*\([\s\S]*for\s*\(", r"matrix\s*\[\s*\w+\s*\]\s*\[\s*\w+\s*\]"])
case("written", "print the length of arr", A, has=[r"arr\.length\b"])
case("written", "search for key in arr and print found if it is there", jm("int[] arr = {4, 9, 1, 7, 3};\nint key = 7;"),
     has=[r"for\s*\(", r"==\s*key|key\s*==", r"\"found\""])
case("written", "bubble sort arr", A, has=[r"for\s*\([\s\S]*for\s*\(", r"temp|tmp|swap"])

# ---- loops and conditions -------------------------------------------------------------------------------
case("written", "while n is greater than 0 add n mod 10 to sum and divide n by 10", jm("int n = 1234;\nint sum = 0;"),
     has=[r"while\s*\(\s*n\s*>\s*0\s*\)", r"sum\s*(\+=\s*n\s*%\s*10|=\s*sum\s*\+\s*n\s*%\s*10)", r"n\s*(/=\s*10|=\s*n\s*/\s*10)"])
case("written", "if age is at least 18 print adult else print minor", jm("int age = 16;"),
     has=[r"if\s*\(\s*age\s*>=\s*18\s*\)", r"else", r"\"adult\"|\"Adult\"", r"\"minor\"|\"Minor\""])
case("written", "add an else if marks above 90 print A", jm("int marks = 95;\nif (marks > 95)\n{\n    System.out.println(\"A+\");\n}"),
     has=[r"else\s+if\s*\(\s*marks\s*>\s*90\s*\)"])
case("written", "switch on day: 1 prints Monday, 2 prints Tuesday, otherwise invalid", jm("int day = 2;"),
     has=[r"switch\s*\(\s*day\s*\)", r"case\s+1", r"case\s+2", r"default"])
case("written", "a do while loop that prints i until i is 5", jm("int i = 0;"), has=[r"\bdo\b[\s\S]*while\s*\("])
case("written", "print numbers from 1 to 10", MAIN, has=[r"for\s*\(\s*int\s+\w+\s*=\s*1\s*;\s*\w+\s*<=\s*10|<\s*11"])
case("written", "print the multiplication table of 5", MAIN, has=[r"for\s*\(", r"5\s*\*|\*\s*5"])
case("written", "break out of the loop when i equals 7", jm("for (int i = 0; i < 10; i++)\n{\n    System.out.println(i);\n}"),
     has=[r"if\s*\(\s*i\s*==\s*7\s*\)[\s\S]*break\s*;"])
case("written", "skip even numbers with continue", jm("for (int i = 0; i < 10; i++)\n{\n    System.out.println(i);\n}"),
     has=[r"i\s*%\s*2\s*==\s*0", r"continue\s*;"])
case("written", "nested loop to print a star triangle of 5 rows", MAIN, has=[r"for\s*\([\s\S]*for\s*\(", r"\"\*"])
case("written", "set max to a if a is greater than b else b using the ternary operator", jm("int a = 3;\nint b = 8;"),
     has=[r"int\s+max\s*=\s*\(?\s*a\s*>\s*b\s*\)?\s*\?\s*a\s*:\s*b"])
case("written", "change the loop to go till 20", jm("for (int i = 0; i < 10; i++)\n{\n    System.out.println(i);\n}"),
     has=[r"i\s*<=?\s*20"], not_=[r"i\s*<\s*10"])
case("written", "make i start from 1", jm("for (int i = 0; i < 10; i++)\n{\n    System.out.println(i);\n}"),
     has=[r"int\s+i\s*=\s*1"], not_=[r"int\s+i\s*=\s*0"])

# ---- input ----------------------------------------------------------------------------------------------
case("written", "take an integer input n from the user", MAIN,
     has=[r"import\s+java\.util\.(Scanner|\*)\s*;", r"new\s+Scanner\s*\(\s*System\.in\s*\)", r"int\s+n\s*=\s*\w+\.nextInt\(\)"])
case("written", "take a string input name", MAIN, has=[r"String\s+name\s*=\s*\w+\.next(Line)?\(\)", r"Scanner"])
case("written", "take a double input price", jm("Scanner sc = new Scanner(System.in);", imports="import java.util.Scanner;"),
     has=[r"double\s+price\s*=\s*sc\.nextDouble\(\)"], not_=[r"new\s+Scanner[\s\S]*new\s+Scanner"],
     note="a Scanner exists: reuse it")

# ---- methods and classes --------------------------------------------------------------------------------
case("written", "create a method square that takes int n and returns n times n", MAIN,
     has=[r"static\s+int\s+square\s*\(\s*int\s+n\s*\)", r"return\s+n\s*\*\s*n"])
case("written", "call square with 5 and print it", jm(members="static int square(int n)\n{\n    return n * n;\n}"),
     has=[r"System\.out\.print(ln)?\s*\(\s*square\s*\(\s*5\s*\)\s*\)"])
case("written", "make a static method isPrime that checks if n is prime", MAIN,
     has=[r"static\s+boolean\s+isPrime\s*\(\s*int\s+n\s*\)", r"return"])
case("written", "write a recursive factorial method", MAIN, has=[r"static\s+(int|long)\s+fact\w*\s*\(\s*int\s+\w+\s*\)", r"fact\w*\s*\(\s*\w+\s*-\s*1\s*\)"])
case("written", "overload add for two ints and for two doubles", MAIN,
     has=[r"static\s+int\s+add\s*\(\s*int\s+\w+\s*,\s*int\s+\w+\s*\)", r"static\s+double\s+add\s*\(\s*double\s+\w+\s*,\s*double\s+\w+\s*\)"])
case("written", "add private fields name and age", jc("Student"),
     has=[r"private\s+String\s+name\s*;", r"private\s+int\s+age\s*;"])
case("written", "create a constructor that takes name and age", jc("Student", "private String name;\nprivate int age;"),
     has=[r"Student\s*\(\s*String\s+\w+\s*,\s*int\s+\w+\s*\)", r"this\.name\s*=", r"this\.age\s*="])
case("written", "create a getter for name", jc("Student", "private String name;\nprivate int age;"),
     has=[r"public\s+String\s+getName\s*\(\s*\)", r"return\s+(this\.)?name"])
case("written", "make a void method greet that prints hello", MAIN, has=[r"void\s+greet\s*\(\s*\)", r"\"(hello|Hello)"])
case("written", "create a class Circle with a radius field and an area method", E,
     has=[r"class\s+Circle", r"double\s+radius", r"area\s*\(\s*\)", r"Math\.PI"])
case("written", "make the method greet static", jm(members="void greet()\n{\n    System.out.println(\"hello\");\n}"),
     has=[r"static\s+void\s+greet"])

# ---- edits ----------------------------------------------------------------------------------------------
case("written", "rename v to vowels", jm('String v = "AEIOU";\nSystem.out.println(v);'),
     has=[r"String\s+vowels\s*=", r"println\s*\(\s*vowels\s*\)"], not_=[r"\bv\b\s*[=)]"])
case("written", "change the type of x from int to double", jm("int x = 5;"), has=[r"double\s+x\s*=\s*5"], not_=[r"int\s+x"])
case("written", "delete the print line", jm("int x = 5;\nSystem.out.println(x);"), not_=[r"System\.out"], has=[r"int\s+x"])
case("written", "add a comment above main saying entry point", MAIN, has=[r"//\s*[Ee]ntry point|/\*[\s\S]*[Ee]ntry point"])
case("written", "move the print statement inside the loop",
     jm("for (int i = 0; i < 3; i++)\n{\n}\nSystem.out.println(\"hi\");"),
     has=[r"for\s*\([^)]*\)\s*\{\s*System\.out\.println\(\"hi\"\);\s*\}"])
case("written", "wrap the loop in a method called show",
     jm("for (int i = 0; i < 3; i++)\n{\n    System.out.println(i);\n}"),
     has=[r"static\s+void\s+show\s*\(\s*\)", r"show\s*\(\s*\)\s*;"])
case("written", "put a try catch around the division and print error if it fails", jm("int a = 5;\nint b = 0;\nint c = a / b;"),
     has=[r"try\s*\{[\s\S]*a\s*/\s*b[\s\S]*\}\s*catch\s*\("])
case("written", "declare a constant PI equal to 3.14", MAIN, has=[r"final\s+double\s+PI\s*=\s*3\.14"])
case("written", "create an int count", jm("int count = 0;"), expect="ask", note="count already exists")
case("written", "initialize i", jm("int i = 0;"), expect="ask", note="i already exists")
case("written", "remove the else part", jm("int a = 3;\nif (a > 2)\n{\n    System.out.println(\"big\");\n}\nelse\n{\n    System.out.println(\"small\");\n}"),
     not_=[r"\belse\b"], has=[r"if\s*\(\s*a\s*>\s*2\s*\)"])
case("written", "add import java util scanner", MAIN, has=[r"import\s+java\.util\.Scanner\s*;"])

# ---- types, maths, output -------------------------------------------------------------------------------
case("written", "declare a char grade equal to A", MAIN, has=[r"char\s+grade\s*=\s*'A'"])
case("written", "a boolean flag set to false", MAIN, has=[r"boolean\s+flag\s*=\s*false"])
case("written", "a long called big equal to ten billion", MAIN, has=[r"long\s+big\s*=\s*10_?000_?000_?000L"])
case("written", "print the square root of 16", MAIN, has=[r"Math\.sqrt\s*\(\s*16"])
case("written", "store 2 to the power 10 in p", MAIN, has=[r"\w+\s+p\s*=\s*\(?\s*\w*\s*\)?\s*Math\.pow\s*\(\s*2(\.0)?\s*,\s*10(\.0)?\s*\)"])
case("written", "a random number between 1 and 10 called r", MAIN,
     has=[r"int\s+r\s*=", r"Math\.random\(\)|new\s+Random|nextInt"])
case("written", "print the remainder of a divided by b", jm("int a = 17;\nint b = 5;"), has=[r"a\s*%\s*b"])
case("written", "increase x by 5", jm("int x = 1;"), has=[r"x\s*(\+=\s*5|=\s*x\s*\+\s*5)"])
case("written", "print hello world", MAIN, has=[r"System\.out\.println\s*\(\s*\"[Hh]ello,? [Ww]orld!?\"\s*\)"])
case("written", "print price with two decimal places", jm("double price = 9.5;"), has=[r"printf\s*\(\s*\"[^\"]*%\.2f|String\.format"])
case("written", "create an ArrayList of strings called names", MAIN,
     has=[r"(ArrayList|List)\s*<\s*String\s*>\s*names\s*=\s*new\s+ArrayList", r"import\s+java\.util\.(ArrayList|\*)"])
case("written", "add Abhra to names", jm("ArrayList<String> names = new ArrayList<>();", imports="import java.util.ArrayList;"),
     has=[r"names\.add\s*\(\s*\"Abhra\"\s*\)"])
case("written", "a HashMap from String to Integer called marks", MAIN,
     has=[r"(HashMap|Map)\s*<\s*String\s*,\s*Integer\s*>\s*marks\s*=\s*new\s+HashMap", r"import\s+java\.util\.(HashMap|\*)"])

# ---- C++ in VS Code -------------------------------------------------------------------------------------
case("written", "write the main function", ("#include <iostream>\nusing namespace std;\n", 3), lang="cpp",
     has=[r"int\s+main\s*\(\s*\)"])
case("written", "print hello", cpp(), lang="cpp", has=[r"cout\s*<<\s*\"[Hh]ello"])
case("written", "take input n", cpp(), lang="cpp", has=[r"int\s+n\s*;", r"cin\s*>>\s*n"])
case("written", "for loop from 1 to n printing i", cpp("int n;\ncin >> n;"), lang="cpp",
     has=[r"for\s*\(\s*int\s+i\s*=\s*1\s*;\s*i\s*<=\s*n", r"cout\s*<<\s*i"])
case("written", "a vector of ints called v", cpp(), lang="cpp", has=[r"vector\s*<\s*int\s*>\s*v", r"#include\s*<vector>"])
case("written", "push 5 into v", cpp("vector<int> v;", "#include <iostream>\n#include <vector>\nusing namespace std;\n"),
     lang="cpp", has=[r"v\.push_back\s*\(\s*5\s*\)"])
case("written", "a function add that takes two ints and returns the sum", cpp(), lang="cpp",
     has=[r"int\s+add\s*\(\s*int\s+\w+\s*,\s*int\s+\w+\s*\)", r"return"])
case("written", "if n is even print even otherwise odd", cpp("int n = 4;"), lang="cpp",
     has=[r"if\s*\(\s*n\s*%\s*2\s*==\s*0\s*\)", r"else", r"\"even\"|\"Even\""])
case("written", "read a full line into a string s", cpp(), lang="cpp",
     has=[r"string\s+s\s*;", r"getline\s*\(\s*cin\s*,\s*s\s*\)"])
case("written", "an array of 5 ints called a", cpp(), lang="cpp", has=[r"int\s+a\s*\[\s*5\s*\]"])
case("written", "declare n as int", cpp("int n = 4;"), lang="cpp", expect="ask", note="n already exists")


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in C), encoding="utf-8", newline="\n")
    from collections import Counter
    print(len(C), "cases:", dict(Counter((c["source"], c["lang"], c["expect"]) for c in C)))
