"""System master volume through the Windows Core Audio API (pycaw)."""

import logging
import os
from ctypes import POINTER, cast

import comtypes
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

log = logging.getLogger(__name__)


def _endpoint():
    try:
        comtypes.CoInitialize()  # needed on every thread that touches COM
    except OSError:
        pass  # already initialised in another mode (pywinauto does this); the volume API works either way
    speakers = AudioUtilities.GetSpeakers()
    # Newer pycaw wraps the device and exposes the endpoint directly.
    if hasattr(speakers, "EndpointVolume"):
        return speakers.EndpointVolume
    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def get_volume() -> int:
    return round(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(level: int) -> str:
    level = max(0, min(100, level))
    ep = _endpoint()
    ep.SetMute(0, None)
    if _apps_muted_by_jarvis:  # "volume 30" after "mute" should bring the sound back
        _mute_other_apps(False)
    ep.SetMasterVolumeLevelScalar(level / 100, None)
    return f"Volume set to {level} percent."


def change_volume(direction: int, step: int) -> str:
    return set_volume(get_volume() + direction * step)


_apps_muted_by_jarvis = False


def _mute_other_apps(on: bool) -> int:
    """Mute/unmute every app's own audio except Jarvis. Returns how many apps were changed."""
    global _apps_muted_by_jarvis
    _apps_muted_by_jarvis = on
    me = os.getpid()
    changed = 0
    for session in AudioUtilities.GetAllSessions():
        proc = session.Process
        if proc and proc.pid == me:
            continue
        session.SimpleAudioVolume.SetMute(1 if on else 0, None)
        changed += 1
    return changed


def mute(on: bool) -> str:
    """'Mute' silences every other app but keeps the PC itself on, so Jarvis can still talk to you.
    (Muting the whole PC used to make Jarvis silent too, so its "Yes, my lord?" and chimes vanished.)"""
    ep = _endpoint()
    ep.SetMute(0, None)
    _mute_other_apps(on)
    return "Muted everything except me." if on else "Unmuted."


def others_muted() -> bool:
    """Are other apps silenced (by "mute", or the whole PC muted)?"""
    if _apps_muted_by_jarvis:
        return True
    try:
        return bool(_endpoint().GetMute())
    except Exception:
        return False


def ensure_jarvis_audible():
    """Called before Jarvis makes a sound. If the whole PC is muted (keyboard key, taskbar), switch to
    'everything else muted' instead, so the user still hears Jarvis but nothing else comes back on."""
    try:
        ep = _endpoint()
        if ep.GetMute():
            _mute_other_apps(True)
            ep.SetMute(0, None)
            log.info("PC was muted: muted the other apps instead so Jarvis can be heard")
    except Exception:
        log.debug("Couldn't check mute state", exc_info=True)


DUCK_TO = 0.12  # other apps play at 12% of their level while Jarvis listens


def duck() -> list:
    """Turn every other app down while Jarvis listens, like a smart speaker does. 30 Sep: a song playing in
    Brave was heard mixed with the user's voice, and most commands came out wrong. Returns what restore() needs."""
    me = os.getpid()
    saved = []
    try:
        for session in AudioUtilities.GetAllSessions():
            proc = session.Process
            if not proc or proc.pid == me:
                continue
            vol = session.SimpleAudioVolume
            level = vol.GetMasterVolume()
            if level > DUCK_TO:
                vol.SetMasterVolume(level * DUCK_TO, None)
                saved.append((vol, level))
    except Exception:
        log.debug("Couldn't turn other apps down", exc_info=True)
    return saved


def restore(saved: list):
    for vol, level in saved:
        try:
            vol.SetMasterVolume(level, None)
        except Exception:
            log.debug("Couldn't turn an app back up", exc_info=True)
