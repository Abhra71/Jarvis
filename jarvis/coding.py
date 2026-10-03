"""Coding mode: say code the way a person says it, get correct Java (BlueJ) or C++ (VS Code) at the cursor.

    "print hello world"            Java: System.out.println("hello world");    C++: cout << "hello world" << endl;
    "system out print sum"         System.out.print(sum);   (a variable in the code: no quotes)
    "print sum is then sum"        System.out.println("sum is " + sum);
    "int sum equals zero"          int sum = 0;
    "for i from 1 to 10"           for (int i = 1; i <= 10; i++) { … cursor inside … }
    "if x greater than 5"          if (x > 5) { … }
    "else" / "else if …" / "while n not equal to 0"
    "input int n"                  Java: int n = sc.nextInt();  (and the Scanner + import when missing)
                                   C++: int n; cin >> n;
    "return sum", "break", "increase count by 2", "sum plus equals digit"…

The common things above are done in code (instant, exact). Anything else goes to the AI once ("a method that
checks if a number is prime"), which answers with code for that language. The user's style is followed: BlueJ
code has its braces on their own line (as in the user's classes), C++ keeps them on the same line.
"""

import logging
import re

from .skills.editors import CURSOR

log = logging.getLogger(__name__)

_WORD_NUMBERS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                 "seven": "7", "eight": "8", "nine": "9", "ten": "10", "hundred": "100"}
_TYPES = {"int": "int", "integer": "int", "double": "double", "float": "float", "char": "char",
          "character": "char", "boolean": "boolean", "bool": "boolean", "string": "String", "long": "long",
          "short": "short", "byte": "byte"}
_OPS = [  # spoken -> code, longest first
    (r"greater than or equal to|greater than equal to|at least", ">="),
    (r"less than or equal to|less than equal to|at most", "<="),
    (r"is not equal to|not equal to|not equals|is not", "!="),
    (r"is equal to|equal to|equals|is", "=="),
    (r"greater than|more than|bigger than", ">"), (r"less than|smaller than", "<"),
    (r"plus plus", "++"), (r"minus minus", "--"),
    (r"plus", "+"), (r"minus", "-"), (r"times|multiplied by|into", "*"), (r"divided by|by", "/"),
    (r"mod|modulo|modulus|remainder of", "%"),
    (r"and", "&&"), (r"or", "||"), (r"not", "!"),
    (r"open bracket|open parenthesis", "("), (r"close bracket|close parenthesis", ")"),
]


def identifiers(code: str | None) -> set[str]:
    """Names already in the code (variables, methods): "print sum" means the variable sum, not the word."""
    if not code:
        return set()
    names = set(re.findall(r"\b(?:int|double|float|char|boolean|bool|String|string|long|short|byte|auto)\s+(\w+)",
                           code))
    names |= set(re.findall(r"\bfor\s*\(\s*(?:int\s+)?(\w+)", code))
    return names


def _num_words(s: str) -> str:
    return " ".join(_WORD_NUMBERS.get(w, w) for w in s.split())


def expression(spoken: str, known: set[str]) -> str:
    """'x greater than 5 and y mod 2 equals 0' -> 'x > 5 && y % 2 == 0'."""
    s = " " + _num_words(spoken.lower().strip(" .")) + " "
    for words, op in _OPS:
        s = re.sub(rf"(?<=\s)(?:{words})(?=\s)", f" {op} ", s)
    s = " ".join(s.split())
    s = re.sub(r"\( ", "(", s)
    s = re.sub(r" \)", ")", s)
    s = re.sub(r"(\w) (\+\+|--)", r"\1\2", s)
    # a multi-word name the code already has in camelCase ("sum of digits" -> sumOfDigits)
    if _camel(spoken.strip(" .")) in known:
        return _camel(spoken.strip(" ."))
    for name in sorted(known, key=len, reverse=True):
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).lower()
        if " " in spaced:
            s = re.sub(rf"\b{re.escape(spaced)}\b", name, s, flags=re.I)
    return s


def _camel(x: str) -> str:
    """'sum of digits' -> 'sumOfDigits'."""
    words = x.split()
    return words[0].lower() + "".join(w.capitalize() for w in words[1:]) if words else ""


def _is_expression(x: str, known: set[str]) -> bool:
    words = x.lower().split()
    if not words:
        return False
    if _camel(x) in known:  # "sum of digits" and the code has sumOfDigits
        return True
    if re.fullmatch(r"-?\d+(\.\d+)?", x.strip()):
        return True
    if all(w in known or w in _WORD_NUMBERS or re.fullmatch(r"[+\-*/%()]|\d+", w) or
           any(re.fullmatch(words_, w) for words_, _ in _OPS) for w in words):
        return any(w in known for w in words) or bool(re.search(r"\d", x))
    return False


def _string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _block(head: str, lang: str) -> str:
    if lang == "java":
        return f"{head}\n{{\n    {CURSOR}\n}}"
    return f"{head} {{\n    {CURSOR}\n}}"


def _print_args(x: str, original: str, known: set[str], lang: str) -> str | None:
    """The thing to print: a variable/expression, a quoted text, or text then a value."""
    m = re.match(r"^(?:the )?(?:text|string|word|words|message) (.+)$", x)
    if m:
        return _string(original[-len(m.group(1)):] if len(original) >= len(m.group(1)) else m.group(1))
    m = re.match(r"^(?:the )?(?:value of|variable) (.+)$", x)
    if m:
        return expression(m.group(1), known)
    parts = re.split(r" (?:then|followed by|and then|and the value of|comma) ", x)
    if len(parts) == 2 and _is_expression(parts[1], known) and parts[0].strip() not in known \
            and _camel(parts[0]) not in known:
        joiner = " + " if lang == "java" else " << "
        return _string(_original_case(original, parts[0]) + " ") + joiner + expression(parts[1], known)
    if _is_expression(x, known):
        return expression(x, known)
    return _string(_original_case(original, x))


def _original_case(original: str, lowered: str) -> str:
    """The words as the user said them (their capitals), found back in the original sentence."""
    i = original.lower().find(lowered)
    return original[i:i + len(lowered)] if i >= 0 else lowered


def translate(said: str, lang: str, code: str | None = None, names: set[str] | None = None) -> str | None:
    """Speech -> code for `lang` ("java" or "cpp"), or None when it isn't one of the common patterns.
    `names`: variables known from this session (VS Code doesn't show Jarvis its code)."""
    original = said.strip().rstrip(".")
    s = " ".join(re.sub(r"[,;:!?]", " ", original.lower()).split())
    s = re.sub(r"\bsystem(?:\W+|\s+dot\s+)out(?:\W+|\s+dot\s+)", "system out ", s)  # "System. out. print", "system dot out dot"
    s = " ".join(s.replace(".", " ").split()) if not re.search(r"\d\.\d", s) else s
    known = identifiers(code) | (names or set())
    java = lang == "java"

    # printing
    m = re.fullmatch(r"(?:system out |std ?:? ?:? ?|c ?out )?(print ?ln|print line|println|print|display|show|output|"
                     r"cout)(?: out)? (.+?)(?P<same> on the same line| without (?:a )?new line)?", s)
    if m and not s.startswith(("print screen",)):
        verb, x = m.group(1), m.group(2)
        newline = not (m.group("same") or (verb == "print" and s.startswith("system out print ")
                                           and "println" not in s and "print line" not in s))
        arg = _print_args(x, original, known, lang)
        if arg is None:
            return None
        if java:
            return f"System.out.{'println' if newline else 'print'}({arg});"
        return f"cout << {arg}{' << endl' if newline else ''};"

    # a variable: "int sum equals 0", "declare a string name", "double average is total divided by n"
    m = re.fullmatch(r"(?:declare |create |make |define |new )?(?:an? |the )?(?P<t>" + "|".join(_TYPES) +
                     r")(?: variable)?(?: called| named)? (?P<n>[a-z]\w*)(?: (?:equals|equal to|=|is|as|with value|"
                     r"initiali[sz]ed to|to) (?P<v>.+))?", s)
    if m:
        t = _TYPES[m.group("t")]
        if not java:
            t = {"String": "string", "boolean": "bool"}.get(t, t)
        value = m.group("v")
        if value is None:
            return f"{t} {m.group('n')};"
        if t in ("String", "string") and not _is_expression(value, known):
            value = _string(_original_case(original, value))
        elif t == "char" and len(value.strip()) == 1:
            value = f"'{value.strip()}'"
        else:
            value = expression(value, known)
        return f"{t} {m.group('n')} = {value};"

    # input
    m = re.fullmatch(r"(?:input|read|take input|take|scan|get|enter)(?: an?| the)? (?P<t>int|integer|double|float|"
                     r"string|word|line|char|character|long)?(?: number| value| variable)? ?(?:into |in |as |called )?"
                     r"(?P<n>[a-z]\w*)", s)
    if m and (m.group("t") or m.group("n") in known):
        name, t = m.group("n"), (m.group("t") or "int")
        if java:
            method = {"int": "nextInt()", "integer": "nextInt()", "double": "nextDouble()", "float": "nextFloat()",
                      "string": "next()", "word": "next()", "line": "nextLine()", "char": "next().charAt(0)",
                      "character": "next().charAt(0)", "long": "nextLong()"}[t]
            jt = {"integer": "int", "string": "String", "word": "String", "line": "String", "character": "char"}.get(t, t)
            decl = "" if name in known else f"{jt} "
            return f"{decl}{name} = sc.{method};"
        ct = {"integer": "int", "word": "string", "line": "string", "string": "string", "character": "char"}.get(t, t)
        if t == "line":
            return (f"string {name};\n" if name not in known else "") + f"getline(cin, {name});"
        return (f"{ct} {name};\n" if name not in known else "") + f"cin >> {name};"

    # loops and conditions
    # 30 Sep: "write a for loop where i is equal to 0, i is less than 10, i++" (said the C way: start; test; step)
    m = re.fullmatch(r"(?:write |make |create |add )?(?:a |an )?for(?: loop)?(?: where| with| in which| such that)? "
                     r"(?P<v>[a-z]\w*) (?:is )?(?:equal to|equals|=|is|as) (?P<a>\S+) (?:and )?(?P=v) (?:is )?"
                     r"(?P<op>less than or equal to|less than equal to|less than|greater than or equal to|"
                     r"greater than equal to|greater than|at most|at least|<=|<|>=|>) (?P<b>\S+) (?:and )?(?P=v) ?"
                     r"(?P<inc>\+\+|plus plus|--|minus minus)", s)
    if m:
        v = m.group("v")
        cmp = {"less than or equal to": "<=", "less than equal to": "<=", "less than": "<", "at most": "<=",
               "greater than or equal to": ">=", "greater than equal to": ">=", "greater than": ">",
               "at least": ">="}.get(m.group("op"), m.group("op"))
        inc = f"{v}++" if m.group("inc") in ("++", "plus plus") else f"{v}--"
        decl = "" if v in known else "int "
        return _block(f"for ({decl}{v} = {expression(m.group('a'), known)}; {v} {cmp} "
                      f"{expression(m.group('b'), known)}; {inc})", lang)
    m = re.fullmatch(r"(?:a |make a |create a )?for(?: loop)?(?: with| using)? (?P<v>[a-z]\w*) (?:from|=|equals|"
                     r"equal to|starting at|starting from) (?P<a>.+?) (?P<op>down to|to|till|until|up to|through|"
                     r"less than|below|greater than|above)(?P<b> .+?)(?: step (?P<s>\w+))?", s)
    if m:
        v, a, b, op = m.group("v"), expression(m.group("a"), known), expression(m.group("b"), known), m.group("op")
        step = _num_words(m.group("s") or "1")
        down = op in ("down to", "greater than", "above")
        cmp = {"to": "<=", "through": "<=", "up to": "<=", "till": "<", "until": "<", "less than": "<",
               "below": "<", "down to": ">=", "greater than": ">", "above": ">"}[op]
        inc = (f"{v}--" if down else f"{v}++") if step == "1" else (f"{v} -= {step}" if down else f"{v} += {step}")
        decl = "" if v in known else "int "
        return _block(f"for ({decl}{v} = {a}; {v} {cmp} {b}; {inc})", lang)
    m = re.fullmatch(r"(?:a )?(?P<kw>else if|if|while)(?: loop)? (?:the )?(?P<c>.+)", s)
    if m:
        return _block(f"{m.group('kw')} ({expression(m.group('c'), known)})", lang)
    if re.fullmatch(r"(?:an? )?else(?: block| part)?|otherwise", s):
        return _block("else", lang)
    m = re.fullmatch(r"(?:a )?do while (?:the )?(?P<c>.+)", s)
    if m:
        return (f"do\n{{\n    {CURSOR}\n}} while ({expression(m.group('c'), known)});" if java else
                f"do {{\n    {CURSOR}\n}} while ({expression(m.group('c'), known)});")

    # small statements
    m = re.fullmatch(r"return (.+)", s)
    if m:
        return f"return {expression(m.group(1), known)};"
    if s in ("break", "break out", "break the loop", "break out of the loop"):
        return "break;"
    if s in ("continue", "continue the loop", "skip to the next"):
        return "continue;"
    m = re.fullmatch(r"(?:increase|increment|add) (?P<n>\w+)(?: by (?P<k>\w+))?|(?P<n2>\w+) plus plus", s)
    if m and (m.group("n") or m.group("n2")) in known:
        n, k = m.group("n") or m.group("n2"), _num_words(m.group("k") or "1")
        return f"{n}++;" if k == "1" else f"{n} += {k};"
    m = re.fullmatch(r"(?:decrease|decrement|reduce) (?P<n>\w+)(?: by (?P<k>\w+))?|(?P<n2>\w+) minus minus", s)
    if m and (m.group("n") or m.group("n2")) in known:
        n, k = m.group("n") or m.group("n2"), _num_words(m.group("k") or "1")
        return f"{n}--;" if k == "1" else f"{n} -= {k};"
    m = re.fullmatch(r"(?P<n>[a-z]\w*) (?P<op>plus|minus|times|divided by|mod) equals (?P<v>.+)", s)
    if m and m.group("n") not in _TYPES:
        op = {"plus": "+=", "minus": "-=", "times": "*=", "divided by": "/=", "mod": "%="}[m.group("op")]
        return f"{m.group('n')} {op} {expression(m.group('v'), known)};"
    m = re.fullmatch(r"(?:set |make |assign )?(?P<n>[a-z]\w*) (?:equals|equal to|=|becomes|to|as) (?P<v>.+)", s)
    if m and m.group("n") not in _TYPES and (m.group("n") in known or re.fullmatch(r"(?:set |assign )?[a-z]\w* "
                                                                            r"(?:equals|=|becomes) .+", s)):
        return f"{m.group('n')} = {expression(m.group('v'), known)};"
    m = re.fullmatch(r"(?:add a |write a )?comment(?: saying| that says)? (.+)", s)
    if m:
        return f"// {_original_case(original, m.group(1))}"
    m = re.fullmatch(r"(?:initiali[sz]e|declare|create|make)(?: a| an| the)?(?: new)?(?: variable| integer| int| counter)?"
                     r"(?: called| named)? (?P<n>[a-z]\w*)(?: (?:to|equal to|equals|is equal to|=|as|with|with value) "
                     r"(?P<v>.+))?", s)
    if m and m.group("n") not in _TYPES and m.group("n") not in ("a", "an", "the", "method", "function", "class",
                                                                  "loop", "array", "program"):
        value = expression(m.group("v"), known) if m.group("v") else "0"
        return f"{m.group('n')} = {value};" if m.group("n") in known else f"int {m.group('n')} = {value};"
    if re.fullmatch(r"(?:write |add |create |make )?(?:a |the )?(?:(?:public )?(?:static )?void main(?: string args)?|"
                    r"main (?:method|function))(?: method| function)?", s):
        if java:
            return f"public static void main(String[] args)\n{{\n    {CURSOR}\n}}"
        return f"int main() {{\n    {CURSOR}\n    return 0;\n}}"
    return None


# ---- the AI, for anything else ------------------------------------------------------------------------------

AI_SYSTEM = """You turn one spoken coding instruction into {language} code for a student's editor.
Answer in JSON: {{"code": "<the code>"}}. The code only: no explanation, no markdown fences.
If it is NOT clearly an instruction to write code (a command like "select all" or "move the cursor", a question,
a single unclear word, or speech that doesn't make sense), answer {{"code": ""}}. Never guess.
Write only the snippet asked for, to be put at the cursor: never wrap it in a class or in main, and never write a
class unless the instruction says to create a class. Never repeat code that is already in their file.
Follow the student's style: {style}
Use the names already in their code where they fit: {names}.{static}
Write the COMPLETE code that was asked for (a whole method, a whole loop with its body…), laid out properly:
one statement per line, 4-space indents (use 
 inside the JSON string).
Only when the instruction just starts an empty block for the student to fill ("start a do-while", "make an empty
method called show"), put the single character {cursor} on its own line inside it.
Keep it short: only what was asked."""


def ask_ai(said: str, lang: str, code: str | None, think) -> str | None:
    """One AI call for what the patterns don't cover. `think(system, user)` -> text."""
    language = "Java (BlueJ)" if lang == "java" else "C++"
    style = ("braces on their own line; 4 spaces" if lang == "java" else "brace on the same line; 4 spaces; "
             "using namespace std")
    system = AI_SYSTEM.format(language=language, style=style, cursor=CURSOR,
                              names=", ".join(sorted(identifiers(code))) or "none yet",
                              static=("\nTheir code runs from a static main: make new methods static, so main can "
                                      "call them." if code and re.search(r"static\s+void\s+main", code) else ""))
    user = f"Instruction: {said}"
    if code:
        user += "\nTheir code so far (for context only, don't repeat it):\n" + code[-1500:]
    try:
        out = think(system, user)
    except Exception as e:
        log.warning("Coding AI failed: %s", e)
        return None
    out = re.sub(r"^```\w*\n?|\n?```$", "", (out or "").strip()).strip("\n")
    if out.startswith("{") and '"' in out[:20]:  # some models answer in JSON when asked for plain text
        try:
            import json
            data = json.loads(out)
            out = next((v for v in data.values() if isinstance(v, str)), "")
        except ValueError:
            pass
    if not out or len(out) > 1500:
        return None
    if re.search(r"\bclass\s+\w+", out) and "class" not in said.lower():
        log.warning("Coding AI wrote a class nobody asked for; not typing it: %r", out[:120])
        return None
    if code and all(ln.strip() in code for ln in out.split("\n") if ln.strip() and ln.strip() not in "{}"):
        log.warning("Coding AI repeated code already in the file; not typing it")
        return None
    if out.count("{") != out.count("}") or out.count("(") != out.count(")"):
        log.warning("Coding AI's answer isn't balanced; not typing it: %r", out[:200])
        return None  # never type broken code
    # it goes in the middle of a file: no #include / using / import lines
    out = "\n".join(ln for ln in out.split("\n")
                    if not re.match(r"\s*(#include|using namespace|import\s+[\w.]+\*?;)", ln)).strip("\n")
    if any(len(ln) > 90 and ln.count(";") > 1 for ln in out.split("\n")):
        out = layout(out, allman=(lang == "java"))
    return out


def layout(code: str, allman: bool) -> str:
    """Cramped one-line code -> one statement per line with 4-space indents (braces in the user's style)."""
    out, line, depth, paren, i = [], "", 0, 0, 0

    def push(text):
        if text.strip():
            out.append("    " * depth + text.strip())

    while i < len(code):
        c = code[i]
        if c == "(":
            paren += 1
        elif c == ")":
            paren -= 1
        if c == "{" and paren == 0:
            if allman:
                push(line)
                push("{")
            else:
                push(line.rstrip() + " {")
            line, depth = "", depth + 1
        elif c == "}" and paren == 0:
            push(line)
            line, depth = "", max(0, depth - 1)
            push("}")
        elif c == ";" and paren == 0:
            push(line + ";")
            line = ""
        elif c != "\n":
            line += c
        i += 1
    push(line)
    return "\n".join(out)


def needs_scanner(code_after: str, text: str | None) -> list[str]:
    """Java input needs a Scanner (and its import): the lines to add when the code doesn't have them yet."""
    if ".next" not in code_after or not text:
        return []
    extra = []
    if "import java.util" not in text:
        extra.append("import")
    if not re.search(r"Scanner\s+sc\s*=", text):
        extra.append("scanner")
    return extra
