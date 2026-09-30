"""'open <app>': config aliases first, then a fuzzy search of everything in the Start Menu."""

import json
import logging
import os
import re
import subprocess

from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

_SKIP_WORDS = ("uninstall", "readme", "help", "documentation", "release notes")


def sound_key(s: str) -> str:
    """A rough 'how it sounds' key, so a misheard name finds the real one ("Clawed", "CloudF" -> Claude,
    1 Oct). First letter, then the consonants, with the letters that sound alike merged."""
    s = re.sub(r"[^a-z]", "", s.lower())
    if not s:
        return ""
    for a, b in (("ph", "f"), ("ck", "k"), ("ch", "c"), ("sh", "s"), ("x", "ks"), ("q", "k"), ("c", "k"),
                 ("z", "s"), ("v", "f"), ("j", "g")):
        s = s.replace(a, b)
    rest = re.sub(r"[aeiouhwy]", "", s[1:])
    return re.sub(r"(.)\1+", r"\1", s[0] + rest)


def _scan_start_apps() -> dict[str, str]:
    """Name -> 'shell:AppsFolder\\<AppID>'. Covers normal programs and Microsoft Store apps."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        apps = json.loads(out) if out.strip() else []
    except Exception:
        log.exception("Couldn't list Start Menu apps")
        return {}
    if isinstance(apps, dict):
        apps = [apps]

    found = {}
    for app in apps:
        name = app["Name"].lower()
        if not any(w in name for w in _SKIP_WORDS):
            found.setdefault(name, f"shell:AppsFolder\\{app['AppID']}")
    log.info("Indexed %d Start Menu apps", len(found))
    return found


def _allow_foreground():
    """Let the app we launch come to the front.

    Windows won't let a background process (like Jarvis) put a window on top, so
    new apps open behind whatever you're using. A synthetic Alt tap counts as user
    input and earns us foreground rights, which we then pass on to any process.
    """
    import ctypes

    user32 = ctypes.windll.user32
    VK_MENU, KEYEVENTF_KEYUP, ASFW_ANY = 0x12, 0x2, -1
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.AllowSetForegroundWindow(ASFW_ANY)


class AppLauncher:
    def __init__(self, aliases: dict[str, str]):
        self.aliases = {k.lower(): v for k, v in aliases.items()}
        self.start_apps = _scan_start_apps()

    def find(self, spoken: str) -> tuple[str, str] | None:
        """Returns (display name, launch target) or None."""
        spoken = spoken.lower().strip()
        if spoken in self.aliases:
            return spoken, self.aliases[spoken]

        candidates = {**self.start_apps, **self.aliases}
        match = process.extractOne(spoken, candidates.keys(), scorer=fuzz.WRatio, score_cutoff=80)
        if match:
            name = match[0]
            return name, candidates[name]
        return None

    def find_exact(self, spoken: str) -> tuple[str, str] | None:
        """Stricter than find(): only near-exact names, for the offline rules path."""
        spoken = spoken.lower().strip()
        candidates = {**self.start_apps, **self.aliases}
        match = process.extractOne(spoken, candidates.keys(), scorer=fuzz.ratio, score_cutoff=88)
        return (match[0], candidates[match[0]]) if match else None

    def closest(self, spoken: str, n: int = 4) -> list[str]:
        """Nearest installed app names, for when speech recognition mangles a name ("Cloud" for "Claude")."""
        candidates = {**self.start_apps, **self.aliases}
        return [m[0] for m in process.extract(spoken.lower(), candidates.keys(), scorer=fuzz.WRatio, limit=n)
                if m[1] >= 45]

    def suggest(self, spoken: str) -> str | None:
        """The installed app the user most likely meant when the name wasn't found: it must SOUND the same
        (not just share letters), else None."""
        key = sound_key(spoken)
        if len(key) < 2:
            return None
        best, best_score = None, 0.0
        for name in {**self.start_apps, **self.aliases}:
            other = sound_key(name)
            if not other or other[0] != key[0]:
                continue
            score = fuzz.ratio(key, other)
            if score > best_score:
                best, best_score = name, score
        return best if best_score >= 80 else None

    @staticmethod
    def display(name: str, target: str) -> str:
        """What to call it: the app's own name for a store app (the "cloud" alias opens Claude)."""
        if target.startswith("shell:AppsFolder") and "!" in target:
            return target.rsplit("!", 1)[1]
        return name

    def names_for_speech(self, limit: int = 40) -> list[str]:
        """Installed app names worth teaching the speech recogniser (skips Windows/system entries)."""
        skip = ("microsoft", "windows", "setup", "settings", "update", "driver", "control panel", "manual",
                "recovery", "tool", "service", "(", "x86", "x64")
        names = [n for n in self.start_apps if 2 < len(n) <= 22 and not any(s in n for s in skip)]
        return sorted(names, key=len)[:limit]

    def open(self, spoken: str) -> str:
        found = self.find(spoken)
        if not found:
            meant = self.suggest(spoken)
            if meant:
                return f"Not done: there's no app called {spoken}. Did you mean {self.display(meant, {**self.start_apps, **self.aliases}[meant])}?"
            near = self.closest(spoken)
            hint = f" Closest installed apps: {', '.join(near)}." if near else ""
            return f"Sorry, I couldn't find an app called {spoken}.{hint}"
        name, target = found
        log.info("Opening %r -> %s", name, target)
        _allow_foreground()
        if target.startswith("shell:"):
            subprocess.Popen(["explorer.exe", target])
        else:
            try:
                os.startfile(target)
            except OSError:
                # Things like "code" live on PATH rather than in App Paths.
                subprocess.Popen(f'start "" {target}', shell=True)
        return f"Opening {self.display(name, target)}."
