"""Chrome profiles and opening websites."""

import json
import logging
import os
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


def find_profile(profiles: list[Profile], spoken: str | None) -> Profile | None:
    """'work', 'my work profile', 'third', 'profile 3', or an email -> Profile."""
    if not spoken or not profiles:
        return None
    for p in profiles:  # exact folder name, e.g. "Profile 2" as Gemini passes it
        if spoken.strip().lower() == p.directory.lower():
            return p

    s = spoken.lower().replace("profile", "").replace("account", "").replace("my", "").strip()
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
    def __init__(self):
        self.profiles = load_profiles()
        self.chrome = chrome_path()
        log.info("Chrome: %s, %d profiles", self.chrome or "not found", len(self.profiles))

    def profile_summary(self) -> str:
        return "; ".join(f"{i}. {p.describe()} [folder: {p.directory}]" for i, p in enumerate(self.profiles, 1))

    def open(self, url: str | None = None, profile: str | None = None) -> str:
        if url and not url.startswith(("http://", "https://")):
            url = SITES.get(url.lower().strip(), f"https://{url.strip()}")
        prof = find_profile(self.profiles, profile)
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

        where = f" in the {prof.name} profile" if prof else ""
        what = url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.") if url else "Chrome"
        log.info("Opened %s%s", url or "Chrome", where)
        return f"Opened {what}{where}."

    def search(self, query: str, site: str = "google", profile: str | None = None) -> str:
        template = SEARCH_URLS.get((site or "google").lower(), SEARCH_URLS["google"])
        result = self.open(template.format(q=quote_plus(query)), profile)
        if result.startswith("I couldn't"):
            return result
        return f"Searching {site or 'google'} for {query}."
