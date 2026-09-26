"""Start Jarvis at login via a shortcut in the user's Startup folder (no admin needed)."""

import os
import subprocess
import sys
from pathlib import Path

from .config import ROOT

SHORTCUT = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup\Jarvis.lnk"


def install() -> str:
    pythonw = Path(sys.executable).with_name("pythonw.exe")  # no console window
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); "
        "$s.TargetPath = $env:TARGET; $s.Arguments = '-m jarvis'; "
        "$s.WorkingDirectory = $env:WORKDIR; $s.Description = 'Jarvis voice assistant'; $s.Save()"
    )
    env = {**os.environ, "LNK": str(SHORTCUT), "TARGET": str(pythonw), "WORKDIR": str(ROOT)}
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True)
    return f"Jarvis will start at login ({SHORTCUT})"


def remove() -> str:
    if SHORTCUT.exists():
        SHORTCUT.unlink()
        return "Autostart removed."
    return "Autostart was not installed."
