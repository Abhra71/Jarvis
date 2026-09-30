"""YouTube by voice, with no AI: search and play, player control, skip ads.

Everything here reads the page through Windows UI Automation (see elements.py):
- On a results page, a real video's title link ends with its length ("... 1 hour, 1 minute",
  "... 4 minutes, 37 seconds"). Ads, Shorts, channels and live streams don't, so "play X" takes
  the first link that does. (Checked on a real results page, 27 Sep.)
- The player's buttons (read 27 Sep): "Play keyboard shortcut k" / "Pause keyboard shortcut k", "Mute (m)",
  "Full screen (f)", "Theater mode (t)", "Next", "Subtitles/closed captions (c)"; the ad button starts
  with "Skip". Names differ a little between versions, so they're matched by their start.
  They're pressed with UI Automation's Invoke, so the mouse doesn't move and focus doesn't matter.
- Seeking and speed have no buttons: YouTube's own keys (l/j = 10 s, Shift+> / Shift+<).
"""

import logging
import re
import time
from urllib.parse import quote_plus

import win32gui
from pywinauto import keyboard

from .. import desktop, elements
from ...nlu import normalize

log = logging.getLogger(__name__)

RESULTS_URL = "https://www.youtube.com/results?search_query={q}"
_DURATION = re.compile(r"\s(\d+ (hours?|minutes?|seconds?))(, \d+ (minutes?|seconds?))*$")
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
             "fifth": 5, "5th": 5, "sixth": 6, "6th": 6, "last": -1}
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def is_front(title: str) -> bool:
    return "youtube" in (title or "").lower()


def video_title(link_name: str) -> str | None:
    """'Chill Lofi Mix 1 hour, 44 minutes' -> 'Chill Lofi Mix'; None if the link isn't a normal video."""
    m = _DURATION.search(link_name or "")
    return link_name[:m.start()].strip() if m else None


# ---- reading and pressing things on the page ----------------------------------------

def _doc(hwnd):
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd)
    doc = root.FindFirst(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_DocumentControlTypeId))
    return UIA, uia, doc or root


def _find_all(hwnd, control: str):
    UIA, uia, doc = _doc(hwnd)
    found = doc.FindAll(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, getattr(UIA, f"UIA_{control}ControlTypeId")))
    return UIA, [found.GetElement(i) for i in range(found.Length)]


def video_links(hwnd) -> list[tuple[str, object]]:
    """Real videos on the page, top to bottom: (title, element)."""
    _, links = _find_all(hwnd, "Hyperlink")
    out, seen = [], set()
    for e in sorted(links, key=lambda e: e.CurrentBoundingRectangle.top):
        title = video_title(" ".join((e.CurrentName or "").split()))
        if title and title not in seen:
            seen.add(title)
            out.append((title, e))
    return out


def _invoke(UIA, e) -> bool:
    try:
        e.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
        return True
    except Exception:
        log.debug("Invoke failed", exc_info=True)
        return False


def _open(UIA, e):
    """Open a link: click it where you can see it, else invoke it (it may be below the fold)."""
    r = e.CurrentBoundingRectangle
    if not e.CurrentIsOffscreen and r.right > r.left:
        elements.click(elements.Element("link", e.CurrentName or "", (r.left, r.top, r.right, r.bottom)))
    elif not _invoke(UIA, e):
        e.SetFocus()
        keyboard.send_keys("{ENTER}")


def _button(hwnd, *prefixes: str):
    UIA, buttons = _find_all(hwnd, "Button")
    for prefix in prefixes:
        for e in buttons:
            if (e.CurrentName or "").strip().lower().startswith(prefix.lower()):
                return UIA, e
    return UIA, None


def has_button(hwnd, *prefixes: str) -> bool:
    return _button(hwnd, *prefixes)[1] is not None


def press_button(hwnd, *prefixes: str) -> str | None:
    """Invoke the first player button whose name starts with one of the prefixes; its name, or None."""
    UIA, e = _button(hwnd, *prefixes)
    if e is not None and _invoke(UIA, e):
        return (e.CurrentName or "").strip()
    return None


def _keys(hwnd, keys: str, times: int = 1):
    """YouTube's own shortcuts. They need the page (ideally the player) to have the keyboard: after a search
    the focus is often in the search box or on Chrome's own toolbar, and the key goes nowhere (30 Sep)."""
    UIA, uia, doc = _doc(hwnd)
    try:
        focused = uia.GetFocusedElement()
        player = doc.FindFirst(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
            UIA.UIA_NamePropertyId, "YouTube Video Player"))
        if focused.CurrentControlType in (UIA.UIA_EditControlTypeId, UIA.UIA_ComboBoxControlTypeId)                 or not uia.CompareElements(focused, player or doc):
            (player or doc).SetFocus()
            time.sleep(0.05)
    except Exception:
        log.debug("Couldn't move the keyboard to the page", exc_info=True)
    for _ in range(max(1, min(times, 30))):
        keyboard.send_keys(keys, vk_packet=False)
        time.sleep(0.05)


# ---- what you can say ------------------------------------------------------------

_PLAY_SEARCH = re.compile(r"^(?:play|put on|listen to|watch)\s+(.+?)\s+(?:on|in|from)\s+youtube$|"
                          r"^(?:youtube\s+)?(?:play|put on)\s+(.+)$")
_SEARCH = re.compile(r"^(?:search for|search|look up|find)\s+(.+?)(?:\s+(?:on|in)\s+youtube)?(?:\s+here)?$")
_NTH = re.compile(r"^(?:play|open|watch|click|start)\s+(?:the\s+)?(\w+)\s+(?:video|one|result)\b")
_SEEK = re.compile(r"\b(forward|ahead|back|backward|rewind)\b(?:\s+(?:by\s+)?(\d+|\w+)\s+(seconds?|secs?|minutes?|mins?))?")

_PAUSE = ("Pause keyboard", "Pause (k)", "Pause")
_PLAY = ("Play keyboard", "Play (k)")

_CONTROLS = [  # (pattern, button prefixes to try, spoken reply, fallback key)
    (re.compile(r"^(pause|stop)( (it|this|the video|video|youtube))?$"), _PAUSE, "Paused.", None),
    (re.compile(r"^(play|resume|continue|unpause)( (it|this|the video|video|youtube))?$"), _PLAY, "Playing.", None),
    (re.compile(r"^(skip|skip the|skip this) ads?$|^skip( the)? advert"), ("Skip",), "Skipped the ad.", None),
    (re.compile(r"^(next|next video|play the next (video|one)|skip (this )?video)$"), ("Next",), "Next video.", "+n"),
    (re.compile(r"^mute (the )?(video|youtube)$"), ("Mute",), "Muted the video.", "m"),
    (re.compile(r"^unmute (the )?(video|youtube)$"), ("Unmute",), "Unmuted the video.", "m"),
    # Full screen by the F key only: browsers ignore a full-screen request that doesn't come from a real key or
    # click, so pressing the button through UI Automation did nothing (30 Sep live test).
    (re.compile(r"^(go )?full ?screen|^make it full ?screen|^maximi[sz]e the video"), (), "Full screen.", "f"),
    (re.compile(r"^(exit|leave|close) full ?screen"), (), "Left full screen.", "f"),
    (re.compile(r"^theatre|^theater|^cinema mode"), ("Theater mode", "Theatre mode"), "Theatre mode.", "t"),
    (re.compile(r"\b(captions|subtitles)\b"), ("Subtitles/closed captions",), "Toggled subtitles.", "c"),
]


def _number(word: str | None, default: int) -> int:
    if not word:
        return default
    return int(word) if word.isdigit() else _NUMBERS.get(word, default)


# Words that point at what's on screen or said before: "search it in this channel" needs the AI.
_CONTEXT = re.compile(r"\b(it|this|that|these|those|here|channel|page|same|one)\b")


def _free_query(query: str, unsure: bool) -> bool:
    """Can the code search/play this as-is? Not when speech recognition was unsure (27 Sep: "a nice
    runviercing polygood song"), and not when it refers to context."""
    return bool(query) and not unsure and not _CONTEXT.search(query)


def understands(text: str, unsure: bool = False) -> bool:
    """Is this a YouTube command the pack can do in code? (No screen reading: for the agent's code plans.)"""
    t = normalize(text)
    m = _NTH.match(t)
    if m and (m.group(1) in _ORDINALS or m.group(1) in _NUMBERS):
        return True
    if any(p.search(t) for p, *_ in _CONTROLS):
        return True
    m = _SEEK.search(t)
    if m and (m.group(3) or m.group(1) in ("forward", "ahead", "rewind")):
        return True
    if re.search(r"\b(faster|speed up|slower|slow down)\b", t):
        return True
    m = _PLAY_SEARCH.match(t)
    query = m and (m.group(1) or m.group(2) or "").strip()
    return bool(query) and _free_query(query, unsure) and query not in ("the video", "video", "youtube")


def command(text: str, browser) -> str:
    """The agent's `youtube` tool: one command, done by the pack, or why not."""
    t = text.strip()
    if re.match(r"^(play|put on|listen to|watch)\b", t, re.I) and not re.search(r"\byoutube\b", t, re.I) \
            and not _NTH.match(normalize(t)):
        t += " on youtube"  # "play lofi" means search and play, wherever you are
    return handle(t, browser) or ("Not done: the YouTube pack can't do that here (is YouTube in front?). "
                                  "Use press_key with YouTube's shortcuts or click_element.")


def handle(text: str, browser, unsure: bool = False) -> str | None:
    """Reply if this is a YouTube command we can do in code, else None (the AI takes it)."""
    t = normalize(text)
    hwnd = win32gui.GetForegroundWindow()
    front = win32gui.GetWindowText(hwnd)
    in_front = is_front(front) and desktop._process_name(hwnd) in desktop.BROWSERS

    if not in_front:
        m = _PLAY_SEARCH.match(t)
        if m and m.group(1) and _free_query(m.group(1).strip(), unsure):  # "play X on YouTube" from anywhere
            return play(m.group(1).strip(), None, browser)
        return None

    m = _NTH.match(t)
    if m and (m.group(1) in _ORDINALS or m.group(1) in _NUMBERS):
        return play_nth(hwnd, _ORDINALS.get(m.group(1)) or _NUMBERS[m.group(1)])

    reply = _control(hwnd, t)
    if reply is not False:
        return reply

    m = _PLAY_SEARCH.match(t)
    if m:
        query = (m.group(1) or m.group(2)).strip()
        if _free_query(query, unsure) and query not in ("the video", "video", "youtube"):
            return play(query, hwnd, browser)

    m = _SEARCH.match(t)
    if m and _free_query(m.group(1), unsure):
        desktop.address_bar(RESULTS_URL.format(q=quote_plus(m.group(1))))
        return f"Here are the YouTube results for {m.group(1)}."
    return None


_OFF = re.compile(r"\b(off|disable|hide|remove|stop|exit|leave|close|no)\b")
_ON = re.compile(r"\b(on|enable|show|turn on|start|want|with)\b")


def _pressed(e) -> bool:
    return "pressed=true" in (e.CurrentAriaProperties or "")


def _wait(test, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if test():
            return True
        time.sleep(0.15)
    return test()


def fullscreen(hwnd, want: bool = True) -> str:
    """Full screen as a goal, not a toggle (30 Sep: a second F, meant as a retry, switched it back off).
    Pressed with the F key: browsers ignore a full-screen request that isn't a real key press or click."""
    if elements.is_fullscreen() == want:
        return "It's already full screen." if want else "It's not in full screen."
    for _ in range(2):  # right after a video opens, the player may not take the key yet
        _keys(hwnd, "f")
        if _wait(lambda: elements.is_fullscreen() == want, 1.5):
            return "Full screen." if want else "Left full screen."
    return "Not done: the video didn't go full screen." if want else "Not done: it's still in full screen."


def subtitles(hwnd, t: str) -> str:
    """'turn on subtitles' only turns them on (the button says whether they're on)."""
    UIA, e = _button(hwnd, "Subtitles")
    if e is None:
        return "Not done: I can't find the subtitles button (is a video open?)."
    if "unavailable" in (e.CurrentName or "").lower():
        return "This video has no subtitles."
    want = False if _OFF.search(t) else (True if _ON.search(t) else not _pressed(e))
    if _pressed(e) == want:
        return f"Subtitles are already {'on' if want else 'off'}."
    if not _invoke(UIA, e):
        _keys(hwnd, "c")
    if _wait(lambda: _pressed(_button(hwnd, "Subtitles")[1]) == want, 1.5):
        return f"Subtitles {'on' if want else 'off'}."
    return "Not done: the subtitles didn't change."


def _control(hwnd, t: str):
    """Player commands: the reply, None (recognised but let the AI deal with it), or False (not one)."""
    if re.search(r"\b(captions|subtitles)\b", t):
        return subtitles(hwnd, t)
    if re.search(r"^(exit|leave|close) full ?screen|^(go )?full ?screen|^make it full ?screen|^maximi[sz]e the video", t):
        return fullscreen(hwnd, not re.match(r"^(exit|leave|close)", t))
    for pattern, prefixes, reply, key in _CONTROLS:
        if pattern.search(t):
            # Already in that state? Say so instead of toggling it the wrong way.
            if prefixes == _PAUSE and not has_button(hwnd, *_PAUSE) and has_button(hwnd, *_PLAY):
                return "It's already paused."
            if prefixes == _PLAY and not has_button(hwnd, *_PLAY) and has_button(hwnd, *_PAUSE):
                return "It's already playing."
            if press_button(hwnd, *prefixes):
                return reply
            if key:
                _keys(hwnd, key)
                return reply
            if prefixes == ("Skip",):
                return "I don't see a skip button yet. It usually appears after five seconds."
            return None  # let the AI look at it

    m = _SEEK.search(t)
    # "back 30 seconds", "forward", "rewind": seeking. Plain "back" / "go back" is the browser's back.
    if m and (m.group(3) or m.group(1) in ("forward", "ahead", "rewind")):
        amount = _number(m.group(2), 10)
        seconds = amount * 60 if m.group(3) and m.group(3).startswith("min") else amount
        forward = m.group(1) in ("forward", "ahead")
        _keys(hwnd, "l" if forward else "j", max(1, round(seconds / 10)))
        return f"{'Forward' if forward else 'Back'} {seconds} seconds."

    if re.search(r"\b(faster|speed up|increase (the )?speed)\b", t):
        _keys(hwnd, "+.")
        return "Faster."
    if re.search(r"\b(slower|slow down|decrease (the )?speed)\b", t):
        _keys(hwnd, "+,")
        return "Slower."
    return False


def _wait_for_videos(hwnd, seconds: float = 8.0) -> list:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            videos = video_links(hwnd)
            if videos:
                return videos
        except Exception:
            log.debug("Results not readable yet", exc_info=True)
        time.sleep(0.3)
    return []


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 "
       "Safari/537.36")
_INITIAL_DATA = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)


def first_video(query: str) -> tuple[str, str] | None:
    """(video id, title) of the first real video for a search, read in the background (~1.3 s) instead of
    loading the results page in the browser and waiting for it (~5 s, 30 Sep live test). Same rule as on
    the page: a normal video has a length; ads, Shorts, channels, playlists and live streams don't."""
    import json

    import httpx
    try:
        r = httpx.get("https://www.youtube.com/results", params={"search_query": query}, timeout=3.5,
                      headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}, follow_redirects=True)
        m = _INITIAL_DATA.search(r.text)
        data = json.loads(m.group(1)) if m else None
    except Exception:
        log.info("YouTube background search failed; using the page", exc_info=True)
        return None
    stack = [data]
    while stack:  # depth-first, in page order
        o = stack.pop()
        if isinstance(o, dict):
            v = o.get("videoRenderer")
            if v and v.get("videoId") and v.get("lengthText"):
                title = "".join(run.get("text", "") for run in v.get("title", {}).get("runs", []))
                return v["videoId"], title.strip()
            stack.extend(reversed(list(o.values())))
        elif isinstance(o, list):
            stack.extend(reversed(o))
    return None


def _wait_for_title(words: str, seconds: float = 6.0) -> bool:
    """Did the video's page open (the tab's title shows it)?"""
    want = normalize(words)[:25]
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if want and want in normalize(win32gui.GetWindowText(win32gui.GetForegroundWindow())):
            return True
        time.sleep(0.2)
    return False


def _started(title: str) -> str:
    """Only say "Playing" once Windows reports it playing (it also means the player is ready for keys)."""
    from ...agent import ocr
    try:
        if _wait(lambda: ocr.playing() is True, 5.0):
            return f"Playing {title}."
    except Exception:
        log.debug("Couldn't read the media status", exc_info=True)
        return f"Opened {title}."
    return f"Opened {title}, but it isn't playing yet."


def play(query: str, hwnd: int | None, browser) -> str:
    """Search YouTube and play the first real video (not an ad, Short, channel or live stream)."""
    found = first_video(query)
    if found:
        video_id, title = found
        url = f"https://www.youtube.com/watch?v={video_id}"
        if hwnd:
            desktop.address_bar(url)
        else:
            browser.open(url, None)
        if _wait_for_title(title):
            log.info("YouTube: opened %r for %r", title, query)
            return _started(title)
        log.info("YouTube: %r didn't open in time; trying the results page", title)
        hwnd = win32gui.GetForegroundWindow() if is_front(win32gui.GetWindowText(win32gui.GetForegroundWindow()))             else hwnd
    url = RESULTS_URL.format(q=quote_plus(query))
    if hwnd:
        desktop.address_bar(url)
    else:
        browser.open(url, None)
        time.sleep(1.0)
        hwnd = win32gui.GetForegroundWindow()
        if not is_front(win32gui.GetWindowText(hwnd)):
            time.sleep(1.0)
            hwnd = win32gui.GetForegroundWindow()
    time.sleep(0.8)  # let the old page go, so we don't pick from it
    videos = _wait_for_videos(hwnd)
    if not videos:
        return f"I searched YouTube for {query}, but couldn't find a video to play."
    title, e = videos[0]
    UIA, _ = _find_all(hwnd, "Hyperlink")
    _open(UIA, e)
    log.info("YouTube: playing %r for %r", title, query)
    return f"Playing {title}."


def play_nth(hwnd, n: int) -> str:
    videos = video_links(hwnd)
    if not videos:
        return None
    if n == -1:
        n = len(videos)
    if n > len(videos):
        return f"I can only see {len(videos)} videos here."
    title, e = videos[n - 1]
    UIA, _ = _find_all(hwnd, "Hyperlink")
    _open(UIA, e)
    return f"Playing {title}."
