"""Voice coding in BlueJ (Java) and VS Code (C++): "go to line 40", "comment lines 10 to 15", "uncomment this",
"select line 12", "open class DigitSumCheck", "compile", "run it", "open file main.cpp".

Every edit is checked (jarvis/skills/editors.py): BlueJ's code is read back directly; VS Code's line is read by
copying it. Speech-to-code ("print hello world") is coding mode: jarvis/coding.py.
"""

import re
import time

from . import ability
from ..skills import desktop, editors, keys

_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
            "fifty": 50, "hundred": 100}


def _num(s: str) -> int:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    total = 0
    for w in s.replace("-", " ").split():
        if w not in _NUMBERS:
            raise ValueError(f"not a line number: {s!r}")
        total += _NUMBERS[w]
    return total


def _editor() -> editors.Editor:
    ed = editors.current()
    if not ed:
        raise ValueError("no code editor (BlueJ or VS Code) is in front")
    return ed


def _range(value: str | None) -> tuple[int, int] | None:
    if not value or value in ("this", "it", "this line", "that"):
        return None
    parts = re.split(r" (?:to|through|till|until) ", value)
    first = _num(parts[0])
    last = _num(parts[1]) if len(parts) > 1 else first
    return (first, last) if last >= first else (last, first)


_LINES = r"(?:lines? (?:number )?(?P<value>[\w -]+?(?: (?:to|through|till|until) [\w -]+)?)|this|it|this line|that)"


@ability("code_go_to_line", "code editor: go to a line",
         r"(?:go|jump|move|take me) to line (?:number )?(?P<value>[\w -]+)", value="n")
def go_to_line(value: str):
    return _editor().go_to_line(_num(value))


@ability("code_comment", "code editor: comment out a line or lines",
         rf"comment(?: out)? {_LINES}(?: out)?", value="n or n to m")
def comment(value: str | None = None):
    return _editor().comment(_range(value), True)


@ability("code_uncomment", "code editor: uncomment a line or lines",
         rf"un ?comment {_LINES}", value="n or n to m")
def uncomment(value: str | None = None):
    return _editor().comment(_range(value), False)


@ability("code_select_lines", "code editor: select a line or lines",
         r"select lines? (?:number )?(?P<value>[\w -]+?(?: (?:to|through|till|until) [\w -]+)?)", value="n or n to m")
def select_lines(value: str):
    first, last = _range(value)
    _editor().select_lines(first, last)
    return f"Selected line {first}." if first == last else f"Selected lines {first} to {last}."


@ability("code_compile", "compile the code in the editor (BlueJ)",
         r"compile(?: it| this| the code| the class| the program| my code)?")
def compile_code():
    return _editor().compile()


@ability("code_run", "run the program (BlueJ: the class's main)",
         r"(?:run|execute)(?: it| this| the code| the program| my code| main| the main method)?",
         r"(?:run|execute) (?:the )?class (?P<value>\w+)", value="class")
def run_code(value: str | None = None):
    if value:
        return editors.run_main(value)
    return _editor().run()


@ability("bluej_open_class", "BlueJ: open a class's editor",
         r"open (?:the )?class (?:called |named )?(?P<value>[\w ]+)", value="class")
def open_class(value: str):
    return editors.open_class(value)


@ability("code_open_file", "VS Code: open a file of the project by name",
         r"open (?:the )?file (?!called |named |explorer|manager|with |of )(?P<value>[\w .-]+?)(?: in (?:vs )?code)?", value="name")
def open_file(value: str):
    if not desktop.front_window().lower().startswith("code:"):
        raise ValueError("VS Code isn't in front")
    name = re.sub(r" dot ", ".", value.strip())
    name = re.sub(r" (cpp|c|h|hpp|py|java|js|ts|txt|md|html|css|json)$", r".\1", name)  # "main cpp" -> main.cpp
    keys.press("ctrl+p")
    time.sleep(0.3)
    desktop.type_text(name)
    time.sleep(0.6)
    keys.press("enter")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if name.split(".")[0].lower() in desktop.front_window().lower():
            return f"Opened {name}."
    return f"Not done: there's no file like {name} in this project."
