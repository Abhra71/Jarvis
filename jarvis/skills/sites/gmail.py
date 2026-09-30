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
        # "Subject" is always there; "To recipients" disappears into a name chip when the address is given.
        if _named(doc, UIA, uia, "Subject"):
            return UIA, uia, doc, _named(doc, UIA, uia, "To recipients")
    return None


_SUGGESTED = re.compile(r"(?:^|\s)([\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,6})(?=\s|$)")  # "Name a@b.com" (not a run-together "Namea@b.comName")


def _recipients(doc, UIA, uia) -> list[str]:
    """Who the draft is to: address chips ("NAME (a@b.com)") and picked-contact chips (an option "NAME")."""
    found = doc.FindAll(UIA.TreeScope_Descendants, uia.CreateTrueCondition())
    subject = _named(doc, UIA, uia, "Subject")
    top = subject.CurrentBoundingRectangle.top + 5 if subject else 260  # chips sit above the subject line
    out = []
    for i in range(found.Length):
        e = found.GetElement(i)
        r = e.CurrentBoundingRectangle
        name = e.CurrentName or ""
        m = _EMAIL.search(name)
        if r.top >= top or not name:
            continue
        if m and m.group(0) not in out:
            out.append(m.group(0))
        elif e.CurrentControlType == UIA.UIA_ListItemControlTypeId and name not in out:
            out.append(name)  # a contact picked from the suggestions (30 Sep: its chip has no address)
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
        if not to_box:
            return "Not done: the new email has no To box."
        # Click into the To box like a person (30 Sep: focusing it right after the page loaded was ignored, and the
        # typed name went nowhere), then check the name really is in it.
        time.sleep(0.8)
        box = elements.Element("field", "To recipients", tuple(
            getattr(to_box.CurrentBoundingRectangle, k) for k in ("left", "top", "right", "bottom")))
        elements.click(box)
        time.sleep(0.3)
        desktop.type_text(to)
        time.sleep(0.3)
        try:
            typed = to_box.GetCurrentPattern(UIA.UIA_ValuePatternId).QueryInterface(
                UIA.IUIAutomationValuePattern).CurrentValue
        except Exception:
            typed = ""
        if to.lower() not in (typed or "").lower():
            return f"Not done: I couldn't type {to} into the To box."
        below = to_box.CurrentBoundingRectangle.bottom - 5
        want = to.lower()
        deadline = time.monotonic() + 3.0
        address = ""
        while time.monotonic() < deadline and not address:  # the contact suggestions under the To box
            time.sleep(0.3)
            options = doc.FindAll(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(
                UIA.UIA_ControlTypePropertyId, UIA.UIA_ListItemControlTypeId))
            for i in range(options.Length):
                e = options.GetElement(i)
                label = e.CurrentName or ""
                m = _SUGGESTED.search(label)
                # Only a visible suggestion, below the box, that is the person said (never a hidden list's
                # entry: 30 Sep, a contacts picker's "Baba" entry was in the page too).
                if m and not e.CurrentIsOffscreen and e.CurrentBoundingRectangle.top >= below \
                        and (want in label.lower()):
                    address = m.group(1)  # the top suggestion's address, said back before sending
                    shown = label[:m.start()].strip() or address
                    break
        if not address:
            return f"Not done: I couldn't find {to} in your contacts. Say their email address instead."
        time.sleep(0.3)  # let the top suggestion be highlighted
        keys.press("enter")  # the top suggestion
        time.sleep(0.6)
        chips = _recipients(doc, UIA, uia)
        if not chips:
            return f"Not done: {to} wasn't added to the email."
        # Say the address only if it belongs to the contact that was picked (same name on the chip).
        who = f"{chips[0]} ({address})" if chips[0].lower() in (shown.lower(), address.lower()) else chips[0]
        log.info("Gmail draft to %s, subject %r", who, subject)
        return f"Email to {who}, subject {subject!r}" + (f", saying {body!r}" if body else "") + ", is ready."
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
    if "gmail" not in desktop.front_window().lower() or not _named(doc, UIA, uia, "Subject"):
        return "Not done: there's no Gmail draft open in front."
    if not _recipients(doc, UIA, uia):
        return "Not done: the draft has no recipient."
    keys.press("ctrl+enter")
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        time.sleep(0.4)
        UIA, uia, doc = _doc()
        if not doc or not _named(doc, UIA, uia, "Subject"):
            log.info("Gmail: sent")
            return "Sent."
    return "Not done: the email still looks unsent. Please check Gmail."
