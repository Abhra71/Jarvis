"""File handling: find, open, show, create, copy, move, rename, read and write.

Deliberately NOT possible: deleting anything, or overwriting an existing file
(which would be deleting by another name). Windows system folders are off-limits.
"""

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from rapidfuzz import fuzz

from .apps import _allow_foreground

log = logging.getLogger(__name__)

HOME = Path.home()
_BLOCKED = [Path(os.environ.get(v, d)).resolve() for v, d in
            (("WINDIR", r"C:\Windows"), ("PROGRAMFILES", r"C:\Program Files"),
             ("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), ("PROGRAMDATA", r"C:\ProgramData"))]
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "appdata", "$recycle.bin", ".cache"}


def _known_folders() -> dict[str, Path]:
    folders = {name: HOME / name for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")}
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        folders["OneDrive"] = Path(onedrive)
        for name in ("Desktop", "Documents", "Pictures"):  # OneDrive often takes these over
            if (Path(onedrive) / name).is_dir():
                folders[name] = Path(onedrive) / name
    return {k: v for k, v in folders.items() if v.is_dir()}


def resolve(path: str) -> Path:
    """'Downloads', 'Desktop/notes.txt', '~/x' or a full path -> absolute Path."""
    path = path.strip().strip('"')
    folders = _known_folders()
    first, _, rest = path.replace("\\", "/").partition("/")
    for name, folder in folders.items():
        if first.lower() in (name.lower(), f"my {name.lower()}"):
            return (folder / rest).resolve() if rest else folder
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    return (p if p.is_absolute() else folders.get("Desktop", HOME) / p).resolve()


# Files that hold secrets (API keys, passwords, private keys). Jarvis never reads, copies, moves, renames
# or writes them, so their contents can't reach an AI service. (27 Sep: it tried to read .env while the
# user was editing it, and took screenshots with the keys on screen.)
_SECRET = re.compile(r"(^|[\s\\/])\.env(\.[\w-]+)?\b|\.(pem|key|pfx|p12|kdbx|ppk|keystore)\b|\bid_(rsa|ed25519|ecdsa)\b|"
                     r"credential|secret|password|passwd|api[_ -]?keys?\b|\btokens?\.(json|txt)", re.I)


def is_secret(name: str) -> bool:
    """Is this file name (or a window title showing one) a secrets file?"""
    return bool(_SECRET.search(name or ""))


def _check_allowed(p: Path):
    if is_secret(p.name):
        raise PermissionError(f"{p.name} holds secrets (keys or passwords); I never read or handle those files.")
    for blocked in _BLOCKED:
        if p == blocked or blocked in p.parents:
            raise PermissionError(f"{p} is a Windows system folder; I don't touch those.")


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024


# ---- finding and listing -----------------------------------------------------------

def find_files(name: str, folder: str | None = None, limit: int = 10) -> str:
    """Fuzzy search by file/folder name under the user's folders (or one folder)."""
    roots = [resolve(folder)] if folder else list(dict.fromkeys(_known_folders().values()))
    name_l = name.lower()
    hits, deadline, seen = [], time.monotonic() + 8, 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
            for entry in dirnames + filenames:
                seen += 1
                score = fuzz.partial_ratio(name_l, entry.lower())
                if score >= 85:
                    full = Path(dirpath) / entry
                    try:
                        mtime = full.stat().st_mtime
                    except OSError:
                        continue
                    hits.append((score, mtime, full))
            if time.monotonic() > deadline:
                break
    if not hits:
        return f"No files or folders matching {name!r} found (searched {seen} items)."
    hits.sort(key=lambda h: (-h[0], -h[1]))  # best match, then newest
    lines = [f"{h[2]}{'  [folder]' if h[2].is_dir() else ''}  (modified {time.strftime('%d %b %Y', time.localtime(h[1]))})"
             for h in hits[:limit]]
    return f"Found {len(hits)} match(es):\n" + "\n".join(lines)


def list_folder(folder: str) -> str:
    p = resolve(folder)
    if not p.is_dir():
        return f"{p} isn't a folder."
    items = sorted(p.iterdir(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)[:40]
    lines = [f"{'[folder] ' if i.is_dir() else ''}{i.name}" + ("" if i.is_dir() else f"  ({_size(i.stat().st_size)})")
             for i in items]
    return f"{p} (newest first):\n" + "\n".join(lines) if lines else f"{p} is empty."


# ---- opening -----------------------------------------------------------------------

def open_path(path: str) -> str:
    """Open a file with its normal app, or a folder in File Explorer, in front of the user."""
    p = resolve(path)
    if not p.exists():
        return f"{p} doesn't exist. Try find_files first."
    _allow_foreground()
    os.startfile(p)
    return f"Opened {p.name}."


def show_in_explorer(path: str) -> str:
    """Open File Explorer with the file selected."""
    p = resolve(path)
    if not p.exists():
        return f"{p} doesn't exist."
    _allow_foreground()
    if _select_in_open_window(p):
        return f"Showing {p.name} in File Explorer."
    subprocess.Popen(["explorer.exe", "/select,", str(p)])
    return f"Showing {p.name} in File Explorer."


def _select_in_open_window(p: Path) -> bool:
    """Reuse a File Explorer window already showing that folder (30 Sep: ten "newest pdf" requests opened ten
    Downloads windows): select the file there and bring it forward."""
    try:
        import win32com.client
        import win32gui
        for w in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                folder = w.Document.Folder
                if Path(folder.Self.Path).resolve() != p.parent.resolve():
                    continue
                item = folder.ParseName(p.name)
                if item is None:
                    continue
                w.Document.SelectItem(item, 1 | 4 | 8 | 16)  # select, only it, into view, focus
                hwnd = int(w.HWND)
                if win32gui.IsIconic(hwnd):
                    import win32con
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                return True
            except Exception:
                continue
    except Exception:
        log.debug("Couldn't reuse an Explorer window", exc_info=True)
    return False


# ---- changing (never deleting) ---------------------------------------------------------

def create_folder(path: str) -> str:
    p = resolve(path)
    _check_allowed(p)
    if p.exists():
        return f"{p} already exists."
    p.mkdir(parents=True)
    return f"Created folder {p}."


def _target(src: Path, dest: str) -> Path:
    d = resolve(dest)
    return d / src.name if d.is_dir() else d


def copy_path(source: str, destination: str) -> str:
    src = resolve(source)
    if not src.exists():
        return f"{src} doesn't exist."
    _check_allowed(src)
    dst = _target(src, destination)
    _check_allowed(dst)
    if dst.exists():
        return f"{dst} already exists; I won't overwrite it."
    (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
    return f"Copied {src.name} to {dst.parent}."


def move_path(source: str, destination: str) -> str:
    src = resolve(source)
    if not src.exists():
        return f"{src} doesn't exist."
    _check_allowed(src)
    dst = _target(src, destination)
    _check_allowed(dst)
    if dst.exists():
        return f"{dst} already exists; I won't overwrite it."
    shutil.move(str(src), str(dst))
    return f"Moved {src.name} to {dst.parent}."


def rename_path(path: str, new_name: str) -> str:
    src = resolve(path)
    if not src.exists():
        return f"{src} doesn't exist."
    _check_allowed(src)
    dst = src.with_name(new_name)
    if dst.exists():
        return f"{dst.name} already exists there; I won't overwrite it."
    src.rename(dst)
    return f"Renamed to {new_name}."


# ---- reading and writing text ------------------------------------------------------------

_TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".log", ".ini", ".toml",
             ".yaml", ".yml", ".xml", ".bat", ".ps1", ".java", ".c", ".cpp", ".h", ".sql", ".srt"}


def read_text(path: str, max_chars: int = 6000) -> str:
    p = resolve(path)
    _check_allowed(p)
    if not p.is_file():
        return f"{p} isn't a file."
    if p.suffix.lower() not in _TEXT_EXT:
        return f"I can only read plain text files, not {p.suffix} files. I can open it for you instead."
    text = p.read_text(encoding="utf-8", errors="replace")
    more = f"\n…({len(text) - max_chars} more characters)" if len(text) > max_chars else ""
    return text[:max_chars] + more


def write_text(path: str, content: str, append: bool = False) -> str:
    """Create a new text file, or add to the end of one. Never replaces an existing file's contents."""
    p = resolve(path)
    _check_allowed(p)
    if p.exists() and not append:
        return f"{p.name} already exists; I can add to the end of it, but I won't replace it."
    p.parent.mkdir(parents=True, exist_ok=True)
    if append and p.exists() and p.stat().st_size:
        content = "\n" + content
    with open(p, "a" if append else "x", encoding="utf-8") as f:  # "x" fails rather than overwrite
        f.write(content)
    return f"{'Added to' if append else 'Created'} {p}."
