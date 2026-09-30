"""Gmail by voice: write the email in code; sending always waits for the user's yes (jarvis/skills/sites/gmail.py)."""

from . import ability
from ..skills.sites import gmail

_browser = None


def _get_browser():
    global _browser
    if _browser is None:
        from ..config import load_config
        from ..skills.browser import Browser
        _browser = Browser(load_config().get("chrome_profiles", {}))
    return _browser


@ability("gmail_draft", "write a Gmail email (not sent)", value="to, subject, body as said", safe=False)
def gmail_draft(said: str):
    parsed = gmail.parse(said)
    if not parsed:
        raise ValueError(f"no email in {said!r}")
    to, subject, body = parsed
    return gmail.draft(to, subject, body, _get_browser())


@ability("gmail_send", "send the open Gmail draft (only after the user's yes)", safe=False)
def gmail_send():
    return gmail.send()
