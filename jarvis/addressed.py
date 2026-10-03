"""Was that said TO Jarvis? Background speech (a TV, a call, people talking) must not become requests.

1 Oct, 21:23: a Hindi conversation in the room woke Jarvis and was heard as eight "requests" ("Ashwita Chhapya,
Bhaari, Bidwa, …", "I will come to the workshop alone. …"); each went to the AI and came back as "Could you
clarify…". The signs, all checked in code with no AI:

- **Not English.** Whisper is told the speech is English, so other languages come out as made-up words. A real
  English word is one piece of Whisper's own vocabulary; "Bhaari" or "Smebote" take three or more pieces.
- **A list of short scraps** ("Kais, Kuch Nei, Xtos, Vier, Blach, Plox, Plox, …"): nobody gives a command that way.
- **Long, unsure, and no sentence asks for anything**, in a follow-up (no "Hey Jarvis" just before it).

A command word at the start of a sentence ("Search for Best Biryani in Kolkata") always keeps it: names and
places are often not English words. Dictation is never filtered.
"""

import functools
import logging
import re

from .config import MODELS_DIR

log = logging.getLogger(__name__)

# Words that start a request (or a question) to Jarvis.
_COMMAND = re.compile(
    r"(open|close|play|pause|resume|stop|search|find|look|go|show|hide|click|press|hit|type|write|scroll|minimi[sz]e|"
    r"maximi[sz]e|restore|snap|mute|unmute|volume|turn|switch|set|start|launch|run|connect|disconnect|pair|send|"
    r"upload|download|read|tell|say|what|what's|whats|who|who's|how|why|when|where|which|can|could|would|will|is|are|"
    r"do|does|did|create|make|add|delete|remove|clear|select|copy|paste|cut|save|undo|redo|skip|next|previous|back|"
    r"take|put|move|increase|decrease|reduce|raise|lower|brightness|check|compile|call|email|mail|reply|fill|submit|"
    r"enter|exit|quit|leave|sign|log|refresh|reload|zoom|lock|sleep|restart|shut|give|let's|lets|help|explain|"
    r"remember|forget|translate|define|calculate|use|change|rename|drag|double|right|left|highlight|bookmark|"
    r"install|update|answer|draft|compose|reopen|enable|disable|keep|bring|focus|listen|watch|mark|print|"
    r"i want|i need|i'd like|please|yes|yeah|yep|yup|haan|no|nope|nah|okay|ok|sure|cancel|jarvis|hey|hi|hello|thanks|thank)\b",
    re.I)
# A clear action anywhere in a long sentence ("Whatever is in the address bar, cut it and open Claude").
_ACTION = re.compile(r"\b(open|close|search|click|type|select|delete|remove|send|cut|copy|paste|press|scroll|"
                     r"upload|download|minimi[sz]e|maximi[sz]e|mute|compile|apply|fill)\b", re.I)
_FILLER = re.compile(r"^(?:(?:so|and|then|now|okay|ok|um|uh|well|also|just|actually)[, ]+)+", re.I)
_SENTENCE = re.compile(r"[^.!?]+[.!?]*")
_WORD = re.compile(r"[A-Za-z']+")

FOREIGN_SHARE = 0.3  # this share of made-up words (in 5+ words) = not English
LIST_CHUNKS = 6  # a list of this many scraps (1-2 words each) = not a request
VERY_UNSURE = -0.9  # Whisper's confidence below this = it was guessing (clear speech ~ -0.05)
LOST = -1.2  # ...and this far below, on a long sentence, it was guessing at someone else's talk (-1.58 on 1 Oct)


@functools.lru_cache(maxsize=1)
def _tokenizer():
    """Whisper's own vocabulary (shipped with the local hearing models); None if it isn't there."""
    try:
        from tokenizers import Tokenizer
        for name in ("small.en", "base.en"):
            for path in (MODELS_DIR / "whisper").glob(f"models--Systran--faster-whisper-{name}/snapshots/*/tokenizer.json"):
                return Tokenizer.from_file(str(path))
    except Exception:
        log.warning("Couldn't load Whisper's vocabulary; foreign speech isn't filtered", exc_info=True)
    return None


@functools.lru_cache(maxsize=4096)
def is_odd_word(word: str, pieces: int = 3) -> bool:
    """Not an English word: three or more pieces of Whisper's vocabulary ("Bhaari", "Smebote")."""
    tok = _tokenizer()
    if tok is None:
        return False
    return min(len(tok.encode(" " + w, add_special_tokens=False).ids) for w in (word, word.lower())) >= pieces


def _starts_with_command(sentence: str) -> bool:
    return bool(_COMMAND.match(_FILLER.sub("", sentence.strip(" ,;:-\"'"))))


def background_reason(text: str, confidence: float | None = None, followup: bool = True) -> str | None:
    """Why `text` wasn't said to Jarvis, or None when it may well be a request."""
    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
    if any(_starts_with_command(s) for s in sentences):
        return None
    words = [w for w in _WORD.findall(text) if len(w) >= 3]
    if len(words) >= 5 and sum(map(is_odd_word, words)) >= FOREIGN_SHARE * len(words):
        return "not English"
    chunks = [c.strip() for c in re.split(r"[,.;!?]", text) if c.strip()]
    if len(chunks) >= LIST_CHUNKS and sum(len(c.split()) <= 2 for c in chunks) >= 0.7 * len(chunks):
        return "a list of scraps, not a request"
    if not followup or confidence is None or confidence >= VERY_UNSURE:
        return None
    if confidence < LOST and len(_WORD.findall(text)) >= 15 and not text.rstrip().endswith("?") \
            and not _ACTION.search(text):
        return "long, unclear, and asks for nothing"
    if len(words) == 1 and len(text.split()) == 1 and is_odd_word(words[0], 2):
        return "one unclear word"  # "Graho." heard in the same room talk
    return None
