"""Site packs: common actions on the user's main sites, done in code with no AI (v3 step 5).

Each pack looks at the request and the front window and either does the job and returns the
spoken reply, or returns None so the request goes on to the offline rules and the AI.
"""

import logging
import re

from . import youtube

log = logging.getLogger(__name__)

PACKS = [("youtube", youtube.handle)]


_VERB = re.compile(r"^(play|pause|resume|stop|go|turn|skip|mute|unmute|open|close|search|find|make|set|put|"
                   r"switch|exit|leave|press|click|type|show|full ?screen|next|previous|back|forward|rewind|like|"
                   r"subscribe|then|also)\b")


def several_commands(text: str) -> bool:
    """"pause, go back 30 seconds and subtitles on" = 3 commands; "play rock and roll" = 1 (the "and" is part
    of a name)."""
    from .. import request_parts
    parts = request_parts(text)
    return len(parts) > 1 and sum(bool(_VERB.match(p)) for p in parts) >= 2


def handle(text: str, browser, unsure: bool = False) -> tuple[str, str] | None:
    """(route, reply) if a site pack handled the request, else None.
    unsure: speech recognition wasn't confident; packs then only do safe player-style commands.
    Requests with several parts ("pause, go back 30 seconds and turn on subtitles") go to the agent, which
    does every part and checks each (30 Sep: the pack did only the subtitles and said so)."""
    if several_commands(text):
        return None
    for name, pack in PACKS:
        try:
            reply = pack(text, browser, unsure)
        except Exception:
            log.exception("The %s pack failed; the AI will take it", name)
            return None
        if reply:
            log.info("Handled by the %s pack", name)
            return f"site:{name}", reply
    return None
