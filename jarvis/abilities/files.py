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


def _parse(said: str) -> tuple[str, tuple[str, ...], str]:
    """'open my downloads and find the newest pdf' -> ('Downloads', ('.pdf',), 'PDF')."""
    folder = next((f for f in _FOLDERS if f in said), "")
    after = re.split(_NEWEST, said, maxsplit=1)[-1]  # the kind is named after "newest" ("open downloads and…")
    kind = re.search(rf"\b({_KIND_WORDS})s?\b", after)
    word = kind.group(1) if kind else "file"
    if not folder:
        folder = "pictures" if word in ("screenshot",) else "downloads"
    if word == "screenshot":
        folder = "pictures/screenshots" if (files.HOME / "Pictures" / "Screenshots").is_dir() else folder
    label = {"pdf": "PDF", "file": "file", "download": "download"}.get(word, word)
    return folder.title(), KINDS.get(word, ()), label


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
         value="what and where, e.g. 'newest pdf in downloads'")
def find_newest(said: str, open_it: bool = False) -> str:
    said = said.lower()
    folder, exts, label = _parse(said)
    try:
        f = newest(folder, exts)
    except (OSError, PermissionError, ValueError) as e:
        return f"Not done: I can't read {folder} ({e})."
    if not f:
        return f"There's no {label} in {folder}."
    if re.match(r"^open\b", said) and not re.match(rf"^open (?:my |the )?(?:{'|'.join(_FOLDERS)})", said):
        return files.open_path(str(f))  # "open my latest pdf": open the file itself
    files.show_in_explorer(str(f))
    shown = _wait_for_explorer(f.parent.name)
    when = _ago(time.time() - f.stat().st_mtime)
    where = "selected in File Explorer" if shown else "in File Explorer"
    return f"The newest {label} in {folder} is {f.stem}, from {when}. It's {where}."


def _wait_for_explorer(folder_name: str, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(p == "explorer.exe" and folder_name.lower() in t.lower() for _, p, t in desktop._app_windows()):
            return True
        time.sleep(0.15)
    return False
