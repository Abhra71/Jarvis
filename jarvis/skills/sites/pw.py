"""Physics Wallah (pw.live): the user's batch and its subjects, in code, no AI (~3–5 s).

Mapped on 30 Sep, live:
    pw.live/study-v2/study        "YOUR BATCH  VICTORY 2027 (Class 10th ICSE)", cards: All Classes, All Tests…
    → All Classes                 …/batch-overview?…pageName=ALL_CLASSES: the subjects, e.g. "Chemistry by
                                  Sunil Sir" (24 %) and "Chemistry by Sanya…" (0 %): the same subject twice
    → a subject                   …/subjects/chemistry-by-sunil-sir-…/subject-topics: its chapters

PW's cards have no accessible names, so they're found by reading the screen (Windows' offline OCR) and
clicked at the words, like a person. When a subject is there twice, the one being studied (the most
progress) is opened, and the reply says which, so "chemistry by Sanya" opens the other.

Pop-ups: notices (the streak screen) are closed on the way; a form (the Student Feedback Form) is never
touched here: the agent asks the user first.
"""

import logging
import re
import time

from .. import desktop, elements, popups
from .. import mouse as jmouse

log = logging.getLogger(__name__)

STUDY = "https://pw.live/study-v2/study"
SUBJECTS = ("physics", "chemistry", "maths", "biology", "history", "civics", "geography", "economics",
            "english", "hindi", "computer")
_ALIASES = {"math": "maths", "mathematics": "maths", "bio": "biology", "geo": "geography", "eco": "economics",
            "computers": "computer", "computer science": "computer", "chem": "chemistry"}
_PERCENT = re.compile(r"^(\d{1,3})\s?%$")
# The user's usual teacher per subject when a subject is there twice (30 Sep: "normally I study chemistry from the
# same teacher", Sunil Sir; he's also the one with progress in the batch). "chemistry by sanya" still opens hers.
TEACHERS = {"chemistry": "sunil"}


def subject_in(text: str) -> str | None:
    """'my batch, chemistry' -> 'chemistry'; 'chemistry by sanya' -> 'chemistry by sanya'."""
    t = " ".join(re.sub(r"physics wallah", " ", text.lower()).split())  # the site's name isn't the subject
    for word in sorted([*SUBJECTS, *_ALIASES], key=len, reverse=True):
        m = re.search(rf"\b{word}\b(?: by (?!(?:on|in|from|at|of|pw)\b)[a-z]+(?: (?!(?:on|in|from|at|of|pw)\b)[a-z]+)?)?", t)
        if m:
            said = m.group(0)
            return said.replace(word, _ALIASES.get(word, word), 1).strip()
    return None


# ---- the page --------------------------------------------------------------------

def _on_pw() -> bool:
    return (desktop.current_url() or "").startswith("https://pw.live") if elements.front_is_browser() else False


def _ocr_lines():
    from ...agent import ocr
    return ocr.read_front_lines()


def _wait(pred, timeout: float, step: float = 0.3) -> bool:
    """Until pred() or the timeout. A pop-up form appearing ends the wait early (it hides the page; 30 Sep:
    Khazana waited 20 s for text under the feedback form): the caller then finds the form and asks the user."""
    deadline = time.monotonic() + timeout
    checks = 0
    while True:
        if pred():
            return True
        checks += 1
        if checks % 3 == 0:  # every ~1 s: the pop-up check costs ~0.05 s
            p = popups.find()
            if p and popups.is_notice(p.title):
                # 3 Oct: the streak screen covered the page for the whole wait. A notice is closed at once.
                log.info("PW: %s", popups.close())
            elif p:
                return False  # a form: the caller asks the user
        if time.monotonic() >= deadline:
            return False
        time.sleep(step)


def _clear_notices():
    """Close a notice (the streak screen) in the way. A form is left for the user to decide."""
    p = popups.find()
    if p and popups.is_notice(p.title):
        log.info("PW: %s", popups.close())


def _form_in_way() -> str:
    p = popups.find()
    return p.title if p and not popups.is_notice(p.title) else ""


def _forms_first(fn):
    """A pop-up form can appear a moment after a PW page loads, over what was about to be clicked (30 Sep). When a
    step fails and a form is the reason, say so: the agent then asks the user "close it, or fill it in?"."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        if isinstance(result, str) and result.startswith("Not done") and "is over the page" not in result:
            form = _form_in_way()
            if form:
                return f"Not done: the {form} is over the page. Shall I close it, or do you want to fill it in?"
        return result
    return wrapper


def _click_at(rect):
    l, t, r, b = rect
    sw, sh = jmouse.screen_size()
    jmouse.click((l + r) / 2 / (sw - 1) * 1000, (t + b) / 2 / (sh - 1) * 1000, "left", False)


def _find_line(want: str, lines) -> tuple | None:
    from ...agent import ocr
    top = elements.page_top()
    return ocr.find(want, [ln for ln in lines if ln.rect[1] >= top])


def _find_steady(want: str, timeout: float = 4.0) -> tuple | None:
    """The words on screen once they've stopped moving: PW's pages shift while banners load (30 Sep: "Khazana"
    moved 80 px between two reads and the click missed)."""
    deadline = time.monotonic() + timeout
    last = None
    while True:
        hit = _find_line(want, _ocr_lines())
        if hit and last and max(abs(a - b) for a, b in zip(hit[1], last[1])) <= 4:
            return hit
        if time.monotonic() >= deadline:
            return hit
        last = hit
        time.sleep(0.3)


@_forms_first
def open_study() -> str:
    """Your batch's page, in the PW tab if there is one (it's logged in there), else in the browser in front."""
    if not _on_pw():
        w = desktop.find_window("physics wallah")
        if w and w[1] in desktop.BROWSERS:
            desktop._focus(w[0])
        elif not desktop._front_browser():
            # No browser page open (3 Oct: only Chrome's profile picker was): PW is logged in on the main profile.
            from ...config import load_config
            from ..browser import Browser
            Browser(load_config().get("chrome_profiles", {})).open(STUDY, "main")
            if not _wait(lambda: (desktop.current_url() or "").startswith("https://pw.live"), 8):
                return "Not done: PW didn't open in Chrome."
    desktop.address_bar(STUDY)
    ok = _wait(lambda: (desktop.current_url() or "").startswith(STUDY) and _has_text("your batch"), 10)
    if not ok:
        return "Not done: PW's study page didn't open."
    _clear_notices()
    name = _batch_name()
    return f"Opened your PW batch{', ' + name if name else ''}."


def _has_text(words: str) -> bool:
    try:
        return any(words in ln.text.lower() for ln in _ocr_lines())
    except Exception:
        return False


def _batch_name() -> str:
    """'VICTORY 2027 (Class 10th ICSE)': the heading on the study page (the screen shows it cut short)."""
    try:
        UIA, uia = desktop._uia()
        import win32gui
        root = uia.ElementFromHandle(win32gui.GetForegroundWindow())
        heads = root.FindAll(UIA.TreeScope_Descendants,
                             uia.CreatePropertyCondition(UIA.UIA_LocalizedControlTypePropertyId, "heading"))
        for i in range(heads.Length):
            name = " ".join((heads.GetElement(i).CurrentName or "").split())
            if re.search(r"\(class ", name, re.I):
                return name
    except Exception:
        log.debug("PW: couldn't read the batch name", exc_info=True)
    return ""


def _all_classes() -> str | None:
    """On the subjects list (All Classes), or why not."""
    if "pageName=ALL_CLASSES" in (desktop.current_url() or "") and "/subjects/" not in (desktop.current_url() or ""):
        return None
    if not (desktop.current_url() or "").startswith(STUDY):
        r = open_study()
        if r.startswith("Not done"):
            return r
    _clear_notices()
    form = _form_in_way()
    if form:
        return f"Not done: the {form} is over the page. Shall I close it, or do you want to fill it in?"
    hit = _find_steady("All Classes")
    if not hit:
        return "Not done: I couldn't find All Classes on your batch page."
    _click_at(hit[1])
    if not _wait(lambda: "pageName=ALL_CLASSES" in (desktop.current_url() or ""), 6):
        return "Not done: All Classes didn't open."
    _wait(lambda: _has_text(" by "), 4)  # the subject cards ("Chemistry by Sunil Sir") drawn
    return None


def _subject_cards(lines) -> list[tuple[str, tuple, int]]:
    """(name, rect, progress %) for each subject card on the All Classes page."""
    top = elements.page_top()
    names = [ln for ln in lines if ln.rect[1] >= top and re.search(r"\bby\b|^[A-Z][a-z]+$", ln.text)]
    percents = [(int(m.group(1)), ln.rect) for ln in lines if (m := _PERCENT.match(ln.text.strip()))]
    cards = []
    for ln in names:
        l, t, r, b = ln.rect
        # The progress sits on the same row, just right of the name, before the next card's column.
        pct = [p for p, (pl, pt, pr, pb) in percents if abs((pt + pb) / 2 - (t + b) / 2) < 20 and l < pl < l + 360]
        cards.append((ln.text.rstrip(". …"), ln.rect, max(pct) if pct else 0))
    return cards


@_forms_first
def open_subject(subject: str) -> str:
    subject = " ".join(subject.lower().split())
    why = _all_classes()
    if why:
        return why
    lines = _ocr_lines()
    base = subject.split(" by ")[0]
    cards = [c for c in _subject_cards(lines) if c[0].lower().startswith(base)]
    if " by " in subject:  # "chemistry by sanya": that teacher's
        teacher = subject.split(" by ", 1)[1]
        cards = [c for c in cards if teacher in c[0].lower()] or cards
    if not cards:
        return f"Not done: there's no {base.capitalize()} in your batch's subjects."
    cards.sort(key=lambda c: -c[2])  # the one being studied (its progress %)
    usual = TEACHERS.get(base)
    if " by " not in subject and usual:  # the user's usual teacher first (30 Sep: a narrow window hid the %)
        cards.sort(key=lambda c: usual not in c[0].lower())
    name, rect, pct = cards[0]
    before = desktop.current_url()
    _click_at(rect)
    if not _wait(lambda: "/subjects/" in (desktop.current_url() or "") and desktop.current_url() != before, 6):
        return f"Not done: {name} didn't open."
    others = [c[0] for c in cards[1:]]
    note = f" There's also {others[0]}." if others else ""
    return f"Opened {name}.{note}"


# ---- Khazana (the batch's old recorded classes) ------------------------------------------
#
# Mapped on 30 Sep: study page → the "Khazana" card → …/khazana/<id>?pageName=Khazana, with
# "Continue Learning" course cards ("Chemistry 2026", "Mathematics 2026"…, each with "View Course") and
# "All Courses" by year (2024, 2025…). Its search is an address: …/khazana/<id>/khazana-search?query=…
# The user studies Chemistry there from Sunil Sir (Khazana's "Chemistry 2026"); an old log had
# "Khazana 2026" open 2024, so a year that's said is matched exactly.

def _places_file():
    from ...config import ROOT
    return ROOT / "data" / "pw.json"


def _places() -> dict:
    import json
    try:
        return json.loads(_places_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember_place(name: str, url: str):
    import json
    places = {**_places(), name: url}
    try:
        _places_file().write_text(json.dumps(places, indent=1), encoding="utf-8")
    except OSError:
        log.debug("PW: couldn't save %s", name, exc_info=True)


def _khazana_home() -> str | None:
    """On Khazana's main page, or why not. The first time it's found through the study page; its address is
    then remembered, so next time it opens straight away."""
    url = _places().get("khazana")
    if url:
        if not _on_pw():
            w = desktop.find_window("physics wallah")
            if w and w[1] in desktop.BROWSERS:
                desktop._focus(w[0])
        desktop.address_bar(url)
        # Its title is always in view; "Continue Learning" may be below the fold in a half-width window (30 Sep).
        if _wait(lambda: "pageName=Khazana" in (desktop.current_url() or "") and _has_text("khazana"), 8):
            _clear_notices()
            return None
        form = _form_in_way()
        if form:  # the page is there, under a form: the user decides (don't go the long way round)
            return f"Not done: the {form} is over the page. Shall I close it, or do you want to fill it in?"
        if "pageName=Khazana" in (desktop.current_url() or ""):
            _clear_notices()
            return None  # Khazana is open; its text was just slow to read
    r = open_study()
    if r.startswith("Not done"):
        return r
    form = _form_in_way()
    if form:
        return f"Not done: the {form} is over the page. Shall I close it, or do you want to fill it in?"
    hit = _find_steady("Khazana")
    if not hit:
        return "Not done: I couldn't find Khazana on your batch page."
    _click_at(hit[1])
    if not _wait(lambda: "/khazana/" in (desktop.current_url() or ""), 8):
        return "Not done: Khazana didn't open."
    _remember_place("khazana", desktop.current_url())
    _wait(lambda: _has_text("khazana"), 5)
    _clear_notices()
    return None


def _label_matches(label: str, subject: str, year: str) -> bool:
    words = label.lower().split()
    return bool(words) and words[0][:4] == subject[:4] and (not year or year in label)


@_forms_first
def open_khazana(request: str = "") -> str:
    """'khazana' / 'khazana chemistry' / 'khazana chemistry 2026' / 'khazana sunil sir organic chemistry'."""
    why = _khazana_home()
    if why:
        return why
    said = " ".join(request.lower().split())
    subject = subject_in(said)
    year = (re.search(r"\b20[2-3]\d\b", said) or [""])[0]
    if not subject:
        return "Opened Khazana."
    base = subject.split(" by ")[0]
    top = elements.page_top()
    # "Continue Learning": the course being studied, with its "View Course" on the same row.
    teacher_named = re.search(r"\b(sir|ma'?am|by)\b", said)
    for attempt in range(0 if teacher_named else 2):  # its teacher isn't shown there: a named one goes to search
        lines = _ocr_lines()
        for ln in lines:
            if ln.rect[1] >= top and _label_matches(ln.text, base, year):
                views = [v for v in lines if "view course" in v.text.lower() and abs(v.rect[1] - ln.rect[1]) < 20
                         and ln.rect[0] < v.rect[0] < ln.rect[0] + 700]
                if views:
                    _click_at(views[0].rect)
                    if _wait(lambda: "khazana-topics" in (desktop.current_url() or ""), 6):
                        return f"Opened Khazana {ln.text.strip()}."
        if attempt == 0:  # below the fold in a narrow window: scroll down once and look again
            desktop.browser_action("scroll_down")
            time.sleep(0.8)
    # Not a course being continued: Khazana's own search, straight by its address.
    home = desktop.current_url() or _places().get("khazana", "")
    root = home.split("?")[0].split("/khazana-")[0]
    from urllib.parse import quote_plus
    query = " ".join(x for x in (said_wanted(said), year) if x).strip() or base
    desktop.address_bar(f"{root}/khazana-search?query={quote_plus(query)}")
    if not _wait(lambda: "khazana-search" in (desktop.current_url() or ""), 6):
        return f"Not done: Khazana's search for {query} didn't open."
    return f"Here's Khazana's search for {query}."


_FILLER = re.compile(r"\b(open|go to|show|me|my|the|in|on|from|of|pw|physics wallah|khazana|please|and|batch|"
                     r"course|classes|lectures?|videos?|20[2-3]\d)\b")


def said_wanted(said: str) -> str:
    """'open khazana sunil sir organic chemistry 2026' -> 'sunil sir organic chemistry'."""
    return " ".join(_FILLER.sub(" ", said).split())
