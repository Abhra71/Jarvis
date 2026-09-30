"""Corrections: "No, I meant Claude." fixes the last request AND is remembered (Phase 5).

30 Sep: "Open Clawed" → Jarvis searched Google for a game; "No, there is an app called Clawed…" → the same again.
A person would have said "Oh, Claude!" and never made that mistake again. Now:

    Open Clawed.            → (did the wrong thing, or asked)
    No, I meant Claude.     → redoes "Open Claude."  and learns  clawed → claude

A learned pair is applied to what's heard before anything else sees it, so the next "Open Clawed" is "Open
Claude". Only pairs that SOUND alike are learned (a real mishearing, not a change of mind: "no, I meant Chrome"
after "open Edge" is a new request, not a hearing fix). "Forget that" removes the last one.
"""

import json
import logging
import re
import threading
from pathlib import Path

from rapidfuzz import fuzz

from .config import ROOT
from .skills.apps import sound_key

log = logging.getLogger(__name__)

FILE = ROOT / "data" / "corrections.json"

# "no, I meant Claude" / "no I said Claude" / "not clawed, Claude" / "I meant Claude" / "it's Claude, not clawed"
_MEANT = re.compile(
    r"^(?:no|nope|nah|wrong|not that)?[,.!]?\s*(?:i|jarvis,? i)\s+(?:meant|mean|said)\s+(?P<meant>.+?)[.!]?$"
    r"|^(?:no|nope)[,.!]?\s+(?:it'?s|it is)\s+(?P<meant2>.+?)(?:,? not .+)?[.!]?$"
    r"|^not (?P<wrong3>.+?)[,.]\s*(?P<meant3>.+?)[.!]?$", re.I)
_FORGET = re.compile(r"^(?:please )?forget (?:that|it|what i (?:just )?(?:said|taught you)|that correction)[.!]?$",
                     re.I)
_FILLER = re.compile(r"^(?:the|a|an|my)\s+|\s+(?:app|application|website|site|please)$", re.I)


def meant(said: str) -> str | None:
    """'No, I meant Claude.' -> 'Claude'; None if it isn't a correction."""
    m = _MEANT.match(said.strip())
    if not m:
        return None
    word = next(g for g in (m.group("meant"), m.group("meant2"), m.group("meant3")) if g)
    word = _FILLER.sub("", word.strip(" ,.!?\"'")).strip()
    return word if 0 < len(word.split()) <= 4 else None


def is_forget(said: str) -> bool:
    return bool(_FORGET.match(said.strip()))


def _grams(words: list[str], n: int):
    for i in range(len(words) - n + 1):
        yield i, " ".join(words[i:i + n])


def misheard_part(previous: str, right: str) -> str | None:
    """The words of the previous request that were a mishearing of `right` ("Open Clawed." + "Claude" ->
    "Clawed"), or None when nothing there sounds like it."""
    words = re.findall(r"[\w'-]+", previous)
    want = sound_key(right)
    best, best_score = None, 0.0
    for n in (1, 2, 3):
        for _, gram in _grams(words, n):
            if gram.lower() == right.lower():
                return None  # it was heard right; this is something else
            key = sound_key(gram)
            if not key or key[0] != want[:1]:
                continue
            score = fuzz.ratio(key, want)
            if score > best_score:
                best, best_score = gram, score
    return best if best_score >= 70 else None


class Corrections:
    def __init__(self, path: Path | None = FILE):
        self.path = path
        self.lock = threading.Lock()
        self.pairs: dict[str, str] = {}
        self.last_learned: str | None = None
        if path:
            try:
                self.pairs = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.pairs = {}

    def fix(self, previous: str, said: str) -> tuple[str, str | None] | None:
        """(the corrected request, the misheard words or None) for a correction of `previous`; else None."""
        right = meant(said)
        if not right or not previous:
            return None
        wrong = misheard_part(previous, right)
        if wrong:
            fixed = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", right, previous, count=1, flags=re.I)
            return fixed, wrong
        return None

    def learn(self, wrong: str, right: str):
        with self.lock:
            self.pairs[wrong.lower()] = right
            self.last_learned = wrong.lower()
            self._save()
        log.info("Learned a correction: %r means %r", wrong, right)

    def forget_last(self) -> str | None:
        with self.lock:
            key = self.last_learned
            if not key or key not in self.pairs:
                return None
            right = self.pairs.pop(key)
            self.last_learned = None
            self._save()
        log.info("Forgot the correction %r -> %r", key, right)
        return f"{key} means {right}"

    def apply(self, text: str) -> str:
        """What was heard, with learned mishearings fixed ("Open Clawed." -> "Open Claude.")."""
        if not self.pairs:
            return text
        out = text
        for wrong, right in sorted(self.pairs.items(), key=lambda kv: -len(kv[0])):
            out = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", right, out, flags=re.I)
        if out != text:
            log.info("Corrected what was heard: %r -> %r", text, out)
        return out

    def words(self) -> list[str]:
        """The right words, for the speech recogniser's hint."""
        return sorted(set(self.pairs.values()))

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(self.pairs, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            log.warning("Couldn't save the corrections", exc_info=True)
