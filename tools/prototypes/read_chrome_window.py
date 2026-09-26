"""READ-ONLY probe: what can Jarvis read from each open Chrome window via Windows UI Automation?
Clicks nothing, types nothing. Also looks for a chess board in a screenshot."""
import sys, time, collections
sys.path.insert(0, r"C:\Syntax_Assembler\Jarvis")
import logging; logging.disable(logging.WARNING)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from jarvis.skills import desktop

UIA, uia = desktop._uia()
TYPES = {UIA.UIA_ButtonControlTypeId: "button", UIA.UIA_HyperlinkControlTypeId: "link",
         UIA.UIA_EditControlTypeId: "edit", UIA.UIA_TextControlTypeId: "text", UIA.UIA_ImageControlTypeId: "image",
         UIA.UIA_TabItemControlTypeId: "tab", UIA.UIA_CheckBoxControlTypeId: "checkbox",
         UIA.UIA_ListItemControlTypeId: "listitem", UIA.UIA_MenuItemControlTypeId: "menuitem",
         UIA.UIA_ComboBoxControlTypeId: "combobox", UIA.UIA_SliderControlTypeId: "slider"}
want = set(sys.argv[1:])  # optional words to filter which windows to show

for hwnd, proc, title in desktop._app_windows():
    if proc != "chrome.exe":
        continue
    if want and not any(w in title.lower() for w in want):
        continue
    t0 = time.monotonic()
    root = uia.ElementFromHandle(hwnd)
    cond = uia.CreateTrueCondition()
    els = root.FindAll(UIA.TreeScope_Descendants, cond)
    dt = time.monotonic() - t0
    counts, named = collections.Counter(), []
    for i in range(els.Length):
        e = els.GetElement(i)
        kind = TYPES.get(e.CurrentControlType)
        if not kind:
            continue
        counts[kind] += 1
        name = (e.CurrentName or "").strip().replace("\n", " ")
        if kind in ("button", "link", "edit", "checkbox", "combobox", "slider", "menuitem") and name and not e.CurrentIsOffscreen:
            r = e.CurrentBoundingRectangle
            named.append(f"{kind:9} {name[:60]!r}  @({r.left},{r.top})")
    print(f"\n=== {title[:70]}")
    print(f"read {els.Length} elements in {dt:.2f}s; by type: {dict(counts)}")
    print(f"named, on-screen clickables: {len(named)}")
    for n in named[:200]:
        print("   ", n)
