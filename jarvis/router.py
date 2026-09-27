"""Decides what kind of job a request is, so each AI request carries only what that job needs.

Pure word rules: instant, free, and easy to adjust. The kind picks:
- which tools are sent (every tool's description is paid for in tokens on every request),
- which parts of the system prompt are sent,
- which AI goes first (brain.py): Gemini for anything that needs the screen, Groq for the rest.

If a request turns out to need a tool it wasn't given, the AI calls `more_tools` and gets it
on the next round, so a wrong guess costs one round trip, not a failure.
"""

import re

KINDS = ("chat", "live", "action", "screen", "files")

# Needs to see the screen or use the mouse.
_SCREEN = re.compile(
    r"\b(screen|click|tap|double click|right click|button|video|videos|play the|shortcut|this page|on the page|"
    r"look at|what do you see|select|choose|field|box|icon|link|thumbnail|scroll|drag|hover|pop ?up|"
    r"what'?s (on|showing|playing)|read (it|this|what)|pawn|knight|bishop|rook|queen|king|castle|takes|"
    r"resign|rematch|new game|hint|undo|fill|tick|check the)\b|\b[a-h] ?[1-8]\b")
# Files and folders on the PC.
_FILES = re.compile(r"\b(file|files|folder|folders|downloads|documents|desktop|pictures|photos|resume|pdf|"
                    r"docx?|txt|rename|copy|explorer)\b")
# Facts that change over time: need a web search (and reading the results on screen).
_LIVE = re.compile(r"\b(latest|today|tonight|yesterday|tomorrow|current|currently|right now|news|score|scores|"
                   r"price|prices|weather|stock|this (week|month|year)|recent|recently|last (film|movie|match|game|"
                   r"episode|album|song)|upcoming|release date|who won)\b")
_QUESTION = re.compile(r"\?\s*$|^\s*(what|who|when|where|which|why|how|is|are|was|were|did|does|do|can|could|"
                       r"tell me|explain|recommend|define)\b")
# Doing something on the PC.
_ACTION = re.compile(r"\b(open|close|launch|start|switch|go|search|mute|unmute|volume|set|minimi[sz]e|maximi[sz]e|"
                     r"restore|create|make|cut|paste|find|pause|play|resume|stop|next|previous|skip|timer|tab|"
                     r"reload|refresh|back|forward|show|put on|listen|watch|quit|exit)\b")
_FILLER = re.compile(r"^(hey |ok |okay )?(jarvis[, ]*)?(please |can you |could you |would you )*")


def classify(text: str) -> str:
    """'chat' | 'live' | 'action' | 'screen' | 'files'."""
    t = _FILLER.sub("", (text or "").lower().strip())
    if _SCREEN.search(t):
        return "screen"
    if _FILES.search(t):
        return "files"
    if _QUESTION.search(t) and not _ACTION.search(t):
        return "live" if _LIVE.search(t) else "chat"
    return "action"


# Tool groups. `more_tools` can add any group mid-request.
GROUPS = {
    "apps": ["do", "open_app", "window", "open_website", "open_chrome", "web_search", "browser", "close_tab_named",
             "address_bar", "site_search"],
    "system": ["volume", "media", "timer"],
    "keys": ["type_text", "press_key"],
    "screen": ["page_elements", "click_element", "look_at_screen", "click", "click_pair", "scroll", "hover",
               "find_on_page"],
    "files": ["find_files", "list_folder", "open_path", "show_in_explorer", "create_folder", "copy_file",
              "move_file", "rename_file", "read_text_file", "write_text_file"],
}
_KIND_GROUPS = {
    "chat": [],
    "live": [],
    "action": ["apps", "keys"],  # shortcuts are the fastest way to do most things
    "screen": ["apps", "keys", "screen"],
    "files": ["files", "apps"],
}
_KIND_EXTRA = {  # single tools some kinds need without their whole group
    "live": ["web_search", "look_at_screen", "scroll", "find_on_page"],
    "chat": ["web_search"],
}
# Groups added when the words call for them, whatever the kind.
_WANTS = {
    "system": re.compile(r"\b(volume|sound|mute|unmute|louder|quieter|softer|timer|remind|alarm|countdown|music|"
                         r"song|pause|resume|next|previous|skip|stop|media)\b"),
    "keys": re.compile(r"\b(type|write|enter|press|key|keyboard|select all|copy|paste|undo|save|escape|esc)\b"),
}


def tool_names(kind: str, extra_groups: set[str] = frozenset(), request: str = "") -> list[str]:
    """The tools to send for this kind of request, in a stable order."""
    t = (request or "").lower()
    groups = [*_KIND_GROUPS.get(kind, list(GROUPS)), *sorted(extra_groups)]
    if kind != "chat":
        groups += [g for g, rx in _WANTS.items() if rx.search(t)]
    names: list[str] = []
    for g in dict.fromkeys(groups):
        names += GROUPS[g]
    names += _KIND_EXTRA.get(kind, [])
    return list(dict.fromkeys(names))


def missing_groups(kind: str, extra_groups: set[str] = frozenset(), request: str = "") -> list[str]:
    """Groups the AI can still ask for with more_tools."""
    have = set(tool_names(kind, extra_groups, request))
    return [g for g, tools in GROUPS.items() if not set(tools) <= have]


# Words that mean the Chrome profile list is relevant.
_PROFILES = re.compile(r"\b(profile|profiles|account|accounts|chrome|main|personal|backup|work|ai|first|second|"
                       r"third|fourth|fifth|1st|2nd|3rd|4th|5th)\b")


# Screen requests about things that have no name to click by: board squares, pictures, what it looks like.
# These need a screenshot (Gemini); the rest can use the list of named items as text (Groq).
_EYES = re.compile(r"\b(pawn|knight|bishop|rook|queen|king|castle|takes|board|see|look|looks|describe|picture|"
                   r"image|photo|thumbnail|colou?r|what'?s on (the |my )?screen|what'?s showing)\b|\b[a-h] ?[1-8]\b")


_VERB = re.compile(r"^(open|go to|click( on)?|tap( on)?|select|choose|show( me)?|take me to|play|press|start|"
                   r"switch to)\s+(the |my |a |an )?")


def thing_named(text: str) -> str:
    """"open chemistry" -> "chemistry": the thing a command is about, to look for on screen."""
    t = _FILLER.sub("", (text or "").lower().strip()).strip(" .!?")
    m = _VERB.match(t)
    return t[m.end():].strip() if m else ""


def needs_eyes(text: str) -> bool:
    return bool(_EYES.search(_FILLER.sub("", (text or "").lower().strip())))


def wants_profiles(text: str) -> bool:
    return bool(_PROFILES.search((text or "").lower()))
