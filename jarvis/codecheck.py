"""The compiler check behind coding mode: never leave broken code (the user, 3 Oct).

The changed code is compiled in a hidden folder BEFORE it reaches the editor: Java with the javac that comes
with BlueJ, C++ with g++ -fsyntax-only (MSYS2). ~0.6-1 s, no window, nothing clicked. A change is kept only
when it adds no new error: a student's file is often mid-way (errors of their own), so errors that were there
before don't count, only new ones.

Simple errors are fixed in code ("fix the errors"): a missing semicolon, a missing closing brace.
"""

import functools
import glob
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import codeedit

log = logging.getLogger(__name__)

_JAVAC_PLACES = [r"~\OneDrive\Documents\BlueJ\bluej\jdk\bin\javac.exe", r"~\Documents\BlueJ\bluej\jdk\bin\javac.exe",
                 r"C:\Program Files\BlueJ\jdk\bin\javac.exe", r"C:\Program Files\Java\*\bin\javac.exe"]
_GPP_PLACES = [r"C:\msys64\ucrt64\bin\g++.exe", r"C:\msys64\mingw64\bin\g++.exe", r"C:\MinGW\bin\g++.exe"]
_TIMEOUT = 20


@dataclass(frozen=True)
class Error:
    line: int      # 1-based
    message: str

    def plain(self) -> str:
        """Said out loud: 'line 5: a semicolon is missing'."""
        m = self.message
        m = {"';' expected": "a semicolon is missing", "reached end of file while parsing":
             "a closing brace is missing at the end"}.get(m, m)
        m = re.sub(r"^expected .*';' before .*", "a semicolon is missing", m)
        m = re.sub(r"^cannot find symbol (\w+)$", r"\1 isn't known there", m)
        m = re.sub(r"^cannot find symbol$", "a name it doesn't know", m)
        m = re.sub(r"^'(\w+)' was not declared in this scope.*", r"\1 isn't declared", m)
        return f"line {self.line}: {m}"


@functools.lru_cache(maxsize=1)
def javac() -> str | None:
    for place in _JAVAC_PLACES:
        for hit in glob.glob(os.path.expanduser(place)):
            return hit
    return shutil.which("javac")


@functools.lru_cache(maxsize=1)
def gpp() -> str | None:
    return shutil.which("g++") or next((p for p in _GPP_PLACES if os.path.exists(p)), None)


def available(lang: str) -> bool:
    return bool(javac() if lang == "java" else gpp())


@functools.lru_cache(maxsize=64)
def errors(text: str, lang: str) -> tuple[Error, ...] | None:
    """The compiler's errors for this code (empty: it compiles), or None when there's no compiler."""
    tool = javac() if lang == "java" else gpp()
    if not tool:
        return None
    with tempfile.TemporaryDirectory(prefix="jarvis-check-") as d:
        if lang == "java":
            m = re.search(r"\bpublic\s+(?:final\s+|abstract\s+)*(?:class|interface|enum)\s+(\w+)", text)
            name = (m.group(1) if m else "Check") + ".java"
            src = Path(d) / name
            src.write_text(text, encoding="utf-8")
            cmd = [tool, "-d", str(Path(d) / "out"), "-encoding", "UTF-8", "-proc:none", "-Xmaxerrs", "30",
                   "-nowarn", str(src)]
            pat = re.compile(rf"^{re.escape(str(src))}:(\d+): error: (.+)$")
        else:
            src = Path(d) / "check.cpp"
            src.write_text(text, encoding="utf-8")
            cmd = [tool, "-fsyntax-only", "-fmax-errors=30", "-w", str(src)]
            pat = re.compile(rf"^{re.escape(str(src))}:(\d+):\d+: (?:fatal )?error: (.+)$")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT, cwd=d,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("Code check couldn't run: %s", e)
            return None
        out = []
        for ln in (r.stderr + r.stdout).splitlines():
            m = pat.match(ln.strip())
            if m:
                out.append(Error(int(m.group(1)), m.group(2).strip()))
                continue
            sym = re.match(r"\s*symbol:\s+(?:variable|method|class)\s+(\w+)", ln)
            if sym and out and out[-1].message == "cannot find symbol":
                # javac names the unknown thing on the next lines: "symbol: variable i"
                out[-1] = Error(out[-1].line, f"cannot find symbol {sym.group(1)}")
        if r.returncode and not out:
            log.warning("Code check failed with no readable error: %s", (r.stderr or r.stdout)[:300])
        return tuple(out)


def _key(e: Error) -> str:
    return re.sub(r"\d+", "#", e.message)


def new_errors(before: str, after: str, lang: str) -> list[Error] | None:
    """Errors the change brought in (by kind, not line: lines move). None: no compiler to ask."""
    a = errors(after, lang)
    if a is None:
        return None
    if not a:
        return []
    b = errors(before, lang) or ()
    left = Counter(_key(e) for e in b)
    fresh = []
    for e in a:
        if left[_key(e)]:
            left[_key(e)] -= 1
        else:
            fresh.append(e)
    return fresh


def quick_fix(text: str, lang: str) -> tuple[str, str] | None:
    """One error fixed in code, or None: (new text, what was done). Missing semicolons and closing braces."""
    errs = errors(text, lang)
    if not errs:
        return None
    lines = text.split("\n")
    e = errs[0]
    if "';' expected" in e.message or re.match(r"expected .*';' (?:before|at end)", e.message):
        # javac points at the line that needs it; g++ at the line after: the last code line up to there
        k = min(e.line, len(lines)) - 1
        if lang != "java" and k > 0 and not re.search(r"[;{}]\s*$", lines[k - 1].rstrip()):
            k -= 1
        while k > 0 and not codeedit.mask(lines[k]).strip():
            k -= 1
        line = lines[k].rstrip()
        cut = len(codeedit.mask(line).rstrip())
        lines[k] = line[:cut] + ";" + line[cut:]
        return "\n".join(lines), f"added the missing semicolon on line {k + 1}"
    why = codeedit.problem(text)
    if why and "never closed" in why and "'{'" in why:
        out = text.rstrip("\n")
        depth = sum(1 for _ in range(codeedit.mask(text).count("{") - codeedit.mask(text).count("}")))
        for d in range(depth - 1, -1, -1):
            out += "\n" + codeedit.unit(text) * d + "}"
        return out, "added the missing closing brace" + ("s" if depth > 1 else "")
    return None


def digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:10]
