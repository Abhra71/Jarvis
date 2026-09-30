"""Windows switches through Quick Settings (Win+A): Night light, Bluetooth, Wi-Fi, Airplane mode, Energy saver,
Live captions, Mobile hotspot. No mouse, no guessing: each switch has a fixed id and reports its own state, so
every change is checked by reading the state back (mapped live on 30 Sep).

    Wi-Fi                Microsoft.QuickAction.WiFi
    Bluetooth            Microsoft.QuickAction.Bluetooth
    Night light          Microsoft.QuickAction.BlueLightReduction
    Airplane mode        Microsoft.QuickAction.AirplaneMode
    Energy saver         Microsoft.QuickAction.BatterySaver
    Live captions        Microsoft.QuickAction.LiveCaptions
    Mobile hotspot       Microsoft.QuickAction.MobileHotspot

Brightness is read and set directly (WMI), with no panel at all.
"""

import logging
import time

import win32gui

from . import desktop, keys

log = logging.getLogger(__name__)

SWITCHES = {
    "wifi": ("Wi-Fi", "Microsoft.QuickAction.WiFi"),
    "bluetooth": ("Bluetooth", "Microsoft.QuickAction.Bluetooth"),
    "night light": ("Night light", "Microsoft.QuickAction.BlueLightReduction"),
    "airplane mode": ("Airplane mode", "Microsoft.QuickAction.AirplaneMode"),
    "energy saver": ("Energy saver", "Microsoft.QuickAction.BatterySaver"),
    "live captions": ("Live captions", "Microsoft.QuickAction.LiveCaptions"),
    "mobile hotspot": ("Mobile hotspot", "Microsoft.QuickAction.MobileHotspot"),
}
ALIASES = {"wi fi": "wifi", "wi-fi": "wifi", "internet": "wifi", "blue tooth": "bluetooth", "nightlight": "night light",
           "night mode": "night light", "blue light filter": "night light", "flight mode": "airplane mode",
           "aeroplane mode": "airplane mode", "battery saver": "energy saver", "power saver": "energy saver",
           "captions": "live captions", "hotspot": "mobile hotspot"}
PANEL_CLASS = "ControlCenterWindow"


def switch_name(said: str) -> str | None:
    s = " ".join(said.lower().replace("-", " ").split())
    s = ALIASES.get(s, s)
    return s if s in SWITCHES else None


def _panel(timeout: float = 2.5):
    """The Quick Settings panel, opened if needed."""
    hwnd = win32gui.GetForegroundWindow()
    if win32gui.GetClassName(hwnd) != PANEL_CLASS:
        keys.press("win+a")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.15)
            hwnd = win32gui.GetForegroundWindow()
            if win32gui.GetClassName(hwnd) == PANEL_CLASS:
                break
        else:
            return None
    return hwnd


def _close(hwnd):
    """Close the panel and make sure it's gone (30 Sep: one Esc during its animation left it open)."""
    for _ in range(3):
        if not hwnd or win32gui.GetClassName(win32gui.GetForegroundWindow()) != PANEL_CLASS:
            return
        keys.press("esc")
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if win32gui.GetClassName(win32gui.GetForegroundWindow()) != PANEL_CLASS:
                return


def _switch(hwnd, auto_id: str):
    UIA, uia = desktop._uia()
    root = uia.ElementFromHandle(hwnd)
    deadline = time.monotonic() + 1.5
    while True:  # the panel animates in: its buttons appear a moment later
        el = root.FindFirst(UIA.TreeScope_Descendants,
                            uia.CreatePropertyCondition(UIA.UIA_AutomationIdPropertyId, auto_id))
        if el or time.monotonic() >= deadline:
            break
        time.sleep(0.15)
    if not el:
        return None, None
    toggle = el.GetCurrentPattern(UIA.UIA_TogglePatternId).QueryInterface(UIA.IUIAutomationTogglePattern)
    return el, toggle


def state(name: str) -> bool | None:
    """Is this switch on? None if it can't be read."""
    label, auto_id = SWITCHES[name]
    hwnd = _panel()
    if not hwnd:
        return None
    try:
        _, toggle = _switch(hwnd, auto_id)
        return None if toggle is None else toggle.CurrentToggleState == 1
    finally:
        _close(hwnd)


def set_switch(name: str, on: bool) -> str:
    label, auto_id = SWITCHES[name]
    hwnd = _panel()
    if not hwnd:
        return "Not done: Quick Settings didn't open."
    try:
        _, toggle = _switch(hwnd, auto_id)
        if toggle is None:
            return f"Not done: there's no {label} switch in Quick Settings."
        if (toggle.CurrentToggleState == 1) == on:
            return f"{label} is already {'on' if on else 'off'}."
        toggle.Toggle()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:  # Bluetooth and Wi-Fi take a moment to switch
            time.sleep(0.2)
            if (toggle.CurrentToggleState == 1) == on:
                log.info("%s switched %s", label, "on" if on else "off")
                return f"{label} is {'on' if on else 'off'}."
        return f"Not done: {label} didn't switch {'on' if on else 'off'}."
    finally:
        _close(hwnd)


# ---- brightness (the laptop's own screen) ------------------------------------------------------------------

def _wmi():
    import win32com.client
    return win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", "root\\WMI")


def brightness() -> int | None:
    try:
        return int([m.CurrentBrightness for m in _wmi().ExecQuery("SELECT * FROM WmiMonitorBrightness")][0])
    except Exception:
        log.debug("Couldn't read the brightness", exc_info=True)
        return None


def set_brightness(level: int) -> str:
    level = max(0, min(100, int(level)))
    try:
        svc = _wmi()
        for m in svc.ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods"):
            args = m.Methods_("WmiSetBrightness").InParameters.SpawnInstance_()
            args.Properties_.Item("Timeout").Value = 1
            args.Properties_.Item("Brightness").Value = level
            m.ExecMethod_("WmiSetBrightness", args)
    except Exception:
        log.debug("Couldn't set the brightness", exc_info=True)
        return "Not done: this screen's brightness can't be set from here (an external monitor?)."
    deadline = time.monotonic() + 1.5
    now = None
    while time.monotonic() < deadline:
        now = brightness()
        if now is not None and abs(now - level) <= 5:  # screens step in levels, e.g. 40 -> 41
            return f"Brightness is {now} percent."
        time.sleep(0.15)
    return f"Not done: brightness is still {now} percent."


# ---- Bluetooth devices: connect / disconnect (Settings > Bluetooth & devices) ------------------------------
#
# Mapped on 30 Sep: each paired device is a group named like "Rockerz 480, Category ..., State Not connected"
# holding a "Connect" (or "Disconnect") button. The device is connected when its group says "Connected".

GENERIC_DEVICES = ("headphones", "headphone", "earphones", "earbuds", "buds", "headset", "speaker", "speakers")


def _settings_bluetooth(timeout: float = 6.0):
    import os
    os.startfile("ms-settings:bluetooth")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.3)
        hwnd = win32gui.GetForegroundWindow()
        if desktop.front_window().startswith("applicationframehost: Settings") and _device_groups(hwnd):
            return hwnd
    return None


def _device_groups(hwnd) -> list:
    UIA, uia = desktop._uia()
    groups = uia.ElementFromHandle(hwnd).FindAll(
        UIA.TreeScope_Descendants, uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_GroupControlTypeId))
    out = []
    for i in range(groups.Length):
        g = groups.GetElement(i)
        name = g.CurrentName or ""
        if ", State " in name:
            out.append((name.split(",")[0].strip(), name, g))
    return out


def _pick(devices: list, said: str):
    from rapidfuzz import fuzz
    s = " ".join(said.lower().replace("my ", "").split())
    if not devices:
        return None
    words = [w for w in s.split() if w not in ("the", "bluetooth")]
    if words and all(w in GENERIC_DEVICES for w in words) and len(devices) == 1:  # "my headphones"
        return devices[0]
    best = max(devices, key=lambda d: fuzz.partial_ratio(d[0].lower(), s))
    return best if fuzz.partial_ratio(best[0].lower(), s) >= 70 else None  # never a guess ("connect to wifi")


def _connected(group_name: str) -> bool:
    state = group_name.rsplit("State ", 1)[-1].lower()
    return state.startswith("connected")


def connect_device(said: str, on: bool = True) -> str:
    if on and state("bluetooth") is False:
        r = set_switch("bluetooth", True)
        if r.startswith("Not done"):
            return r
    hwnd = _settings_bluetooth()
    if not hwnd:
        return "Not done: the Bluetooth settings page didn't open."
    UIA, uia = desktop._uia()
    try:
        dev = _pick(_device_groups(hwnd), said)
        if not dev:
            names = ", ".join(d[0] for d in _device_groups(hwnd)) or "none"
            return f"Not done: no paired device like {said!r}. Paired: {names}."
        name, full, group = dev
        if _connected(full) == on:
            return f"{name} is already {'connected' if on else 'disconnected'}."
        want = "Connect" if on else "Disconnect"
        btn = group.FindFirst(UIA.TreeScope_Descendants, uia.CreatePropertyCondition(UIA.UIA_NamePropertyId, want))
        if not btn:
            return f"Not done: there's no {want} button for {name}."
        btn.GetCurrentPattern(UIA.UIA_InvokePatternId).QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
        deadline = time.monotonic() + (15.0 if on else 6.0)  # headphones take a few seconds to pair up
        while time.monotonic() < deadline:
            time.sleep(0.5)
            now = next((d for d in _device_groups(hwnd) if d[0] == name), None)
            if now and _connected(now[1]) == on:
                log.info("%s %s", name, "connected" if on else "disconnected")
                return f"{'Connected to' if on else 'Disconnected'} {name}."
        return (f"Not done: {name} didn't connect. Is it switched on and near the laptop?" if on
                else f"Not done: {name} is still connected.")
    finally:
        if win32gui.IsWindow(hwnd):
            import win32con
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)  # close Settings again
