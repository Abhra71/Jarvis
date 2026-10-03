"""Files by kind and age: "find the newest PDF in Downloads", "open my last screenshot". Instant and exact:
the folder is read in code (no AI), and the file is shown selected in File Explorer, like a person would."""

import re
import time

from . import ability
from ..skills import desktop, files

KINDS = {
    "pdf": (".pdf",), "document": (".pdf", ".docx", ".doc", ".txt", ".odt", ".pptx", ".xlsx"),
    "word": (".docx", ".doc"), "doc": (".docx", ".doc"), "excel": (".xlsx", ".xls", ".csv"),
    "spreadsheet": (".xlsx", ".xls", ".csv"), "sheet": (".xlsx", ".xls", ".csv"),
    "powerpoint": (".pptx", ".ppt"), "presentation": (".pptx", ".ppt"), "ppt": (".pptx", ".ppt"),
    "image": (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"), "photo": (".jpg", ".jpeg", ".png", ".heic", ".webp"),
    "picture": (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"), "screenshot": (".png", ".jpg"),
    "video": (".mp4", ".mkv", ".mov", ".avi", ".webm"), "song": (".mp3", ".m4a", ".wav", ".flac"),
    "music": (".mp3", ".m4a", ".wav", ".flac"), "audio": (".mp3", ".m4a", ".wav", ".flac", ".ogg"),
    "zip": (".zip", ".rar", ".7z"), "installer": (".exe", ".msi"), "setup": (".exe", ".msi"),
    "text": (".txt", ".md"), "file": (), "download": (),
}
_FOLDERS = ("downloads", "documents", "desktop", "pictures", "music", "videos")
_KIND_WORDS = "|".join(sorted(KINDS, key=len, reverse=True))


def _screenshots() -> str:
    """Where screenshots are: Pictures may be in OneDrive, and the folder may be "Screenshots 1" (both on this
    PC, 1 Oct). The newest folder called Screenshots…, else Pictures."""
    try:
        pics = files.resolve("pictures")
        dirs = [d for d in pics.iterdir() if d.is_dir() and d.name.lower().startswith("screenshot")]
    except Exception:
        return "pictures"
    if not dirs:
        return "pictures"
    return "pictures/" + max(dirs, key=lambda d: d.stat().st_mtime).name


def _parse(said: str) -> tuple[str, tuple[str, ...], str]:
    """'open my downloads and find the newest pdf' -> ('Downloads', ('.pdf',), 'PDF')."""
    folder = next((f for f in _FOLDERS if f in said), "")
    after = re.split(_NEWEST, said, maxsplit=1)[-1]  # the kind is named after "newest" ("open downloads and…")
    kind = re.search(rf"\b({_KIND_WORDS})s?\b", after)
    word = kind.group(1) if kind else "file"
    if not folder:
        folder = "pictures" if word in ("screenshot",) else "downloads"
    if word == "screenshot":
        folder = _screenshots()
    label = {"pdf": "PDF", "file": "file", "download": "download"}.get(word, word)
    return folder if "/" in folder else folder.title(), KINDS.get(word, ()), label


def newest(folder: str, exts: tuple[str, ...]):
    p = files.resolve(folder)
    best, best_time = None, 0.0
    for f in p.iterdir():
        try:
            if not f.is_file() or f.name.startswith(("~$", ".")) or files.is_secret(f.name):
                continue
            if f.suffix.lower() in (".crdownload", ".part", ".tmp"):
                continue  # still downloading
            if exts and f.suffix.lower() not in exts:
                continue
            t = f.stat().st_mtime
        except OSError:
            continue
        if t > best_time:
            best, best_time = f, t
    return best


def _ago(seconds: float) -> str:
    minutes = seconds / 60
    if minutes < 2:
        return "just now"
    if minutes < 90:
        return f"{round(minutes)} minutes ago"
    hours = minutes / 60
    if hours < 36:
        return f"{round(hours)} hours ago"
    return f"{round(hours / 24)} days ago"


_NEWEST = r"(?:newest|latest|most recent|last|recent|new)"


@ability("find_newest", "find the newest file of a kind in a folder and show it selected in File Explorer",
         rf"(?P<value>(?:(?:open|go to) (?:my |the )?(?:{'|'.join(_FOLDERS)})(?: folder)? (?:and )?)?"
         rf"(?:find|show|select|open|where is|where's|get)(?: me)? (?:my |the )?{_NEWEST} (?:{_KIND_WORDS})s?"
         rf"(?: (?:in|from) (?:my |the )?(?:{'|'.join(_FOLDERS)})(?: folder)?)?)",
         value="e.g. newest pdf in downloads")
def find_newest(said: str, open_it: bool = False) -> str:
    said = said.lower()
    folder, exts, label = _parse(said)
    try:
        f = newest(folder, exts)
    except (OSError, PermissionError, ValueError) as e:
        return f"Not done: I can't read {folder} ({e})."
    said_folder = folder.rsplit("/", 1)[-1]  # "Screenshots 1", not "pictures/Screenshots 1"
    if not f:
        return f"There's no {label} in {said_folder}."
    if re.match(r"^open\b", said) and not re.match(rf"^open (?:my |the )?(?:{'|'.join(_FOLDERS)})", said):
        return files.open_path(str(f))  # "open my latest pdf": open the file itself
    files.show_in_explorer(str(f))
    shown = _wait_for_explorer(f.parent.name)
    when = _ago(time.time() - f.stat().st_mtime)
    where = "selected in File Explorer" if shown else "in File Explorer"
    return f"The newest {label} in {said_folder} is {f.stem}, from {when}. It's {where}."


def _wait_for_explorer(folder_name: str, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(p == "explorer.exe" and folder_name.lower() in t.lower() for _, p, t in desktop._app_windows()):
            return True
        time.sleep(0.15)
    return False


# ---- a file in the open File Explorer folder, by its spoken name or size ---------------------------
#
# 30 Sep: "there's a file called the_brutal_revenge_not_ready, open that" clicked the name (which only
# selects it) and a check waited for a window; "open the file with size 37,272 KB" searched Chrome. Both are
# plain facts about the folder, so they're read from the folder in code and the file is opened directly.

_PROGRAMS = (".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".com", ".lnk")
_UNITS = {"b": 1, "byte": 1, "bytes": 1, "kb": 1024, "kilobyte": 1024, "kilobytes": 1024, "mb": 1024 ** 2,
          "megabyte": 1024 ** 2, "megabytes": 1024 ** 2, "gb": 1024 ** 3, "gigabyte": 1024 ** 3, "gigabytes": 1024 ** 3}


def explorer_folder():
    """The folder shown in File Explorer: the one in front, else the most recent one."""
    import win32com.client
    import win32gui
    from pathlib import Path
    front = win32gui.GetForegroundWindow()
    found = []
    for w in win32com.client.Dispatch("Shell.Application").Windows():
        try:
            path = w.Document.Folder.Self.Path
            if path and Path(path).is_dir():
                found.append((int(w.HWND), Path(path)))
        except Exception:
            continue
    for hwnd, path in found:
        if hwnd == front:
            return path
    return found[-1][1] if found else None


def _plain(name: str) -> str:
    """'the_brutal_revenge-not ready.mp4' / 'the underscore brutal underscore…' -> 'the brutal revenge not ready'."""
    name = re.sub(r"\.[a-z0-9]{1,5}$", "", name.lower())
    name = re.sub(r"\b(underscore|dash|hyphen|dot)\b", " ", name)
    return " ".join(re.sub(r"[_\-.,]+", " ", name).split())


def _size_bytes(said: str) -> tuple[float, float] | None:
    """'37,272 kilobytes' -> (bytes, tolerance). Explorer rounds sizes, so a small tolerance."""
    m = re.search(r"(\d{1,3}(?:[, ]\d{3})+|\d+)(\.\d+)?\s*(bytes?|kb|kilobytes?|mb|megabytes?|gb|gigabytes?)\b", said.lower())
    if not m:
        return None
    n = float(re.sub(r"[, ]", "", m.group(1)) + (m.group(2) or ""))
    unit = _UNITS[m.group(3)]
    return n * unit, n * unit * 0.02 + 1024  # Explorer rounds to whole KB; spoken sizes are rounder


def pick(folder, said: str):
    """(the file meant, or None, why not)."""
    from rapidfuzz import fuzz
    entries = []
    for f in folder.iterdir():
        try:
            if f.name.startswith(("~$", ".")) or files.is_secret(f.name):
                continue
            entries.append((f, f.stat().st_size if f.is_file() else -1))
        except OSError:
            continue
    size = _size_bytes(said)
    if size:
        want, tol = size
        hits = [f for f, n in entries if n >= 0 and abs(n - want) <= tol]
        if len(hits) == 1:
            return hits[0], ""
        return None, ("No file in " if not hits else "More than one file in ") + f"{folder.name} is that size."
    want = _plain(said)
    scored = sorted(((max(fuzz.ratio(want, _plain(f.name)), fuzz.token_sort_ratio(want, _plain(f.name))), f)
                     for f, _ in entries), key=lambda s: -s[0])
    if not scored or scored[0][0] < 80:
        return None, f"There's nothing called {said} in {folder.name}."
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 3 and _plain(scored[1][1].name) != _plain(scored[0][1].name):
        return None, f"More than one thing in {folder.name} is called something like {said}: {scored[0][1].name}, {scored[1][1].name}."
    return scored[0][1], ""


@ability("open_file_here", "open a file in the open Explorer folder",
         r"(?:there(?:'s| is) an? (?:full |whole )?(?:file|folder|video) (?:called|named) )(?P<value>.+?),? (?:please )?open (?:that|it)(?: one)?",
         r"open (?:the |that )?(?:file|folder|video|pdf|document|photo|song|one) (?:called|named) (?P<value>.+)",
         r"(?:open|play) (?:the |that )?(?:file|video|one|pdf|song) (?:with|of) (?:a )?size (?:of )?(?P<value>.+)",
         value="name or size")
def open_file_here(said: str):
    import os
    folder = explorer_folder()
    if not folder:
        return "Not done: no File Explorer folder is open. Say which folder, like 'open downloads'."
    f, why = pick(folder, said)
    if not f:
        return f"Not done: {why}"
    if f.is_file() and f.suffix.lower() in _PROGRAMS:
        return f"Not done: {f.name} is a program or script; I don't run those from a file name. Say 'open app' for apps."
    os.startfile(str(f))
    return f"Opened {f.name}."


@ability("open_folder", "open one of the user's folders (Downloads, Documents, Desktop, Pictures, Music, Videos)",
         r"(?:open|go to|take me to) (?:my |the )?(?P<value>downloads?|documents?|desktop|pictures?|photos|music|"
         r"videos|screenshots)(?: folder)?",
         # "show me my desktop" means minimise everything: showing needs the word folder
         r"show(?: me)? (?:my |the )?(?P<value>downloads?|documents?|desktop|pictures?|photos|music|videos|"
         r"screenshots) folder",
         value="downloads/documents/desktop/pictures/music/videos/screenshots")
def open_folder(value: str):
    """1 Oct speed report: 'Open downloads.' went to the AI (2 calls, 6 s). A folder the user names is instant."""
    name = {"download": "downloads", "document": "documents", "picture": "pictures", "photos": "pictures",
            "screenshots": _screenshots()}.get(value, value)
    return files.open_path(name)
