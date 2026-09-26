"""Bring Chrome forward, switch through its tabs (UIA select, no clicks on pages), read each page, then
bring the Claude app back. Saves a screenshot per tab for the chess-board check."""
import sys, time, collections
sys.path.insert(0, r"C:\Syntax_Assembler\Jarvis")
import logging; logging.disable(logging.WARNING)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from jarvis.skills import desktop

OUT = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "logs")
UIA, uia = desktop._uia()
KINDS = {UIA.UIA_ButtonControlTypeId: "button", UIA.UIA_HyperlinkControlTypeId: "link",
         UIA.UIA_EditControlTypeId: "edit", UIA.UIA_CheckBoxControlTypeId: "checkbox",
         UIA.UIA_ComboBoxControlTypeId: "combobox", UIA.UIA_SliderControlTypeId: "slider",
         UIA.UIA_MenuItemControlTypeId: "menuitem", UIA.UIA_ListItemControlTypeId: "listitem",
         UIA.UIA_TextControlTypeId: "text", UIA.UIA_ImageControlTypeId: "image"}

windows = desktop._app_windows()
claude = next((w for w in windows if "claude" in w[1]), None)
chrome = next((w for w in windows if w[1] == "chrome.exe"), None)
desktop._focus(chrome[0])
time.sleep(1)

tabs = [t for t in desktop._browser_tabs() if t[0] == chrome[0]]
for i, (hwnd, title, el) in enumerate(tabs):
    el.GetCurrentPattern(UIA.UIA_SelectionItemPatternId).QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
    time.sleep(2.5)
    t0 = time.monotonic()
    els = uia.ElementFromHandle(hwnd).FindAll(UIA.TreeScope_Descendants, uia.CreateTrueCondition())
    dt = time.monotonic() - t0
    counts, lines = collections.Counter(), []
    for j in range(els.Length):
        e = els.GetElement(j)
        kind = KINDS.get(e.CurrentControlType)
        if not kind:
            continue
        counts[kind] += 1
        name = (e.CurrentName or "").strip().replace("\n", " ")
        r = e.CurrentBoundingRectangle
        if name and not e.CurrentIsOffscreen and r.top > 140:  # page area only (below Chrome's toolbars)
            lines.append(f"{kind:9} {name[:70]!r} @({r.left},{r.top},{r.right - r.left}x{r.bottom - r.top})")
    open(fr"{OUT}\tab{i}.jpg", "wb").write(desktop.screenshot_jpeg(1100))
    with open(fr"{OUT}\tab{i}.txt", "w", encoding="utf-8") as f:
        f.write(f"=== {title}\nread {els.Length} elements in {dt:.2f}s; {dict(counts)}\n" + "\n".join(lines))
    print(f"tab{i}: {title[:50]!r}: {els.Length} elements in {dt:.2f}s, {len(lines)} named items in the page area")

if claude:
    desktop._focus(claude[0])
print("done")
