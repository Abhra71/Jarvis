"""Gmail in the main Chrome profile: write an email in code, and send it only after the user's spoken yes.

Mapped live on 30 Sep: a full-page draft opens straight from an address
    https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1&su=<subject>&body=<body>
with named boxes "To recipients" (a combo box that suggests contacts as you type), "Subject", "Message Body",
and a "Send (Ctrl-Enter)" button. Sending is never done here: the agent's next step presses Ctrl+Enter, which
the safety rules hold back until the user says yes ("Your message is ready. Shall I send it?").
"""

import logging
import re
import time
from urllib.parse import quote

from .. import desktop, elements, keys

log = logging.getLogger(__name__)

COMPOSE = "https://mail.google.com/mail/u/0/?view=cm&fs=1&tf=1"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# "email mom about dinner saying I'll be late" / "send an email to rahul saying hi" / "mail sir subject leave"
_ASK = re.compile(r"(?:send |write |compose )?(?:an? )?(?:e ?mail|mail)(?: to)? (?P<to>.+?)"
                  r"(?: (?:about|regarding|with (?:the )?subject|subject) (?P<subject>.+?))?"
                  r"(?: (?:saying|that says|and say|to say|body|message)[:,]? (?P<body>.+))?$", re.I)
_SPOKEN_ADDRESS = re.compile(r"^([\w.+-]+) at ([\w-]+(?: dot [\w-]+)+)$", re.I)


def parse(said: str) -> tuple[str, str, str] | None:
    """'email mom about dinner saying i'll be late' -> ('mom', 'dinner', "i'll be late")."""
    m = _ASK.fullmatch(" ".join(said.strip().rstrip(".!").split()))  # the user's own words, with punctuation
    if not m:
        return None
    to, subject, body = (m.group("to") or "").strip(" ,:"), (m.group("subject") or "").strip(" ,:"),         (m.group("body") or "").strip()
    spoken = _SPOKEN_ADDRESS.match(to)
    if spoken:  # "abhra at gmail dot com"
        to = f"{spoken.group(1)}@{spoken.group(2).replace(' dot ', '.')}"
    if not subject and body:
        subject = " ".join(body.split()[:6])  # Gmail asks "send without a subject?" otherwise
    if body:
        body = body[0].upper() + body[1:]
        if body[-1] not in ".!?":
            body += "."
    return to, subject[:1].upper() + subject[1:], body


def _doc(hwnd=None):
    import win32gui
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd or win32gui.GetForegroundWindow())
    return UIA, uia, root.FindFirst(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
        UIA.UIA_ControlTypePropertyId, UIA.UIA_DocumentControlTypeId))


def _named(doc, UIA, uia, name: str):
    return doc.FindFirst(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(UIA.UIA_NamePropertyId, name)) \
        if doc else None


def _wait_for_draft(timeout: float = 12.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.4)
        if "gmail" not in desktop.front_window().lower():
            continue
        UIA, uia, doc = _doc()
        to = _named(doc, UIA, uia, "To recipients")
        if to:
            return UIA, uia, doc, to
    return None


def _recipients(doc, UIA, uia) -> list[str]:
    """Email addresses shown as chips in the To box."""
    found = doc.FindAll(UIA.TreeScope_Descendants, uia.CreateTrueCondition())
    to = _named(doc, UIA, uia, "To recipients")
    top = to.CurrentBoundingRectangle.bottom + 5 if to else 260
    out = []
    for i in range(found.Length):
        e = found.GetElement(i)
        r = e.CurrentBoundingRectangle
        m = _EMAIL.search(e.CurrentName or "")
        if m and r.top < top and m.group(0) not in out:
            out.append(m.group(0))
    return out


def draft(to: str, subject: str, body: str, browser) -> str:
    """Open a draft to `to` (a name from the contacts, or an address). Never sends."""
    url = f"{COMPOSE}&su={quote(subject)}&body={quote(body)}"
    if _EMAIL.fullmatch(to):
        url += f"&to={quote(to)}"
    if elements.front_is_browser() and "mail.google.com" in (desktop.current_url() or ""):
        desktop.address_bar(url)
    else:
        browser.open(url, "main")  # Gmail is signed in on the main profile
    ready = _wait_for_draft()
    if not ready:
        return "Not done: Gmail's new email didn't open."
    UIA, uia, doc, to_box = ready
    if not _EMAIL.fullmatch(to):
        to_box.SetFocus()
        time.sleep(0.2)
        desktop.type_text(to)
        deadline = time.monotonic() + 3.0
        options = None
        while time.monotonic() < deadline:  # the contact suggestions
            time.sleep(0.3)
            options = doc.FindAll(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
                UIA.UIA_ControlTypePropertyId, UIA.UIA_ListItemControlTypeId))
            if options.Length and any(_EMAIL.search(options.GetElement(i).CurrentName or "")
                                      for i in range(options.Length)):
                break
        else:
            return f"Not done: I couldn't find {to} in your contacts. Say their email address instead."
        keys.press("enter")  # the top suggestion
        time.sleep(0.6)
    who = _recipients(doc, UIA, uia)
    if not who:
        return f"Not done: the email has no recipient; {to} wasn't accepted."
    log.info("Gmail draft to %s, subject %r", who, subject)
    return (f"Email to {to} ({', '.join(who)}), subject {subject!r}" +
            (f", saying {body!r}" if body else "") + ", is ready.")


def send() -> str:
    """Send the open draft (Ctrl+Enter), then check it went: the draft's boxes are gone. The safety rules only
    let this run after the user's yes."""
    UIA, uia, doc = _doc()
    if "gmail" not in desktop.front_window().lower() or not _named(doc, UIA, uia, "To recipients"):
        return "Not done: there's no Gmail draft open in front."
    if not _recipients(doc, UIA, uia):
        return "Not done: the draft has no recipient."
    keys.press("ctrl+enter")
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        time.sleep(0.4)
        UIA, uia, doc = _doc()
        if not _named(doc, UIA, uia, "To recipients"):
            log.info("Gmail: sent")
            return "Sent."
    return "Not done: the email still looks unsent. Please check Gmail."
