"""Site packs: common actions on the user's main sites, done in code with no AI (v3 step 5).

Each pack looks at the request and the front window and either does the job and returns the
spoken reply, or returns None so the request goes on to the offline rules and the AI.
"""

import logging

from . import youtube

log = logging.getLogger(__name__)

PACKS = [("youtube", youtube.handle)]


def handle(text: str, browser, unsure: bool = False) -> tuple[str, str] | None:
    """(route, reply) if a site pack handled the request, else None.
    unsure: speech recognition wasn't confident; packs then only do safe player-style commands."""
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
