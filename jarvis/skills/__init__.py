"""Everything Jarvis can do, as a list of tools.

The offline rules (nlu.py) and Gemini (brain.py) both call the same tools. Each tool
has a Gemini function declaration next to it so the AI knows when and how to use it.
Every tool returns a short sentence describing what happened.
"""

import logging
import re
import threading
from dataclasses import dataclass
from typing import Callable

from ..nlu import Intent, normalize
from ..usage import usage
from . import desktop, files, mouse, volume
from .apps import AppLauncher
from .browser import SEARCH_URLS, SITES, Browser
from .timer import Timers

log = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    params: dict           # name -> (type, description, required, enum or None)
    fn: Callable[..., str]

    def declaration(self) -> dict:
        props, required = {}, []
        for pname, (ptype, pdesc, req, enum) in self.params.items():
            props[pname] = {"type": ptype, **({"description": pdesc} if pdesc else {})}
            if enum:
                props[pname]["enum"] = enum
            if req:
                required.append(pname)
        decl = {"name": self.name, "description": self.description}
        if props:
            decl["parameters"] = {"type": "OBJECT", "properties": props, "required": required}
        return decl


S, I, B = "STRING", "INTEGER", "BOOLEAN"

# Hard safety check in code (not just an instruction to the AI): these need the user's spoken "yes".
_RISKY_CLICK = re.compile(
    r"\b(send|post|publish|tweet|buy|purchase|pay|payment|checkout|check out|place order|order now|subscribe|"
    r"delete|remove|trash|sign in|log in|login|submit|transfer|confirm|donate|install)\b", re.I)
_CHAT_APPS = ("whatsapp", "telegram", "discord", "slack", "messenger", "instagram", "gmail", "outlook", "teams",
              "signal", "mail")


# These don't change what's on screen, so a screenshot taken before them is still valid for clicking.
_READ_ONLY_TOOLS = {"find_files", "list_folder", "read_text_file"}
# What the offline rules leave of a spoken web address ("chess dot com" / "chess.com" -> "chess com").
_DOMAIN = re.compile(r"[a-z0-9][a-z0-9 -]{0,40} (com|org|net|io|live|ai|dev)")  # not "in": "open sign in"


def site_url(app: str) -> str | None:
    """The website an offline "open X" means, if X is a known site or a spoken address ("wikipedia dot org")."""
    if app in SITES:
        return SITES[app]
    if _DOMAIN.fullmatch(app):
        name, tld = app.rsplit(" ", 1)
        return f"https://www.{name.replace(' ', '')}.{tld}"
    return None


def needs_confirmation(name: str, args: dict, front_window) -> str | None:
    """If this action is the kind that can't be taken back, describe it; else None."""
    if name in ("click", "click_pair"):
        target = str(args.get("target", ""))
        if _RISKY_CLICK.search(target):
            return f"click '{target}'"
        return None
    sends_enter = (name == "type_text" and args.get("press_enter")) or (
        name == "press_key" and str(args.get("key", "")).lower() == "enter")
    if sends_enter:
        try:
            front = front_window().lower()
        except Exception:
            front = ""
        if any(app in front for app in _CHAT_APPS):
            return "press Enter in a chat or mail window, which sends the message"
    return None


# Tools that act on the screen like the user's own hands. A request may use only as many as it asked for:
# on 26 Sep Jarvis played an extra chess move and kept clicking after "No thanks". Enforced here in code.
_HANDS = {"click", "click_pair", "type_text", "press_key"}
_PARTS = re.compile(r"\s*(?:,|;|\bafter that\b|\band then\b|\bthen\b|\band\b)\s*", re.I)
_ONE_ACTION = re.compile(r"^(click|tap|press|hit|select|choose|move|castle|pause|skip|close the pop ?up)\b|"
                         r"\b(pawn|knight|bishop|rook|queen|king|castle|takes)\b|\b[a-h][1-8]\b")
_TYPING = re.compile(r"^(type|write|enter|fill in)\b")  # may need a click on the field first
_REPEATS = re.compile(r"\b(twice|thrice|\d+ times|every|all|each)\b")
OPEN_ENDED_ACTIONS = 3


def action_budget(request: str, open_ended: int = OPEN_ENDED_ACTIONS) -> int:
    """How many hands-on actions (clicks, drags, typing, key presses) a request asks for.

    "Click No thanks" = 1, "move e2 to e4" = 1, "type hello" = 2 (focus the field, then type),
    anything open-ended = `open_ended` per part. "X and Y" adds the parts up.
    """
    total = 0
    for part in _PARTS.split(request or ""):
        part = normalize(part)
        if not part:
            continue
        if _REPEATS.search(part):
            total += open_ended
        elif _ONE_ACTION.search(part):
            total += 1
        elif _TYPING.search(part):
            total += 2
        else:
            total += open_ended
    return max(total, 1)


_COORDS = {"x", "y", "x2", "y2"}


def check_args(tool: "Tool", args: dict) -> tuple[dict, str | None]:
    """Tidy the AI's arguments, or say what's wrong so it can fix them in the same round.
    (A missing y2 in click_pair crashed a chess move on 26 Sep.)"""
    clean, problems = {}, []
    for pname, (ptype, _, required, enum) in tool.params.items():
        v = args.get(pname)
        if v is None or v == "":
            if required:
                problems.append(f"missing {pname}")
            continue
        try:
            if ptype == I:
                v = int(round(float(v)))
            elif ptype == B:
                v = v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1")
            else:
                v = str(v)
        except (TypeError, ValueError):
            problems.append(f"{pname} must be a number, not {v!r}")
            continue
        if enum:
            match = next((e for e in enum if str(e).lower() == str(v).strip().lower()), None)
            if match is None:
                problems.append(f"{pname} must be one of {', '.join(map(str, enum))}")
                continue
            v = match
        if pname in _COORDS and tool.name in ("click", "click_pair", "scroll", "hover") and not 0 <= v <= 1000:
            problems.append(f"{pname}={v} is off screen (positions are 0-1000)")
            continue
        clean[pname] = v
    extra = set(args) - set(tool.params)
    if extra:
        log.info("Ignoring unknown args for %s: %s", tool.name, sorted(extra))
    if problems:
        needed = ", ".join(p for p, spec in tool.params.items() if spec[2])
        return clean, (f"Not done: {'; '.join(problems)}. Call {tool.name} again with correct args"
                       f"{f' (required: {needed})' if needed else ''}.")
    return clean, None


class Skills:
    def __init__(self, config: dict, announce: Callable[[str], None]):
        self.config = config
        self.apps = AppLauncher(config.get("apps", {}))
        self.browser = Browser(config.get("chrome_profiles", {}))
        self.timers = Timers(announce)
        self.calls_made = 0  # lets the assistant tell whether the AI already did something this turn
        self.cancel = threading.Event()  # set when the user says "Hey Jarvis" mid-task: stop at the next step
        self.confirmed = False  # the user just said "yes" to Jarvis's question: risky actions allowed this turn
        self.screen_fresh = False  # a screenshot was taken and nothing has changed the screen since
        self.budget: int | None = None  # hands-on actions this request may still take (None = no limit)
        self.on_tool: Callable[[str], None] = lambda name: None  # the assistant uses this to update the tray icon
        step = config["volume"]["step"]

        # Descriptions are kept short on purpose: every word is sent with every AI request, and the
        # free tiers are counted in tokens. Behaviour rules live once in the system prompt instead.
        P = "Chrome profile folder, e.g. 'Profile 2'"
        tools = [
            Tool("open_app", "Launch a desktop app.",
                 {"name": (S, "e.g. 'notepad', 'whatsapp'", True, None)},
                 lambda name: self.apps.open(name)),
            Tool("window", "Focus/minimize/maximize/restore/close an app window, or close_all of that app's windows "
                           "('browser' = any browser).",
                 {"app": (S, "", True, None),
                  "action": (S, "", True, ["focus", "minimize", "maximize", "restore", "close", "close_all"])},
                 lambda app, action: desktop.window_action(app, action)),
            Tool("look_at_screen", "Screenshot of the whole screen. Positions are x,y from 0 to 1000.", {},
                 lambda: {"text": "Screenshot attached. Give positions as x,y from 0 to 1000 of this image.",
                          "image_jpeg": desktop.screenshot_jpeg()}),
            Tool("click", "Move the real mouse to x,y (0-1000, from a screenshot) and click.",
                 {"x": (I, "", True, None), "y": (I, "", True, None),
                  "target": (S, "what you're clicking, e.g. 'second video title', 'Send button'", True, None),
                  "button": (S, "", False, ["left", "right"]), "double": (B, "", False, None)},
                 lambda x, y, target="", button="left", double=False: mouse.click(x, y, button, bool(double))),
            Tool("click_pair", "Click one spot then a second one, both from the same screenshot, in one step: a chess "
                               "move (piece, then target square), pick-then-place, or drag=true to drag.",
                 {"x": (I, "", True, None), "y": (I, "", True, None), "x2": (I, "", True, None), "y2": (I, "", True, None),
                  "target": (S, "what you're doing, e.g. 'pawn f2 to f4'", True, None), "drag": (B, "", False, None)},
                 lambda x, y, x2, y2, target="", drag=False: mouse.click_pair(x, y, x2, y2, bool(drag))),
            Tool("scroll", "Mouse-wheel scroll at x,y (default middle of screen).",
                 {"direction": (S, "", True, ["up", "down"]), "amount": (I, "notches, default 3", False, None),
                  "x": (I, "", False, None), "y": (I, "", False, None)},
                 lambda direction, amount=3, x=500, y=500: mouse.scroll_at(x, y, direction, amount)),
            Tool("hover", "Move the mouse to x,y without clicking.",
                 {"x": (I, "", True, None), "y": (I, "", True, None)},
                 lambda x, y: mouse.hover(x, y)),
            Tool("site_search", "Search inside the site open in the front tab (its own search).",
                 {"query": (S, "", True, None)},
                 lambda query: desktop.site_search(query, SEARCH_URLS)),
            Tool("find_on_page", "Ctrl+F: jump to text on the current page.",
                 {"text": (S, "", True, None)},
                 lambda text: desktop.find_on_page(text)),
            Tool("open_chrome", "New Chrome window in a profile.",
                 {"profile": (S, P, True, None)},
                 lambda profile: self.browser.open(None, profile)),
            Tool("open_website", "Open a URL in a new Chrome window.",
                 {"url": (S, "full URL", True, None), "profile": (S, P, False, None)},
                 lambda url, profile=None: self.browser.open(url, profile)),
            Tool("web_search", "Open search results in Chrome.",
                 {"query": (S, "", True, None), "site": (S, "default google", False, list(SEARCH_URLS)),
                  "profile": (S, P, False, None)},
                 lambda query, site="google", profile=None: self.browser.search(query, site, profile)),
            Tool("browser", "Tabs, navigation and scrolling in the front browser.",
                 {"action": (S, "", True, desktop.BROWSER_ACTIONS), "times": (I, "", False, None)},
                 lambda action, times=1: desktop.browser_action(action, times)),
            Tool("close_tab_named", "Close a browser tab by its name/title, in any browser window.",
                 {"name": (S, "e.g. 'chess', 'YouTube'", True, None)},
                 lambda name: desktop.close_tab(name)),
            Tool("address_bar", "Type a URL or search words into the current tab's address bar + Enter.",
                 {"text": (S, "", True, None)},
                 lambda text: desktop.address_bar(text)),
            Tool("type_text", "Type into whatever is focused.",
                 {"text": (S, "", True, None), "press_enter": (B, "", False, None)},
                 lambda text, press_enter=False: desktop.type_text(text, press_enter)),
            Tool("press_key", "Press a key or shortcut.",
                 {"key": (S, "", True, sorted(desktop.KEYS)), "times": (I, "", False, None)},
                 lambda key, times=1: desktop.press_key(key, times)),
            Tool("media", "Media keys (YouTube, Spotify…).",
                 {"action": (S, "", True, ["play_pause", "next", "previous", "stop"])},
                 lambda action: desktop.media(action)),
            Tool("volume", f"PC volume: set to a level, up/down by {step}%, mute or unmute.",
                 {"action": (S, "", True, ["set", "up", "down", "mute", "unmute"]),
                  "level": (I, "0-100, for set", False, None)},
                 lambda action, level=None: self._volume(action, level)),
            Tool("timer", "Start a countdown timer, or cancel all timers.",
                 {"action": (S, "", True, ["start", "cancel"]), "seconds": (I, "for start", False, None)},
                 lambda action, seconds=None: self.timers.cancel_all() if action == "cancel"
                 else self.timers.start(int(seconds or 0))),
            Tool("find_files", "Find files/folders by name in the user's folders (or one folder).",
                 {"name": (S, "", True, None), "folder": (S, "e.g. 'Downloads'", False, None)},
                 lambda name, folder=None: files.find_files(name, folder)),
            Tool("list_folder", "List a folder, newest first.",
                 {"folder": (S, "e.g. 'Downloads' or a full path", True, None)},
                 lambda folder: files.list_folder(folder)),
            Tool("open_path", "Open a file in its app, or a folder in Explorer.",
                 {"path": (S, "", True, None)},
                 lambda path: files.open_path(path)),
            Tool("show_in_explorer", "Show a file selected in File Explorer.",
                 {"path": (S, "", True, None)},
                 lambda path: files.show_in_explorer(path)),
            Tool("create_folder", "Create a folder.",
                 {"path": (S, "e.g. 'Desktop/Trips'", True, None)},
                 lambda path: files.create_folder(path)),
            Tool("copy_file", "Copy a file/folder (never overwrites).",
                 {"source": (S, "", True, None), "destination": (S, "folder or new path", True, None)},
                 lambda source, destination: files.copy_path(source, destination)),
            Tool("move_file", "Move a file/folder (never overwrites).",
                 {"source": (S, "", True, None), "destination": (S, "folder or new path", True, None)},
                 lambda source, destination: files.move_path(source, destination)),
            Tool("rename_file", "Rename a file/folder.",
                 {"path": (S, "", True, None), "new_name": (S, "name only", True, None)},
                 lambda path, new_name: files.rename_path(path, new_name)),
            Tool("read_text_file", "Read a plain-text file.",
                 {"path": (S, "", True, None)},
                 lambda path: files.read_text(path)),
            Tool("write_text_file", "Create a new text file, or append to one (can't replace).",
                 {"path": (S, "e.g. 'Desktop/todo.txt'", True, None), "content": (S, "", True, None),
                  "append": (B, "", False, None)},
                 lambda path, content, append=False: files.write_text(path, content, bool(append))),
        ]
        self.tools = {t.name: t for t in tools}

    def _volume(self, action: str, level=None) -> str:
        step = self.config["volume"]["step"]
        if action == "set":
            return volume.set_volume(int(level if level is not None else 50))
        if action in ("up", "down"):
            return volume.change_volume(1 if action == "up" else -1, step)
        return volume.mute(action == "mute")

    def snapshot(self) -> bytes:
        """A screenshot taken by Jarvis itself (not asked for by the AI), sent along with a screen request
        so the AI can act straight away instead of spending a round trip on look_at_screen."""
        usage.action("look_at_screen")
        self.on_tool("look_at_screen")
        jpeg = desktop.screenshot_jpeg()
        self.screen_fresh = True
        return jpeg

    def declarations(self, names: list[str] | None = None) -> list[dict]:
        """All tools, or only the named ones (each request sends just what its kind of job needs)."""
        if names is None:
            return [t.declaration() for t in self.tools.values()]
        return [self.tools[n].declaration() for n in names if n in self.tools]

    def call(self, name: str, args: dict) -> str | dict:
        tool = self.tools.get(name)
        if not tool:
            return f"Unknown tool {name}."
        if self.cancel.is_set():
            raise mouse.Cancelled()
        args, problem = check_args(tool, args or {})
        if problem:
            log.info("Bad args for %s: %s", name, problem)
            return problem
        risk = needs_confirmation(name, args, desktop.front_window)
        if risk and not self.confirmed:
            log.info("Blocked %s(%s): %s, needs the user's yes", name, args, risk)
            return (f"Needs confirmation: this would {risk}. Nothing was done. Ask the user one short yes/no "
                    f"question, and do it only after they say yes.")
        if name in ("click", "click_pair") and not self.screen_fresh:
            # Enforced in code: a click must be aimed at what's on screen NOW. On 26 Sep a click aimed at
            # a YouTube window landed on Gmail (YouTube had opened behind it), and "1,2,4" became 3 blind clicks.
            log.info("Blocked click(%s): no fresh screenshot", args)
            return "Not clicked: look_at_screen first. The screen may have changed since the last look."
        if name in _HANDS and self.budget is not None:
            if self.budget <= 0:
                log.info("Blocked %s(%s): more actions than the user asked for", name, args)
                return ("Not done: the user didn't ask for more actions than you've already taken. Stop and "
                        "report what happened; if something is still needed, ask the user first.")
            self.budget -= 1
        log.info("Tool %s(%s)", name, args)
        self.calls_made += 1
        # The browser's scroll actions use the mouse too, so show them as mouse use.
        kind = "scroll" if name == "browser" and str((args or {}).get("action", "")).startswith("scroll") else name
        usage.action(kind)
        self.on_tool(kind)
        if name not in _READ_ONLY_TOOLS:
            self.screen_fresh = False  # anything else may change what's on screen
        try:
            result = tool.fn(**args)
            if name == "look_at_screen":
                self.screen_fresh = True
            return result
        except (mouse.UserTookOver, mouse.Cancelled):
            raise  # stop the whole request, not just this step
        except PermissionError as e:
            return f"Not allowed: {e}"
        except Exception as e:
            log.exception("Tool %s failed", name)
            return f"Error: {e}"

    def run(self, intent: Intent) -> str:
        """Offline rules path."""
        s = intent.slots
        match intent.name:
            case "open_profile":
                return self.browser.open(None, s["profile"])
            case "open_app":
                url = site_url(s["app"])
                if url:
                    return self.call("open_website", {"url": url})
                return self.call("open_app", {"name": s["app"]})
            case "set_volume":
                return self.call("volume", {"action": "set", "level": s["level"]})
            case "change_volume":
                return self.call("volume", {"action": "up" if s["direction"] > 0 else "down"})
            case "mute":
                return self.call("volume", {"action": "mute" if s["on"] else "unmute"})
            case "web_search":
                return self.call("web_search", {"query": s["query"]})
            case "set_timer":
                return self.timers.start(s["seconds"])  # may be None: asks "how long?"
            case "cancel_timer":
                return self.call("timer", {"action": "cancel"})
            case "tell_time":
                from datetime import datetime
                return datetime.now().strftime("It's %I:%M %p.").replace(" 0", " ")
        return "I don't know how to do that yet."
