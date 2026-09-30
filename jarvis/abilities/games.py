"""Games: "start eFootball", "close the game". Simple on purpose (the user, 30 Sep: "nothing fancy").

Mapped live on 30 Sep: eFootball starts through Windows' Gaming Services, whose window "eFootball™" shows
"Launching game…"; the game itself comes after. That day it crashed on start ("The game has crashed", error
0xc0000005: the game or the graphics driver, not Jarvis), so a start is watched for a couple of minutes and a crash
is reported as a pop-up. Closing is the normal close (never a forced kill), and it's checked.
"""

import os
import re
import threading
import time

import win32con
import win32gui

from . import ability
from ..skills import desktop

GAMES = {  # spoken name -> (app to start, a word in its window titles, name to say)
    "efootball": (r"shell:AppsFolder\KonamiDigitalEntertainmen.PES2022_168atcksx2mfc!Game", "football", "eFootball"),
}
_ALIASES = {"e football": "efootball", "your football": "efootball", "football": "efootball", "pes": "efootball",
            "the game": "efootball", "my game": "efootball", "game": "efootball"}
_GAME_WORDS = r"e ?football|efootball|your football|football|pes|(?:the |my )?game"


def _game(said: str):
    s = " ".join((said or "game").lower().split())
    key = _ALIASES.get(s, s)
    return GAMES.get(key)


def _windows(word: str) -> list[tuple[int, str, str]]:
    return [(h, p, t) for h, p, t in desktop._app_windows()
            if word in (p + " " + t).lower() and not p.startswith(("chrome", "msedge", "brave", "firefox"))]


def _crash_text(hwnd: int) -> str | None:
    try:
        UIA, uia = desktop._uia()
        f = uia.ElementFromHandle(hwnd).FindAll(UIA.TreeScope_Descendants, uia.CreateTrueCondition())
        names = [f.GetElement(i).CurrentName or "" for i in range(f.Length)]
    except Exception:
        return None
    if any("has crashed" in n.lower() for n in names):
        code = next((re.search(r"0x[0-9a-f]+", n, re.I).group(0) for n in names if re.search(r"0x[0-9a-f]+", n, re.I)), "")
        return code or "no code"
    return None


def _watch(word: str, name: str, seconds: float = 150):
    """In the background: tell the user (a pop-up) if the game crashes while starting."""
    from ..notify import popup
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(3)
        for h, _, _ in _windows(word):
            code = _crash_text(h)
            if code:
                popup(f"{name} crashed while starting (error {code}). That's the game or the graphics driver, "
                      "not Jarvis.", f"crash-{name}")
                return


@ability("start_game", "start a game (eFootball)",
         rf"(?:start|open|launch|play|run|load) (?:the |my )?(?P<value>{_GAME_WORDS})"
         r"(?! (?:on|in) (?:youtube|chrome|the browser))(?: game)?", value="game")
def start_game(said: str):
    game = _game(said)
    if not game:
        raise ValueError(f"no game called {said!r}")
    app, word, name = game
    if _windows(word):
        return f"{name} is already open."
    os.startfile(app)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if _windows(word):
            threading.Thread(target=_watch, args=(word, name), daemon=True).start()
            return f"Starting {name}. It takes about a minute."
    return f"Not done: {name} didn't start."


@ability("close_game", "close the game that's running",
         rf"(?:close|quit|exit|stop|end|shut down) (?:the |my )?(?P<value>{_GAME_WORDS})(?: game)?", value="game")
def close_game(said: str):
    game = _game(said)
    if not game:
        raise ValueError(f"no game called {said!r}")
    _, word, name = game
    wins = _windows(word)
    if not wins:
        return f"{name} isn't open."
    for h, _, _ in wins:
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)  # the normal close, never a forced kill
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if not _windows(word):
            return f"Closed {name}."
    return f"Not done: {name} is still open. Close it from the game's own menu, or say close it again."
