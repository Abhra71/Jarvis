"""Coding mode, controllable (Block 2, 3 Oct): "write, then say it".

The user's complaint: it wrote a second class and main for "wrap this inside the main method", never checked for
errors, was slow, and took background noise for code. Now:

- A FIXED set of commands (below). Anything else that's clearly code goes to the AI only when it's a clear "write a
  method that…", and that is read out and written only after a yes. Unclear speech is never turned into code.
- Every change is made on the whole file's structure (jarvis/codeedit.py): it finds the class and main that are
  there. Moves, wraps, renames, deletes and AI code are compiled in a hidden folder first (jarvis/codecheck.py);
  a change that brings a new error is fixed once in code or not made at all ("That would break the code…").
- Short pattern lines go in at once and Jarvis says exactly what it wrote ("Added int i equals 0.").
- "Undo" takes back Jarvis's own last change from its own record (never a blind Ctrl+Z), "redo" puts it back.
- A pop-up shows what was heard and what was written.

Commands:
  writing   print …, int x equals …, for i from 1 to 10, if/else/while, return, input int n, comment saying …,
            create a class [called X], create a main method, write a method that … (AI, after a yes)
  editing   undo, redo, wrap/put/move this|line N|lines N to M|the loop into main|a method called X|a for loop …,
            delete line N, delete lines N to M, rename X to Y, clear everything (after a yes), fix the errors,
            move the cursor inside main, come out of the loop
  tools     (abilities) compile, run, go to line N, comment line N, open class X, coding mode off
"""

import logging
import re
import time
from dataclasses import dataclass

from . import codecheck, codeedit, coding
from .skills import editors, keys

log = logging.getLogger(__name__)

_POLITE = re.compile(r"^(?:(?:please|now|okay|ok|so|and|then|can you|could you|would you|i want you to|i want to|"
                     r"let'?s|next|jarvis|hey jarvis)[, ]+)+", re.I)
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
        "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}

YES = re.compile(r"(?:yes|yeah|yep|yup|sure|ok(?:ay)?|do it|go ahead|write it|add it|haan|correct|right)"
                 r"(?: please| jarvis| do it| write it)*")
NO = re.compile(r"(?:no|nope|nah|don'?t|do not|cancel|leave it|never ?mind|stop)(?: (?:it|that|write it|please))*")

UNDO = re.compile(r"undo(?: that| it| the last (?:change|line|thing))?|scratch that|take (?:that|it) back|"
                  r"(?:remove|delete|erase) (?:that|it|what(?:ever)? you (?:have |just )?(?:wrote|written|typed|"
                  r"added)(?: above)?)")
REDO = re.compile(r"redo(?: that| it)?|put (?:it|that) back")
MAIN = re.compile(r"(?:(?:create|make|add|write|give me|insert|start|declare|define)(?: me)? )?(?:a |an |the )?"
                  r"(?:new )?(?:public static void main(?: string args)?|main (?:method|function)|main)"
                  r"(?: method| function)?(?: here| now| inside (?:the |this )?class(?: \w+)?)?")
CLASS = re.compile(r"(?:create|make|add|write|start|declare|define) (?:a |an |the )?(?:new )?(?:public )?class"
                   r"(?: (?:called|named) (?P<n>\w+)| (?P<n2>(?!called|named)\w+))?")
_WHAT = (r"(?P<what>this|that|it|these|those|this line|that line|this code|the code|all (?:of )?(?:it|the code)|"
         r"everything|the last line|the last (?P<k>\w+) lines|what you (?:just )?wrote|"
         r"(?:the )?lines? (?:number )?(?P<a>\w+)(?: (?:to|through|till|and) (?:line )?(?P<b>\w+))?|"
         r"the (?:for |while )?loop|the if(?: block)?|the (?:\w+ )?(?:statement|variable|declaration)(?: \w+)?|"
         r"(?:the )?(?:initiali[sz]e|initialization|declaration|print) (?:statement|line))")
WRAP = re.compile(r"(?:wrap|put|move|place|shift|take|keep|insert) " + _WHAT +
                  r" (?:inside|into|in|within|under|to) (?:of )?(?:the |a |an )?(?P<where>.+)")
CURSOR_INTO = re.compile(r"(?:move|go|take|put|place|jump)(?: me| the cursor| cursor)? (?:inside|into|in|to) "
                         r"(?:the )?(?P<n>main|[a-z]\w*)(?: method| function| loop| class| block)?")
EXIT = re.compile(r"(?:come |get |go )?(?:out of|outside|exit|leave|after|close|end) (?:the |this )?(?:loop|block|if|"
                  r"else|while|for|braces?|brackets?|method|function|condition)|next block")
DELETE = re.compile(r"(?:delete|remove|erase|cut) (?:the )?(?:line (?:number )?(?P<a>\w+)(?: (?:to|through|till) "
                    r"(?:line )?(?P<b>\w+))?|lines (?:number )?(?P<a2>\w+) (?:to|through|till|and) (?P<b2>\w+)|"
                    r"(?P<this>this line|the current line|current line))")
RENAME = re.compile(r"(?:rename|change the name of) (?:the )?(?:variable |method |function |class )?(?P<o>\w+) "
                    r"(?:to|as|into) (?P<n>\w+)")
FIX = re.compile(r"(?:fix|correct|solve|repair|remove) (?:the |all the |all |my |these |those |any )?"
                 r"(?:errors?|mistakes?|bugs?|syntax(?: errors?)?|it|this|code)|(?:check|test) (?:my |the |this )?"
                 r"code(?: for errors)?|(?:are there |is there |any )(?:any )?(?:errors?|mistakes?)(?: in (?:my |the )?code)?")
CLEAR = re.compile(r"(?:delete|remove|clear|erase|wipe)(?: out)? (?:all|everything|all the code|the whole code|"
                   r"all of it|the code|whatever is (?:written|there)(?: here| in this code| on (?:my |the )?screen)?)")
SELECT_ALL = re.compile(r"(?:select all|select everything|(?:control|ctrl) (?:plus )?a)|"
                        r"(?:i want you to )?(?:press|click) (?:control|ctrl) (?:plus )?a")
STATUS = re.compile(r"(?:is )?(?:coding|code) mode (?:on|still on|active)|are you in (?:coding|code) mode")
WRITE_CODE = re.compile(r"(?:write|add|make|create|declare|define|implement|generate|build|give me) "
                        r"(?:a |an |the |me a |me an )?(?:new )?(?:\w+ )?(?:method|function|loop|program|code|"
                        r"constructor|array|switch|recursive)")
CODE_VERB = re.compile(r"(?:write|add|make|create|declare|define|implement|generate|build|insert|print|set|"
                       r"initiali[sz]e|increase|decrease|return|input|read|for|while|if|else)\b")
# Said in coding mode but meant as a command for Jarvis, not code: handled the normal way.
NOT_CODE = re.compile(r"(?:open|close|play|pause|resume|volume|mute|unmute|search|switch|minimi[sz]e|maximi[sz]e|"
                      r"snap|scroll|save|copy|paste|go back|what|who|how|why|when|tell me|turn (?:on|off)|"
                      r"brightness|night light|bluetooth|wi ?fi|email|upload|stop|cancel|press|click|"
                      r"compile|run|execute|comment|uncomment|select|go to|jump to|open class|show)\b")

BIG_LINES = 6  # more lines than this from the AI: read out, written after a yes


@dataclass
class Change:
    before: str
    after: str
    said: str
    span: tuple[int, int]
    title: str


def _n(word: str | None) -> int | None:
    if not word:
        return None
    w = word.lower()
    if w.isdigit():
        return int(w)
    total = 0
    for part in w.replace("-", " ").split():
        if part not in _NUM:
            return None
        total += _NUM[part]
    return total or None


class CodeMode:
    def __init__(self, think=None):
        self.think = think              # think(system, user) -> text: the AI, for "write a method that…"
        self.history: list[Change] = []
        self.redone: list[Change] = []
        self.pending: tuple | None = None   # (Edit, before, title, said) waiting for a yes
        self.last_method: str | None = None
        self.last_written = ""

    # ---- entry ------------------------------------------------------------------------------------------------

    def handle(self, text: str, ed: editors.Editor, unsure: bool = False) -> str | None:
        """The reply, or None when it isn't a coding command (the normal request handling takes it)."""
        spoken = " ".join(_POLITE.sub("", re.sub(r"[,!?]", " ", text.lower())).strip(" .").split())
        spoken = re.sub(r"\bsystem\.?\s*out\.?\s*", "system out ", spoken)
        if self.pending:
            if YES.fullmatch(spoken):
                return self._confirm(ed)
            if NO.fullmatch(spoken):
                self.pending = None
                return "Okay, I didn't write it."
            self.pending = None  # something else: the offer lapses
        if STATUS.fullmatch(spoken):
            return "Yes, coding mode is on."
        if UNDO.fullmatch(spoken):
            return self.undo(ed)
        if REDO.fullmatch(spoken):
            return self.redo(ed)
        if SELECT_ALL.fullmatch(spoken):
            keys.press("ctrl+a")
            return "Selected everything."
        if CLEAR.fullmatch(spoken):
            return self._offer_clear(ed)
        if FIX.fullmatch(spoken):
            return self.fix(ed)
        m = CLASS.fullmatch(spoken)
        if m:
            name = m.group("n") or m.group("n2")
            if isinstance(ed, editors.BlueJ) and name and name.lower() != ed.file_class.lower():
                return None  # BlueJ: another class is a new file (its New Class button: abilities)
            return self._structure(ed, lambda t, c: codeedit.ensure_class(t, (name or ed.file_class).capitalize()
                                                                          if not name or name.islower() else name,
                                                                          ed.lang), check=False)
        if MAIN.fullmatch(spoken):
            return self._structure(ed, lambda t, c: codeedit.ensure_main(t, ed.lang, ed.file_class), check=False)
        m = WRAP.fullmatch(spoken)
        if m:
            return self.wrap(ed, m)
        m = CURSOR_INTO.fullmatch(spoken)
        if m:
            return self.cursor_into(ed, m.group("n"))
        if EXIT.fullmatch(spoken):
            return self.exit_block(ed)
        m = DELETE.fullmatch(spoken)
        if m:
            return self.delete(ed, m)
        m = RENAME.fullmatch(spoken)
        if m:
            return self._structure(ed, lambda t, c: codeedit.rename(t, m.group("o"), m.group("n")), check=True)
        if NOT_CODE.match(spoken):
            return None
        return self.write_code(text, spoken, ed, unsure)

    # ---- writing ------------------------------------------------------------------------------------------------

    def write_code(self, text: str, spoken: str, ed, unsure: bool) -> str | None:
        got = ed.read()
        if got is None:
            return "Not done: I can't read the code in this editor."
        before, cursor = got
        body = _POLITE.sub("", text.strip()).strip()
        code = coding.translate(body, ed.lang, before, coding.identifiers(before) | coding.identifiers(self.last_written))
        source = "patterns"
        if code is None:
            words = spoken.split()
            if unsure or len(words) < 3 or not WRITE_CODE.match(spoken):
                # 30 Sep: "Ect.", "Rongen.", "VS Code." became methods. Unclear speech is never code.
                # It may be someone else talking (3 Oct: "it catches very much of background noises"): quiet, with a
                # pop-up, unless it sounded like a coding instruction ("write…", "add…", "print…").
                log.info("Coding: not a coding command: %r", text)
                if not unsure and CODE_VERB.match(spoken):
                    return "I didn't catch that as code. Say it again?"
                _popup(text, "(not a coding command, so nothing was written)", "Coding mode")
                return ""
            if not self.think:
                return "I can only write that with the AI, and it isn't available right now."
            code = coding.ask_ai(text, ed.lang, before, self.think)
            source = "AI"
            if not code:
                return "I didn't get that as code. Say it again, or say coding mode off."
        if self.last_written and code.strip() == self.last_written.strip() and self.history \
                and codeedit.same(before, self.history[-1].after):
            return "That's the same code I just wrote, so I didn't add it again."
        log.info("Coding (%s, %s): %r -> %r", ed.name, source, text, code)
        extra = coding.needs_scanner(code, before) if ed.lang == "java" else []
        if "scanner" in extra:
            code = "Scanner sc = new Scanner(System.in);\n" + code
        try:
            edit = codeedit.insert(before, cursor, code, ed.lang, ed.file_class, self.last_method)
        except codeedit.Unbalanced as e:
            return f"I didn't add it: the code's brackets don't match ({e}). Say fix the errors."
        if "import" in extra and edit.changed:
            edit.text = "import java.util.Scanner;\n" + edit.text
            edit.cursor += 1
            edit.lines = (edit.lines[0] + 1, edit.lines[1] + 1)
        if source == "AI":  # anything the AI wrote is read out first, and written after a yes
            n = len([ln for ln in code.split("\n") if ln.strip()])
            return self._offer(ed, before, edit, code, n, text)
        reply = self._apply(ed, before, cursor, edit, check=False, heard=text)
        if reply.startswith(("Added", "There's already")):
            self.last_written = code
        return reply

    def _offer(self, ed, before, edit, code, n, heard) -> str:
        """AI code is read out first; written only after a yes (the user's choice, 3 Oct)."""
        fresh = codecheck.new_errors(before, edit.text, ed.lang)
        if fresh:
            fixed = codecheck.quick_fix(edit.text, ed.lang)
            if fixed and not codecheck.new_errors(before, fixed[0], ed.lang):
                edit.text = fixed[0]
            else:
                return f"The AI's code would break yours ({fresh[0].plain()}), so I didn't write it. Say it another way?"
        self.pending = (edit, before, ed.title, code)
        _popup(heard, code, "Say yes to write it")
        first = codeedit._say(code)
        return f"I'll add {n} line{'s' if n != 1 else ''}: {first}{'…' if n > 1 else ''}. It's in the pop-up. Shall I write it?"

    def _confirm(self, ed) -> str:
        edit, before, title, code = self.pending
        self.pending = None
        got = ed.read()
        if got is None or ed.title != title or not codeedit.same(got[0], before):
            return "The code changed since I offered that, so I didn't write it. Say it again?"
        reply = self._apply(ed, before, got[1], edit, check=False, heard="yes")
        if reply.startswith("Added"):
            self.last_written = code
        return reply

    # ---- structure ----------------------------------------------------------------------------------------------

    def _structure(self, ed, make, check: bool, heard: str = "") -> str:
        got = ed.read()
        if got is None:
            return "Not done: I can't read the code in this editor."
        before, cursor = got
        try:
            edit = make(before, cursor)
        except codeedit.Unbalanced as e:
            return f"I can't change it yet: the code's brackets don't match ({e}). Say fix the errors."
        except ValueError as e:
            return f"I didn't change it: {e}."
        return self._apply(ed, before, cursor, edit, check=check, heard=heard)

    def wrap(self, ed, m) -> str:
        where = m.group("where").strip()

        def make(text, cursor):
            span = self._span(text, cursor, m)
            target = re.sub(r"^(?:the |a |an )", "", where)
            if re.search(r"\bmain\b", target):
                return codeedit.move_into(text, span, "main", ed.lang, ed.file_class)
            mm = re.fullmatch(r"(?:new )?(?:method|function) (?:called |named )?(?P<x>\w+)|(?P<y>\w+) (?:method|function)",
                              target)
            if mm:
                name = mm.group("x") or mm.group("y")
                if codeedit.find(text, "method", name):
                    return codeedit.move_into(text, span, name, ed.lang, ed.file_class)
                return codeedit.extract_method(text, span, _ident(name), ed.lang)
            header = coding.translate(target, ed.lang, text)
            if header and re.match(r"(for|while|if)\b", header):
                return codeedit.wrap_in(text, span, header.split("\n")[0].strip(), ed.lang)
            raise ValueError(f"I don't know where '{where}' is")

        return self._structure(ed, make, check=True)

    def _span(self, text: str, cursor: int | None, m) -> tuple[int, int]:
        """What 'this' / 'line 5' / 'the loop' means."""
        what = m.group("what")
        lines = text.split("\n")
        a, b = _n(m.group("a")), _n(m.group("b"))
        if a:
            b = b or a
            if not (1 <= a <= b <= len(lines)):
                raise ValueError(f"there's no line {b}")
            return a - 1, b - 1
        if m.group("k"):
            k = _n(m.group("k")) or 1
            last = self._last_span(text)
            end = last[1] if last else (cursor if cursor is not None else len(lines) - 1)
            return max(0, end - k + 1), end
        if re.search(r"loop|\bif\b", what):
            kinds = ("for", "while", "do") if "loop" in what else ("if",)
            here = cursor if cursor is not None else 0
            cands = [bk for bk in codeedit.blocks(text) if bk.kind == "control" and bk.name in kinds]
            if not cands:
                raise ValueError(f"there's no {'loop' if 'loop' in what else 'if'} in the code")
            best = min(cands, key=lambda bk: 0 if bk.head <= here <= bk.close else abs(bk.head - here))
            return best.head, best.close
        if what in ("all of it", "all it", "all of the code", "all the code", "everything", "the code", "this code"):
            body = [i for i, ln in enumerate(lines) if ln.strip() and not re.match(r"\s*(import|package|#include|using)\b", ln)]
            return body[0], body[-1]
        last = self._last_span(text)
        if last and what in ("this", "that", "it", "these", "those", "what you wrote", "what you just wrote",
                             "the last line"):
            return last if what != "the last line" else (last[1], last[1])
        if cursor is None:
            raise ValueError("I don't know which line you mean. Say the line number")
        return codeedit.block_span(text, cursor)

    def _last_span(self, text: str) -> tuple[int, int] | None:
        """The lines Jarvis wrote last, if the code is still as it left it."""
        if self.history and codeedit.same(text, self.history[-1].after) and self.history[-1].span[1] >= self.history[-1].span[0]:
            return self.history[-1].span
        return None

    def cursor_into(self, ed, name: str) -> str:
        got = ed.read()
        if got is None:
            return "Not done: I can't read the code in this editor."
        text, _ = got
        try:
            bl = codeedit.blocks(text)
        except codeedit.Unbalanced as e:
            return f"I can't find my way: the code's brackets don't match ({e})."
        if name in ("loop", "for", "while"):
            hit = next((b for b in bl if b.kind == "control" and b.name in ("for", "while", "do")), None)
        else:
            hit = next((b for b in bl if b.name.lower() == name.lower()), None)
        if not hit:
            return f"There's no {name} in this code."
        line = codeedit._last_body_line(text.split("\n"), hit)
        if hit.kind == "method":
            self.last_method = hit.name
        ed.place(line)
        return f"In {hit.name}."

    def exit_block(self, ed) -> str:
        got = ed.read()
        if got is None or got[1] is None:
            r = ed.exit_block()  # can't read: the old way, by walking down to the closing brace
            return "" if r == "ok" else r
        text, cursor = got
        try:
            inside = codeedit.at(text, cursor)
        except codeedit.Unbalanced as e:
            return f"I can't find my way: the code's brackets don't match ({e})."
        inner = [b for b in inside if b.kind == "control"] or inside
        if not inner:
            return "The cursor isn't inside a block."
        b = inner[-1]
        ed.place(b.close)
        return f"After the {b.name}." if b.kind == "control" else f"After {b.name}."

    def delete(self, ed, m) -> str:
        def make(text, cursor):
            if m.group("this"):
                if cursor is None:
                    raise ValueError("I don't know which line the cursor is on")
                return codeedit.delete_lines(text, (cursor, cursor))
            a, b = _n(m.group("a") or m.group("a2")), _n(m.group("b") or m.group("b2"))
            if not a:
                raise ValueError("say the line number, like delete line 5")
            return codeedit.delete_lines(text, (a - 1, (b or a) - 1))
        return self._structure(ed, make, check=False)

    def fix(self, ed) -> str:
        got = ed.read()
        if got is None:
            return "Not done: I can't read the code in this editor."
        before, cursor = got
        if not codecheck.available(ed.lang):
            return "I can't check this code: there's no compiler for it on this PC."
        errs = codecheck.errors(before, ed.lang)
        if not errs:
            return "No errors. The code compiles."
        text, done = before, []
        for _ in range(5):  # simple fixes, one at a time
            fixed = codecheck.quick_fix(text, ed.lang)
            if not fixed:
                break
            text, said = fixed
            done.append(said)
        if done:
            left = codecheck.errors(text, ed.lang) or ()
            edit = codeedit.Edit(text, cursor if cursor is not None else 0, "I " + ", and ".join(done) + ".")
            reply = self._apply(ed, before, cursor, edit, check=False)
            if left and reply.startswith("I "):
                reply += f" There's still {len(left)} error{'s' if len(left) != 1 else ''}: {left[0].plain()}."
            return reply
        e = errs[0]
        if self.think:
            return self._ai_fix(ed, before, errs)
        return f"There {'is 1 error' if len(errs) == 1 else f'are {len(errs)} errors'}: {e.plain()}."

    def _ai_fix(self, ed, before: str, errs) -> str:
        """The AI suggests the fixed lines; offered first, kept only if it compiles with fewer errors."""
        system = ("You fix compile errors in a student's code. Answer with the WHOLE corrected file only, no "
                  "explanation, no markdown. Change as little as possible: only what the errors need.")
        user = "Errors:\n" + "\n".join(f"line {e.line}: {e.message}" for e in errs[:5]) + "\n\nCode:\n" + before
        try:
            out = self.think(system, user) or ""
        except Exception as e:
            log.warning("AI fix failed: %s", e)
            return f"There's an error: {errs[0].plain()}. I couldn't work out a fix."
        out = re.sub(r"^```\w*\n?|\n?```$", "", out.strip()).strip("\n")
        after = codecheck.errors(out, ed.lang)
        if after is None or len(after) >= len(errs) or codeedit.problem(out):
            return f"There's an error: {errs[0].plain()}. I couldn't find a fix I trust."
        old, new = before.split("\n"), out.split("\n")
        changed = [i for i in range(min(len(old), len(new))) if old[i].strip() != new[i].strip()]
        if len(changed) > 8 or abs(len(old) - len(new)) > 4:
            return f"There's an error: {errs[0].plain()}. The fix I found changes too much, so I left it."
        edit = codeedit.Edit(out, changed[0] if changed else 0, "Fixed it.", (changed[0], changed[-1]) if changed else (0, -1))
        self.pending = (edit, before, ed.title, out)
        where = f"line {changed[0] + 1}" if len(changed) == 1 else f"{len(changed)} lines"
        _popup("fix the errors", "\n".join(new[i] for i in changed[:6]), "Say yes to keep it")
        return f"{errs[0].plain()}. I can fix it by changing {where}; it's in the pop-up. Shall I?"

    def _offer_clear(self, ed) -> str:
        got = ed.read()
        if got is None:
            return "Not done: I can't read the code in this editor."
        before, _ = got
        self.pending = (codeedit.Edit("", 0, "Cleared the code. Say undo to bring it back.", (0, -1)), before,
                        ed.title, "")
        return "Clear all the code in this file? Say yes."

    # ---- writing it in, and undo -----------------------------------------------------------------------------------

    def _apply(self, ed, before: str, cursor: int | None, edit: codeedit.Edit, check: bool, heard: str = "") -> str:
        """Checked, written, read back, recorded. Never leaves broken code."""
        if not edit.changed:
            if edit.cursor is not None and edit.cursor != cursor:
                ed.place(edit.cursor)
            return edit.said
        why = codeedit.problem(edit.text)
        if why and not codeedit.problem(before):
            log.warning("Refusing an edit that unbalances the code: %s", why)
            return f"That would break the code ({why}), so I didn't change it."
        if check:
            fresh = codecheck.new_errors(before, edit.text, ed.lang)
            if fresh:
                fixed = codecheck.quick_fix(edit.text, ed.lang)
                if fixed and not codecheck.new_errors(before, fixed[0], ed.lang):
                    edit.text = fixed[0]
                else:
                    return f"That would break the code ({fresh[0].plain()}), so I didn't change it."
        result = self._write(ed, before, cursor, edit)
        if result != "ok":
            return result
        self.history.append(Change(before, edit.text, edit.said, edit.lines, ed.title))
        del self.history[:-30]
        self.redone.clear()
        try:
            host = codeedit.method_at(edit.text, edit.cursor)
            if host:
                self.last_method = host.name
        except codeedit.Unbalanced:
            pass
        new_lines = edit.text.split("\n")[edit.lines[0]:edit.lines[1] + 1] if edit.lines[1] >= edit.lines[0] else []
        _popup(heard, "\n".join(new_lines) or edit.said, edit.said)
        return edit.said

    def _write(self, ed, before: str, cursor: int | None, edit: codeedit.Edit) -> str:
        """Fast when the new lines go right below the cursor (End, then paste them); else the whole file."""
        old, new = before.split("\n"), edit.text.split("\n")
        k, n = edit.lines[0], edit.lines[1] - edit.lines[0] + 1
        below = cursor is not None and k == cursor + 1 and n > 0 and new[:k] == old[:k] and new[k + n:] == old[k:]
        if below and ed.insert_below(new[k:k + n], (k + n - 1) - edit.cursor):
            got = ed.read() if ed.cheap_read else None  # BlueJ: reading back is instant
            if got is None or codeedit.same(got[0], edit.text):
                return "ok"
            log.warning("%s: the quick insert came out differently; writing the whole file", ed.name)
        r = ed.write(edit.text, edit.cursor)
        if r != "ok":
            back = ed.write(before, cursor or 0)
            log.warning("Write failed (%s); put the code back: %s", r, back)
        return r

    def undo(self, ed) -> str:
        if not self.history:
            return "There's nothing of mine to undo."
        got = ed.read()
        if got is None:
            return "Not done: I can't read the code in this editor."
        last = self.history[-1]
        if last.title != ed.title or not codeedit.same(got[0], last.after):
            return ("The code has changed since my last edit, so I won't undo over it. Say control Z to use the "
                    "editor's own undo.")
        r = ed.write(last.before, max(0, last.span[0] - 1))
        if r != "ok":
            return r
        self.history.pop()
        self.redone.append(last)
        said = last.said.split(". Say undo")[0].rstrip(".")
        return f"Undone: {said[0].lower() + said[1:]}."

    def redo(self, ed) -> str:
        if not self.redone:
            return "There's nothing to redo."
        got = ed.read()
        change = self.redone[-1]
        if got is None or change.title != ed.title or not codeedit.same(got[0], change.before):
            return "The code has changed since, so I won't redo it."
        r = ed.write(change.after, max(0, change.span[1]))
        if r != "ok":
            return r
        self.redone.pop()
        self.history.append(change)
        return f"Redone: {change.said[0].lower() + change.said[1:]}"


def _ident(name: str) -> str:
    """'print sum' -> 'printSum' (a spoken method name)."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    return words[0].lower() + "".join(w.capitalize() for w in words[1:]) if words else "method"


def _popup(heard: str, code: str, title: str):
    from . import notify
    shown = "\n".join(code.split("\n")[:8])[:240]
    text = (f'Heard: "{heard}"\n' if heard else "") + shown
    notify.popup(f"{title}\n{text}", key=f"code-{time.monotonic()}")
