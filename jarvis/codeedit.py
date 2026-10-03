"""Coding mode's editing brain: the whole file as text, changed IN CODE, checked, and only then written.

The user, 3 Oct: "I told it create a class, create a main method, initialize i equals 0, then wrap this inside the
main method, and it made a new main method and a new class, with no care for syntax. Very dumb and very slow."

So every change here works on the code's structure, never on typed keystrokes:
  - the file is read whole and split into its blocks (classes, methods, loops) by matching braces, with strings
    and comments ignored;
  - a statement goes inside a method (the one at the cursor, else the one Jarvis wrote to last, else main, which
    is made if missing); a method goes inside the class; a class that exists is never made again;
  - "wrap this inside the main method" moves the lines into the main that exists;
  - every result has balanced brackets and is laid out in the file's own style (braces on their own line or not,
    its indent) before anything reaches the editor; the compiler check (jarvis/codecheck.py) comes after.

Nothing here touches the screen: tests cover all of it. Lines are 0-based inside, 1-based in what's said.
"""

import re
from dataclasses import dataclass, field

from .skills.editors import CURSOR

_CONTROL = re.compile(r"^(?:}\s*)?(else\s+if|if|for|foreach|while|do|switch|try|catch|finally|else|synchronized)\b")
_CLASS = re.compile(r"\b(?:class|interface|enum|struct)\s+([A-Za-z_]\w*)")
_METHOD = re.compile(r"([A-Za-z_]\w*)\s*\((?:[^()]|\([^()]*\))*\)\s*(?:const\s*)?(?:throws\s+[\w.,\s]+)?$")
_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "do", "try", "synchronized"}


class Unbalanced(ValueError):
    """The code's brackets don't match (the file is mid-edit, or broken)."""


@dataclass
class Block:
    kind: str    # class | method | control | other
    name: str    # the class/method name, or the keyword (for, while, if…)
    head: int    # the line with the header ("public static void main(String[] args)")
    open: int    # the line with "{"
    close: int   # the line with the matching "}"
    depth: int   # 0 = top level
    children: list = field(default_factory=list)

    def contains(self, line: int) -> bool:
        """Inside the body (between the braces' lines)."""
        return self.open < line < self.close


# ---- reading the code ---------------------------------------------------------------------------------------

def mask(text: str) -> str:
    """The code with strings, chars and comments blanked out (same length, same lines): brackets in them don't
    count."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(c + " " * max(0, j - i - 2) + (text[j - 1] if j - i >= 2 else ""))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def problem(text: str) -> str | None:
    """Why the brackets don't match, or None."""
    pairs = {")": "(", "}": "{", "]": "["}
    stack: list[tuple[str, int]] = []
    for ln, line in enumerate(mask(text).split("\n")):
        for c in line:
            if c in "({[":
                stack.append((c, ln))
            elif c in pairs:
                if not stack or stack[-1][0] != pairs[c]:
                    return f"an extra '{c}' on line {ln + 1}"
                stack.pop()
    if stack:
        c, ln = stack[-1]
        return f"the '{c}' on line {ln + 1} is never closed"
    return None


def _head_line(lines: list[str], masked: list[str], ln: int, col: int) -> int:
    """The line that holds a block's header: the same line as "{" when there's code before it, else the line
    above (braces on their own line)."""
    if masked[ln][:col].strip():
        return ln
    k = ln - 1
    while k >= 0 and not masked[k].strip():
        k -= 1
    return max(k, 0)


def _classify(header: str) -> tuple[str, str]:
    h = header.strip()
    m = _CONTROL.match(h)
    if m:
        return "control", re.sub(r"\s+", " ", m.group(1))
    m = _CLASS.search(h)
    if m:
        return "class", m.group(1)
    m = _METHOD.search(h)
    if m and m.group(1) not in _KEYWORDS:
        return "method", m.group(1)
    return "other", ""


def blocks(text: str) -> list[Block]:
    """Every {…} block, outermost first (children inside). Raises Unbalanced."""
    why = problem(text)
    if why:
        raise Unbalanced(why)
    lines, masked = text.split("\n"), mask(text).split("\n")
    stack: list[tuple[int, int]] = []
    found: list[Block] = []
    for ln, line in enumerate(masked):
        for col, c in enumerate(line):
            if c == "{":
                stack.append((ln, col))
            elif c == "}":
                o_ln, o_col = stack.pop()
                head = _head_line(lines, masked, o_ln, o_col)
                header = masked[head][:o_col] if head == o_ln else masked[head]
                kind, name = _classify(header)
                found.append(Block(kind, name, head, o_ln, ln, len(stack)))
    found.sort(key=lambda b: (b.open, -b.close))
    roots: list[Block] = []
    open_: list[Block] = []
    for b in found:
        while open_ and not (open_[-1].open <= b.open and b.close <= open_[-1].close and b is not open_[-1]):
            open_.pop()
        (open_[-1].children if open_ else roots).append(b)
        open_.append(b)
    return found


def at(text: str, line: int) -> list[Block]:
    """The blocks a line is inside, outermost first."""
    return [b for b in blocks(text) if b.open < line < b.close]


def find(text: str, kind: str, name: str | None = None) -> Block | None:
    for b in blocks(text):
        if b.kind == kind and (name is None or b.name == name or b.name.lower() == (name or "").lower()):
            return b
    return None


def method_at(text: str, line: int) -> Block | None:
    inside = [b for b in at(text, line) if b.kind == "method"]
    return inside[-1] if inside else None


# ---- the file's style ---------------------------------------------------------------------------------------

def indent_of(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


def unit(text: str) -> str:
    """One level of indent in this file (4 spaces unless it uses tabs or 2)."""
    widths = sorted({len(indent_of(ln)) for ln in text.split("\n") if ln.strip() and indent_of(ln)
                     and "\t" not in indent_of(ln)})
    if any(ln.startswith("\t") for ln in text.split("\n")):
        return "\t"
    return " " * widths[0] if widths and widths[0] in (2, 3, 4, 8) else "    "


def allman(text: str, lang: str) -> bool:
    """Braces on their own line? The file decides; an empty file: Java (BlueJ) yes, C++ no (the user's style)."""
    own = sum(1 for ln in text.split("\n") if ln.strip() == "{")
    same = sum(1 for ln in mask(text).split("\n") if ln.rstrip().endswith("{") and ln.strip() != "{")
    if own or same:
        return own >= same
    return lang == "java"


def restyle(snippet: str, own_line: bool, ind: str = "    ") -> list[str]:
    """A snippet's lines with braces in the file's style and its indent unit (no base indent yet)."""
    out: list[str] = []
    for raw in snippet.split("\n"):
        depth_txt = indent_of(raw)
        level = len(depth_txt.replace("\t", "    ")) // 4
        body = raw.strip()
        if own_line and body.endswith("{") and body != "{" and not body.startswith("}"):
            out.append(ind * level + body[:-1].rstrip())
            out.append(ind * level + "{")
        elif not own_line and body == "{" and out:
            out[-1] = out[-1].rstrip() + " {"
        else:
            out.append(ind * level + body if body else (ind * level + CURSOR if CURSOR in raw else ""))
    return out


# ---- edits ----------------------------------------------------------------------------------------------------

@dataclass
class Edit:
    text: str             # the whole file after the change
    cursor: int           # 0-based line for the cursor afterwards
    said: str             # what Jarvis says it did
    lines: tuple[int, int] = (0, -1)  # the lines Jarvis wrote (0-based, inclusive): "this" for "wrap this"
    changed: bool = True


def snippet_kind(snippet: str) -> str:
    first = next((ln.strip() for ln in snippet.split("\n") if ln.strip()), "")
    if _CLASS.search(first) and not first.endswith(";"):
        return "class"
    if not _CONTROL.match(first) and _METHOD.search(first.rstrip("{ ").rstrip()) and not first.endswith(";") \
            and _METHOD.search(first.rstrip("{ ").rstrip()).group(1) not in _KEYWORDS:
        return "method"
    return "statement"


def _splice(lines: list[str], at_line: int, new: list[str], base: str) -> tuple[list[str], int, int]:
    """Insert `new` (already styled) at line index `at_line` with the base indent; returns (lines, first, cursor)."""
    placed, cursor = [], at_line + len(new) - 1
    for i, ln in enumerate(new):
        if CURSOR in ln:
            cursor = at_line + i
            placed.append(base + ln.replace(CURSOR, ""))  # keeps its indent: the cursor sits there
        else:
            placed.append(base + ln if ln.strip() else "")
    return lines[:at_line] + placed + lines[at_line:], at_line, cursor


def _body_indent(lines: list[str], b: Block, ind: str) -> str:
    for k in range(b.open + 1, b.close):
        if lines[k].strip() and not lines[k].strip().startswith("}"):
            return indent_of(lines[k])
    return indent_of(lines[b.head]) + ind


def _end_of_body(lines: list[str], b: Block, lang: str) -> int:
    """Where a statement goes at the end of a method: before its closing brace (C++ main: before return 0)."""
    k = b.close
    if lang == "cpp" and b.name == "main":
        prev = k - 1
        while prev > b.open and not lines[prev].strip():
            prev -= 1
        if re.match(r"\s*return\s+0\s*;", lines[prev]):
            return prev
    return k


def _say(code: str) -> str:
    """The first line of code, said like a person: 'int i = 0;' -> 'int i equals 0'."""
    first = next((ln.strip() for ln in code.replace(CURSOR, "").split("\n") if ln.strip()), "")
    s = first.rstrip(";{ ").rstrip()
    s = re.sub(r"System\.out\.println", "print line", s)
    s = re.sub(r"System\.out\.print", "print", s)
    for a, b in (("==", " is equal to "), ("!=", " not equal to "), ("<=", " at most "), (">=", " at least "),
                 ("++", " plus plus"), ("--", " minus minus"), ("+=", " plus equals "), ("-=", " minus equals "),
                 ("&&", " and "), ("||", " or "), ("=", " equals "), ("<<", " "), ("<", " less than "),
                 (">", " greater than "), ("(", " "), (")", " "), ('"', ""), (";", ","), ("[]", " array")):
        s = s.replace(a, b)
    return " ".join(s.split())


def insert(text: str, cursor: int | None, snippet: str, lang: str, file_class: str = "Main",
           last_method: str | None = None) -> Edit:
    """Put `snippet` where it belongs. `cursor`: the 0-based line the cursor is on (None when unknown)."""
    lines = text.split("\n") if text else [""]
    kind = snippet_kind(snippet)
    own = allman(text, lang)
    ind = unit(text)
    new = restyle(snippet, own, ind)
    bl = blocks(text)
    cur = cursor if cursor is not None and 0 <= cursor < len(lines) else None

    if kind == "class":
        name = _CLASS.search(snippet).group(1)
        have = next((b for b in bl if b.kind == "class" and b.name.lower() == name.lower()), None)
        if have:
            return Edit(text, have.open + 1, f"There's already a class {have.name}, so I put the cursor in it.",
                        changed=False)
        while lines and not lines[-1].strip():
            lines.pop()
        at_line = len(lines)
        gap = [""] if lines else []
        out, first, cur2 = _splice(lines + gap, at_line + len(gap), new, "")
        return Edit("\n".join(out), cur2, f"Added the class {name}.", (first, first + len(new) - 1))

    if kind == "method":
        name = _METHOD.search(next(ln for ln in snippet.split("\n") if ln.strip()).rstrip("{ ").rstrip()).group(1)
        have = next((b for b in bl if b.kind == "method" and b.name == name), None)
        if have:
            return Edit(text, have.open + 1, f"There's already a method {name}, so I put the cursor in it.",
                        changed=False)
        classes = [b for b in bl if b.kind == "class"]
        if lang == "java" and not classes:
            text = _with_class(text, file_class, own, ind)
            return insert(text, None, snippet, lang, file_class, last_method)._made_class(file_class)
        if lang == "java":
            target = next((c for c in reversed(classes) if cur is not None and c.open < cur < c.close), None) \
                or next((c for c in classes if c.name == file_class), classes[0])
            inner = method_at(text, cur) if cur is not None and target.open < cur < target.close else None
            if inner:
                at_line = inner.close + 1
            elif cur is not None and target.open < cur < target.close:
                at_line = cur + 1
            else:
                at_line = target.close
            base = _body_indent(lines, target, ind)
        else:  # C++: a function before main, so main can call it
            main = next((b for b in bl if b.kind == "method" and b.name == "main"), None)
            at_line = main.head if main else len(lines)
            base = ""
        block = new + [""] if lang == "cpp" and at_line < len(lines) else new
        if lang == "java" and at_line > 0 and lines[at_line - 1].strip() not in ("", "{"):
            block = [""] + block
        out, first, cur2 = _splice(lines, at_line, block, base)
        if CURSOR not in snippet:
            cur2 = first + len(block) - 1
        return Edit("\n".join(out), cur2, f"Added the method {name}.", (first, first + len(block) - 1))

    # a statement (or a loop/if block): inside a method
    where = method_at(text, cur) if cur is not None else None
    said_where = ""
    if where:
        inner = [b for b in at(text, cur) if b.depth >= where.depth]
        host = inner[-1]
        on_head = next((b for b in bl if b.head <= cur <= b.open and b.depth >= where.depth), None)
        if on_head:  # the cursor is on a block's header: the code goes first inside it
            host, at_line = on_head, on_head.open + 1
        elif lines[cur].strip().startswith("}"):
            closing = next((b for b in bl if b.close == cur), None)
            host = next((b for b in at(text, cur) if b.depth == (closing.depth - 1 if closing else 0)), where)
            at_line = cur + 1
        else:
            at_line = cur + 1
        base = indent_of(lines[cur]) if not on_head and lines[cur].strip() and not lines[cur].strip().startswith("}") \
            else _body_indent(lines, host, ind)
        if lines[cur].strip().startswith("}"):
            base = indent_of(lines[cur])
        if not lines[cur].strip() and host.open < cur < host.close:  # a blank line: the code goes ON it
            at_line, base = cur, _body_indent(lines, host, ind)
            lines = lines[:cur] + lines[cur + 1:]
    else:
        methods = [b for b in bl if b.kind == "method"]
        host = next((b for b in methods if b.name == last_method), None) \
            or next((b for b in methods if b.name == "main"), None) \
            or (methods[0] if len(methods) == 1 else None)
        if host is None:
            made = _with_main(text, lang, file_class, own, ind)
            again = insert(made, None, snippet, lang, file_class, "main")
            again.said = f"Added {_say(snippet)} in a new main method."
            return again
        at_line = _end_of_body(lines, host, lang)
        base = _body_indent(lines, host, ind)
        said_where = f" in {host.name}"
        # an empty body's blank placeholder line is used, not left above the code
        k = at_line - 1
        if k > host.open and not lines[k].strip() and all(not lines[j].strip() for j in range(host.open + 1, at_line)):
            lines = lines[:k] + lines[k + 1:]
            at_line = k
    out, first, cur2 = _splice(lines, at_line, new, base)
    if CURSOR not in snippet:
        cur2 = first + len(new) - 1
    return Edit("\n".join(out), cur2, f"Added {_say(snippet)}{said_where}.", (first, first + len(new) - 1))


def _with_class(text: str, name: str, own: bool, ind: str) -> str:
    """Wrap the file's code in `public class Name` (imports stay above it)."""
    lines = text.split("\n") if text.strip() else []
    head = [ln for ln in lines if re.match(r"\s*(import|package)\b", ln)]
    rest = [ln for ln in lines if ln not in head]
    while rest and not rest[0].strip():
        rest.pop(0)
    while rest and not rest[-1].strip():
        rest.pop()
    body = [ind + ln if ln.strip() else "" for ln in rest] or [""]
    top = [f"public class {name}", "{"] if own else [f"public class {name} {{"]
    return "\n".join(head + ([""] if head else []) + top + body + ["}"])


def _main_lines(lang: str, own: bool, ind: str) -> list[str]:
    if lang == "java":
        return (["public static void main(String[] args)", "{", ind, "}"] if own else
                ["public static void main(String[] args) {", ind, "}"])
    return ["int main() {", ind, ind + "return 0;", "}"] if not own else ["int main()", "{", ind, ind + "return 0;", "}"]


def _with_main(text: str, lang: str, file_class: str, own: bool, ind: str) -> str:
    """The file with an empty main added (inside the class in Java; a class is made if there's none)."""
    if lang == "java" and not find(text, "class"):
        text = _with_class(text, file_class, own, ind)
    lines = text.split("\n") if text else []
    if lang == "java":
        cls = next((b for b in blocks(text) if b.kind == "class" and b.name == file_class), None) or find(text, "class")
        base = _body_indent(lines, cls, ind)
        body_lines = [ln for ln in lines[cls.open + 1:cls.close] if ln.strip()]
        if not body_lines:  # a class body that was only blank lines: main takes their place
            lines = lines[:cls.open + 1] + lines[cls.close:]
            close = cls.open + 1
        else:
            close = cls.close
        block = ([""] if body_lines else []) + _main_lines(lang, own, ind)
        out, _, _ = _splice(lines, close, block, base)
        return "\n".join(out)
    while lines and not lines[-1].strip():
        lines.pop()
    block = ([""] if lines else []) + _main_lines(lang, own, ind)
    return "\n".join(lines + block)


def _made_class(self: Edit, name: str) -> Edit:
    self.said = self.said.rstrip(".") + f", in a new class {name}."
    return self


Edit._made_class = _made_class


def ensure_main(text: str, lang: str, file_class: str = "Main") -> Edit:
    """'create a main method': the cursor into the main that exists, else a new one."""
    have = find(text, "method", "main")
    if have:
        lines = text.split("\n")
        return Edit(text, _last_body_line(lines, have), "There's already a main method, so I put the cursor in it.",
                    changed=False)
    own, ind = allman(text, lang), unit(text)
    made = _with_main(text, lang, file_class, own, ind)
    m = find(made, "method", "main")
    lines = made.split("\n")
    first = m.head
    return Edit(made, m.open + 1, "Added the main method.", (first, m.close))


def _last_body_line(lines: list[str], b: Block) -> int:
    k = b.close - 1
    while k > b.open and not lines[k].strip():
        k -= 1
    return k if k > b.open else b.open + (1 if b.close > b.open + 1 else 0)


def ensure_class(text: str, name: str, lang: str) -> Edit:
    have = next((b for b in blocks(text) if b.kind == "class" and b.name.lower() == name.lower()), None)
    if have:
        return Edit(text, have.open + 1, f"There's already a class {have.name}, so I put the cursor in it.",
                    changed=False)
    own, ind = allman(text, lang), unit(text)
    snippet = f"public class {name}\n{{\n    {CURSOR}\n}}" if lang == "java" else f"class {name} {{\n    {CURSOR}\n}};"
    return insert(text, None, snippet, lang, name)


def move_into(text: str, span: tuple[int, int], target: str, lang: str, file_class: str = "Main") -> Edit:
    """'wrap this inside the main method': the lines `span` (0-based, inclusive) moved into the method `target`
    (made if missing). Lines already inside it stay where they are."""
    lines = text.split("\n")
    a, b = span
    moving = lines[a:b + 1]
    if not any(ln.strip() for ln in moving):
        return Edit(text, a, "There's nothing on that line to move.", changed=False)
    have = find(text, "method", target)
    if have and have.open < a and b < have.close:
        return Edit(text, b, f"That's already inside {have.name}.", changed=False)
    own, ind = allman(text, lang), unit(text)
    if have and (have.open <= b and a <= have.close):
        raise ValueError(f"those lines overlap the start or end of {target}")
    rest = lines[:a] + lines[b + 1:]
    # don't leave a gap where the code was: two blank lines, or a blank line right after "{"
    while a < len(rest) and not rest[a].strip() and (a == 0 or not rest[a - 1].strip()
                                                     or rest[a - 1].strip().endswith("{")):
        rest.pop(a)
    body = _dedent(moving)
    rest_text = "\n".join(rest)
    if problem(rest_text) or problem("\n".join(moving)):
        raise ValueError("the lines don't hold whole statements")
    have = find(rest_text, "method", target)  # its lines moved up
    if not have:
        if target != "main":
            raise ValueError(f"there's no method {target}")
        rest_text = _with_main(rest_text, lang, file_class, own, ind)
        have = find(rest_text, "method", "main")
    rest = rest_text.split("\n")
    at_line = _end_of_body(rest, have, lang)
    base = _body_indent(rest, have, ind)
    k = at_line - 1
    if k > have.open and all(not rest[j].strip() for j in range(have.open + 1, at_line)):
        rest = rest[:have.open + 1] + rest[at_line:]
        at_line = have.open + 1
    out, first, _ = _splice(rest, at_line, body, base)
    said = f"Moved {_say(moving[0].strip() if len([m for m in moving if m.strip()]) == 1 else ' '.join(m.strip() for m in moving if m.strip()))} into {have.name}." \
        if len([m for m in moving if m.strip()]) == 1 else f"Moved {len([m for m in moving if m.strip()])} lines into {have.name}."
    return Edit("\n".join(out), first + len(body) - 1, said, (first, first + len(body) - 1))


def wrap_in(text: str, span: tuple[int, int], header: str, lang: str) -> Edit:
    """'put this inside a for loop from 1 to 10': the lines become the body of a new block, in place."""
    lines = text.split("\n")
    a, b = span
    moving = lines[a:b + 1]
    if problem("\n".join(moving)):
        raise ValueError("the lines don't hold whole statements")
    own, ind = allman(text, lang), unit(text)
    base = indent_of(next((ln for ln in moving if ln.strip()), ""))
    inner = [ind + ln if ln.strip() else "" for ln in _dedent(moving)]
    block = [header, "{", *inner, "}"] if own else [header + " {", *inner, "}"]
    out = lines[:a] + [base + ln if ln.strip() else "" for ln in block] + lines[b + 1:]
    return Edit("\n".join(out), a + len(block) - 1, f"Put that inside {_say(header)}.", (a, a + len(block) - 1))


def extract_method(text: str, span: tuple[int, int], name: str, lang: str) -> Edit:
    """'wrap this inside a method called show': the lines become a new method; a call takes their place."""
    lines = text.split("\n")
    a, b = span
    host = method_at(text, a)
    if host is None or not (host.open < a and b < host.close):
        raise ValueError("those lines aren't inside a method")
    if find(text, "method", name):
        raise ValueError(f"there's already a method {name}")
    own, ind = allman(text, lang), unit(text)
    moving = lines[a:b + 1]
    static = "static " if re.search(r"\bstatic\b", lines[host.head]) else ""
    head = f"{'public ' if lang == 'java' else ''}{static if lang == 'java' else ''}void {name}()"
    body = [ind + ln if ln.strip() else "" for ln in _dedent(moving)]
    method = [head, "{", *body, "}"] if own else [head + " {", *body, "}"]
    call_base = indent_of(next((ln for ln in moving if ln.strip()), ""))
    rest = lines[:a] + [call_base + f"{name}();"] + lines[b + 1:]
    host2 = method_at("\n".join(rest), a)
    base = indent_of(rest[host2.head])
    at_line = host2.close + 1
    out = rest[:at_line] + [""] + [base + ln if ln.strip() else "" for ln in method] + rest[at_line:]
    return Edit("\n".join(out), at_line + 1, f"Made the method {name} from that, and called it there.",
                (at_line + 1, at_line + len(method)))


def _dedent(lines: list[str]) -> list[str]:
    real = [indent_of(ln) for ln in lines if ln.strip()]
    cut = min((len(i) for i in real), default=0)
    return [ln[cut:] if ln.strip() else "" for ln in lines]


def delete_lines(text: str, span: tuple[int, int]) -> Edit:
    lines = text.split("\n")
    a, b = span
    if not (0 <= a <= b < len(lines)):
        raise ValueError(f"there's no line {b + 1}")
    out = "\n".join(lines[:a] + lines[b + 1:])
    if problem(out) and not problem(text):
        raise ValueError("that would leave a bracket without its pair")
    n = b - a + 1
    return Edit(out, max(0, a - 1), f"Deleted line {a + 1}." if n == 1 else f"Deleted lines {a + 1} to {b + 1}.",
                (a, a - 1))


def rename(text: str, old: str, new: str) -> Edit:
    """Every use of the name `old` (not inside strings or comments) becomes `new`."""
    m = mask(text)
    hits = [x.start() for x in re.finditer(rf"\b{re.escape(old)}\b", m)]
    if not hits:
        raise ValueError(f"there's no {old} in the code")
    out = text
    for pos in reversed(hits):
        out = out[:pos] + new + out[pos + len(old):]
    line = text[:hits[0]].count("\n")
    return Edit(out, line, f"Renamed {old} to {new} in {len(hits)} place{'s' if len(hits) != 1 else ''}.",
                (line, line))


def block_span(text: str, line: int) -> tuple[int, int]:
    """'this' on a block's header means the whole block; else the line."""
    for b in blocks(text):
        if b.head <= line <= b.open:
            return b.head, b.close
    return line, line


def same(a: str, b: str) -> bool:
    """Equal, ignoring trailing spaces and line ends (editors add their own)."""
    def norm(t):
        return [ln.rstrip() for ln in t.replace("\r\n", "\n").replace("\r", "\n").rstrip().split("\n")]
    return norm(a) == norm(b)
