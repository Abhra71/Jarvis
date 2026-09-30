"""Windows switches and brightness by voice, done in code and checked (jarvis/skills/quick.py).

"turn on night light", "bluetooth off", "disable wi-fi", "brightness 40", "brightness up", "dim the screen"."""

import re

from . import ability
from ..skills import quick

_STEP = 10  # "brightness up/down"


def _parse_switch(said: str) -> tuple[str | None, bool | None]:
    s = " ".join(said.lower().replace("-", " ").split())
    on = None
    m = re.fullmatch(r"(?:turn|switch|put) (on|off) (?:the |my )?(.+)|(?:turn|switch|put) (?:the |my )?(.+?) (on|off)|"
                     r"(enable|disable) (?:the |my )?(.+)|(.+?) (on|off)", s)
    if not m:
        return None, None
    g = m.groups()
    if g[0]:
        on, name = g[0] == "on", g[1]
    elif g[2]:
        on, name = g[3] == "on", g[2]
    elif g[4]:
        on, name = g[4] == "enable", g[5]
    else:
        on, name = g[7] == "on", g[6]
    return quick.switch_name(name), on


@ability("switch_setting", "turn a Windows switch on/off (night light, bluetooth, wifi…)",
         r"(?P<value>(?:turn|switch|put) (?:on|off) (?:the |my )?(?:wi ?fi|wi-fi|internet|blue ?tooth|night ?light|"
         r"night mode|blue light filter|airplane mode|aeroplane mode|flight mode|energy saver|battery saver|power saver|"
         r"live captions|captions|mobile hotspot|hotspot))",
         r"(?P<value>(?:turn|switch|put) (?:the |my )?(?:wi ?fi|wi-fi|internet|blue ?tooth|night ?light|night mode|"
         r"blue light filter|airplane mode|aeroplane mode|flight mode|energy saver|battery saver|power saver|"
         r"live captions|captions|mobile hotspot|hotspot) (?:on|off))",
         r"(?P<value>(?:enable|disable) (?:the |my )?(?:wi ?fi|wi-fi|blue ?tooth|night ?light|night mode|airplane mode|"
         r"aeroplane mode|flight mode|energy saver|battery saver|power saver|live captions|captions|mobile hotspot|hotspot))",
         r"(?P<value>(?:wi ?fi|wi-fi|blue ?tooth|night ?light|night mode|airplane mode|aeroplane mode|flight mode|"
         r"energy saver|battery saver|live captions|mobile hotspot|hotspot) (?:on|off))",
         value="e.g. night light on")
def switch_setting(said: str):
    name, on = _parse_switch(said)
    if not name:
        raise ValueError(f"no Windows switch in {said!r}")
    reply = quick.set_switch(name, on)
    if name in ("wifi", "airplane mode") and not reply.startswith("Not done") and (on is (name == "airplane mode")):
        reply += " Without internet I'll only understand simple commands until it's back."
    return reply


@ability("set_brightness", "screen brightness",
         r"(?:set |change |put )?(?:the |my )?(?:screen )?brightness (?:to |at )?(?P<value>\d{1,3})(?: ?%| percent)?",
         r"(?:set |make )?(?:the |my )?(?:screen )?brightness (?P<value>up|down|higher|lower|max|maximum|full|min|minimum)",
         r"(?P<value>increase|raise|decrease|lower|reduce|max|maximum|full|min|minimum) (?:the |my )?(?:screen )?brightness",
         r"(?P<value>dim|darken|brighten) (?:the |my )?screen",
         r"(?:make )?(?:the |my )?screen (?P<value>brighter|darker|dimmer)",
         value="0-100/up/down")
def set_brightness(value: str):
    v = value.strip().lower()
    if v.isdigit():
        return quick.set_brightness(int(v))
    now = quick.brightness()
    if now is None:
        return "Not done: I can't read this screen's brightness."
    if v in ("max", "maximum", "full"):
        return quick.set_brightness(100)
    if v in ("min", "minimum"):
        return quick.set_brightness(5)  # never 0: a black screen looks like a crash
    up = v in ("up", "higher", "increase", "raise", "brighten", "brighter")
    return quick.set_brightness(max(5, now + (_STEP if up else -_STEP)))


@ability("connect_bluetooth", "connect a Bluetooth device",
         r"(?:connect|pair)(?!.*\b(?:wi ?fi|wi-fi|internet|network|vpn|hotspot)\b)(?: to)? (?:my |the )?(?P<value>.+?)"
         r"(?: headphones| earphones| earbuds| speaker)?"
         r"(?: (?:with|via|over|on) bluetooth)?",
         value="device")
def connect_bluetooth(said: str):
    return quick.connect_device(said, True)


@ability("disconnect_bluetooth", "disconnect a Bluetooth device",
         r"(?:disconnect|unpair)(?: from)? (?:my |the )?(?P<value>.+?)(?: headphones| earphones| earbuds| speaker)?",
         value="device")
def disconnect_bluetooth(said: str):
    return quick.connect_device(said, False)
