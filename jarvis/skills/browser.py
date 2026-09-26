"""Chrome profiles and opening websites."""

import json
import logging
import os
import re
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from rapidfuzz import fuzz, process

from .apps import _allow_foreground

log = logging.getLogger(__name__)

LOCAL_STATE = Path(os.environ.get("LOCALAPPDATA", "")) / r"Google\Chrome\User Data\Local State"

# Used by the offline rules; Gemini works out URLs for anything else.
SITES = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.in",
    "whatsapp web": "https://web.whatsapp.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "chess": "https://www.chess.com",
    "chess com": "https://www.chess.com",  # the offline rules hear "chess.com" / "chess dot com" as this
    "youtube com": "https://www.youtube.com",
    "physics wallah": "https://www.pw.live",
    "pw live": "https://www.pw.live",
}

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "github": "https://github.com/search?q={q}",
    "maps": "https://www.google.com/maps/search/{q}",
}

_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
             "seventh": 7, "eighth": 8, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6}


@dataclass
class Profile:
    directory: str        # "Profile 2"
    name: str             # "Work", the name shown in Chrome's profile picker
    email: str
    full_name: str = ""   # Google account name, e.g. "Abhra Chakraborty"

    def describe(self) -> str:
        extra = [x for x in (self.full_name if self.full_name.lower() != self.name.lower() else "", self.email) if x]
        return f"{self.name} ({', '.join(extra)})" if extra else self.name


def load_profiles(local_state: Path = LOCAL_STATE) -> list[Profile]:
    """Profiles in the order Chrome's profile picker shows them: alphabetical by name."""
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cache = data.get("profile", {}).get("info_cache", {})
    order = data.get("profile", {}).get("profiles_order") or list(cache)
    order += [d for d in cache if d not in order]
    profiles = []
    for d in order:
        if d not in cache:
            continue
        info = cache[d]
        gaia = info.get("gaia_name", "")
        profiles.append(Profile(d, info.get("name", d), info.get("user_name", ""),
                                "" if gaia in ("", "Error") else gaia))
    # sorted() is stable, so equal names keep Chrome's creation order.
    return sorted(profiles, key=lambda p: p.name.casefold())


_FILLER_WORDS = {"profile", "account", "my", "the", "chrome", "google", "one", "in", "open"}


def find_profile(profiles: list[Profile], spoken: str | None, nicknames: dict[str, str] | None = None) -> Profile | None:
    """'main', 'work', 'my work profile', 'third', 'profile 3', or an email -> Profile.

    Nicknames (from config.toml [chrome_profiles]) come first: several of this user's profiles
    are all named "Abhra", and speech has no capital letters, so names alone can't tell them apart.
    """
    if not spoken or not profiles:
        return None
    for p in profiles:  # exact folder name, e.g. "Profile 2" as Gemini passes it
        if spoken.strip().lower() == p.directory.lower():
            return p

    words = [w for w in re.findall(r"[a-z0-9]+", spoken.lower()) if w not in _FILLER_WORDS]
    s = " ".join(words)
    for nick, folder in (nicknames or {}).items():
        if s == nick.lower() or f" {nick.lower()} " in f" {s} ":
            hit = next((p for p in profiles if p.directory.lower() == folder.lower()), None)
            if hit:
                return hit
    for word, n in _ORDINALS.items():
        if word in s.split() and n <= len(profiles):
            return profiles[n - 1]
    if s.isdigit() and 1 <= int(s) <= len(profiles):
        return profiles[int(s) - 1]

    for p in profiles:  # full account name said exactly, e.g. "Abhra Chakraborty"
        if p.full_name and s == p.full_name.lower() and p.full_name.lower() != p.name.lower():
            return p

    choices = {i: f"{p.name} {p.full_name} {p.email.split('@')[0]}".lower() for i, p in enumerate(profiles)}
    match = process.extractOne(s, choices, scorer=fuzz.WRatio, score_cutoff=70)
    return profiles[match[2]] if match else None


def chrome_path() -> str | None:
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                return winreg.QueryValue(k, None)
        except OSError:
            pass
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        p = Path(base or "") / r"Google\Chrome\Application\chrome.exe"
        if p.exists():
            return str(p)
    return None


class Browser:
    def __init__(self, nicknames: dict[str, str] | None = None):
        self.profiles = load_profiles()
        self.nicknames = {k.lower(): v for k, v in (nicknames or {}).items()}  # "main" -> "Default"
        self.chrome = chrome_path()
        log.info("Chrome: %s, %d profiles", self.chrome or "not found", len(self.profiles))

    def find(self, spoken: str | None) -> Profile | None:
        return find_profile(self.profiles, spoken, self.nicknames)

    def profile_summary(self) -> str:
        out = []
        for i, p in enumerate(self.profiles, 1):
            nicks = [n for n, folder in self.nicknames.items() if folder.lower() == p.directory.lower()]
            also = f" nicknames: {', '.join(nicks)}" if nicks else ""
            out.append(f"{i}. {p.describe()} [folder: {p.directory}]{also}")
        return "; ".join(out)

    def open(self, url: str | None = None, profile: str | None = None) -> str:
        if url and not url.startswith(("http://", "https://")):
            url = SITES.get(url.lower().strip(), f"https://{url.strip()}")
        prof = self.find(profile)
        if profile and not prof:
            return f"I couldn't find a Chrome profile called {profile}."

        _allow_foreground()
        if self.chrome:
            args = [self.chrome]
            if prof:
                args.append(f"--profile-directory={prof.directory}")
            args.append(url or "--new-window")
            subprocess.Popen(args)
        else:
            os.startfile(url or "https://www.google.com")

        nick = next((n for n, f in self.nicknames.items() if prof and f.lower() == prof.directory.lower()), None)
        where = f" in your {nick} profile" if nick else (f" in the {prof.name} profile" if prof else "")
        what = url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.") if url else "Chrome"
        log.info("Opened %s%s", url or "Chrome", where)
        return f"Opened {what}{where}."

    def search(self, query: str, site: str = "google", profile: str | None = None) -> str:
        template = SEARCH_URLS.get((site or "google").lower(), SEARCH_URLS["google"])
        result = self.open(template.format(q=quote_plus(query)), profile)
        if result.startswith("I couldn't"):
            return result
        return f"Searching {site or 'google'} for {query}."
