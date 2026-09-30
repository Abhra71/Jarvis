"""The ability catalog: everything Jarvis can do in code, instantly, with no AI (Jarvis 4, layer 1).

An ability is a small, reliable piece of code plus the phrases that ask for it. Requests are
matched in this order (see assistant.py):
    1. site packs  2. abilities (phrases)  3. phrase memory  4. offline rules  5. the AI
The AI can use abilities too, through one compact tool, `do(ability, value)`. When the AI maps a
new phrasing onto a *safe* ability, the phrase is remembered (phrase memory), so next time it's
instant and costs no AI.

Adding an ability: write a function in one of the area modules and register it with @ability.
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import ROOT
from ..nlu import normalize

log = logging.getLogger(__name__)

LEARNED_FILE = ROOT / "data" / "learned.json"


@dataclass
class Ability:
    name: str                   # "snap_left": what the AI calls it
    summary: str                # "snap the front window to the left half": for the AI's catalog
    run: Callable[..., str]     # run(value) -> spoken reply
    patterns: list[re.Pattern] = field(default_factory=list)  # full-match on normalized speech; group "value"
    value_hint: str = ""        # "0-100", "setting name": shown to the AI when the ability takes a value
    safe: bool = True           # False: never remembered as a phrase (the user must say it clearly each time)


REGISTRY: dict[str, Ability] = {}


def ability(name: str, summary: str, *phrases: str, value: str = "", safe: bool = True):
    """Register an ability. Phrases are regexes matched against the whole normalized request;
    a named group (?P<value>…) is passed to the function."""
    def wrap(fn):
        REGISTRY[name] = Ability(name, summary, fn, [re.compile(f"^(?:{p})$") for p in phrases], value, safe)
        return fn
    return wrap


def match(text: str) -> tuple[Ability, str | None] | None:
    t = normalize(text)
    for ab in REGISTRY.values():
        for p in ab.patterns:
            m = p.match(t)
            if m:
                return ab, (m.groupdict().get("value") or None)
    return None


def run(name: str, value: str | None = None) -> str:
    ab = REGISTRY.get(name)
    if not ab:
        return f"Unknown ability {name}. Choose from: {', '.join(REGISTRY)}."
    try:
        return ab.run(value) if ab.value_hint else ab.run()
    except (TypeError, ValueError) as e:
        return f"Not done: {e}"


def catalog_text() -> str:
    """What the AI needs beyond the ability names (which it sees as the tool's enum, and which explain
    themselves): the values some abilities take. Kept short, because it goes with every command."""
    values = "; ".join(f"{a.name}: {a.value_hint}" for a in REGISTRY.values() if a.value_hint)
    return f"Values: {values}." if values else ""


def declaration() -> dict:
    return {"name": "do",
            "description": "Do a built-in ability (instant, exact; prefer it over clicks or keys). " + catalog_text(),
            "parameters": {"type": "OBJECT", "required": ["ability"], "properties": {
                "ability": {"type": "STRING", "enum": list(REGISTRY)},
                "value": {"type": "STRING"}}}}


# ---- phrase memory -------------------------------------------------------------

class PhraseMemory:
    """Phrasings the AI worked out once, remembered so they're instant (and free) next time.
    Only exact (normalized) phrases, only safe abilities, and only when speech recognition was sure."""

    def __init__(self, path: Path = LEARNED_FILE):
        self.path = path
        self.lock = threading.Lock()
        try:
            self.phrases: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.phrases = {}

    def get(self, text: str) -> tuple[str, str | None] | None:
        hit = self.phrases.get(normalize(text))
        return (hit["ability"], hit.get("value")) if hit and hit.get("ability") in REGISTRY else None

    def learn(self, text: str, name: str, value: str | None):
        ab = REGISTRY.get(name)
        key = normalize(text)
        if not ab or not ab.safe or not key or len(key.split()) > 12 or match(text):
            return  # unsafe, too long to be a command, or already understood by the patterns
        with self.lock:
            self.phrases[key] = {"ability": name, **({"value": value} if value else {})}
            try:
                self.path.parent.mkdir(exist_ok=True)
                self.path.write_text(json.dumps(self.phrases, indent=1, sort_keys=True), encoding="utf-8")
            except OSError:
                log.warning("Couldn't save learned phrases", exc_info=True)
        log.info("Learned %r -> %s(%s)", key, name, value or "")


memory = PhraseMemory()


def handle(text: str, unsure: bool = False) -> str | None:
    """Reply if an ability (or a remembered phrase) covers this request, else None."""
    hit = match(text)
    if hit:
        ab, value = hit
        log.info("Ability %s(%s)", ab.name, value or "")
        return run(ab.name, value)
    if not unsure:
        remembered = memory.get(text)
        if remembered:
            log.info("Remembered phrase -> %s(%s)", *remembered)
            return run(*remembered)
    return None


from . import browser, files, windows  # noqa: E402,F401  (registers the abilities)
