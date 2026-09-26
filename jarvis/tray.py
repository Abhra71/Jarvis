"""System tray icon: shows what Jarvis is doing, opens the AI status page, pause or quit."""

import threading

import pystray
from PIL import Image, ImageDraw

from .assistant import Assistant, State
from .usage import usage

_COLORS = {
    State.LOADING: "#9e9e9e",
    State.IDLE: "#2196f3",
    State.LISTENING: "#4caf50",
    State.THINKING: "#ff9800",
    State.LOOKING: "#9c27b0",   # purple: a screenshot is being taken / looked at
    State.ACTING: "#e91e63",    # pink: Jarvis is moving your mouse
    State.SPEAKING: "#00bcd4",
    State.PAUSED: "#616161",
    State.ERROR: "#f44336",
}


def _icon_image(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    d.ellipse((20, 20, 44, 44), fill="white")
    return img


def _ai_line(assistant: Assistant) -> str:
    """e.g. 'AI: gemini-flash-lite-latest (12 requests today, 3 screenshots)'."""
    s = usage.snapshot()
    by_key = {m["key"]: m for m in s["models"]}
    order = assistant.brain.model_order()
    nxt = next((k for k in order if not by_key.get(k, {}).get("state", "").startswith("limit")), None)
    who = nxt.split(":", 1)[1] if nxt else ("all at limit" if order else "no AI key")
    return f"AI: {who} ({s['ai_requests']} requests, {s['screenshots']['count']} screenshots today)"


def run_with_tray(assistant: Assistant):
    icon = pystray.Icon("jarvis", _icon_image(_COLORS[State.LOADING]), "Jarvis: Loading...")

    def on_state(state: State):
        icon.icon = _icon_image(_COLORS[state])
        icon.title = f"Jarvis: {state.value}"

    def toggle_pause(_icon, _item):
        if assistant.paused.is_set():
            assistant.paused.clear()
        else:
            assistant.paused.set()

    def quit_(_icon, _item):
        assistant.stop()
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda _: f"Jarvis: {assistant.state.value}", None, enabled=False),
        pystray.MenuItem(lambda _: _ai_line(assistant), None, enabled=False),
        pystray.MenuItem("Open AI status page", lambda _i, _m: assistant.open_dashboard(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Pause listening", toggle_pause, checked=lambda _: assistant.paused.is_set()),
        pystray.MenuItem("Quit", quit_),
    )
    assistant.on_state = on_state

    worker = threading.Thread(target=assistant.run, name="assistant", daemon=True)
    worker.start()
    icon.run()  # blocks on the main thread until Quit
    worker.join(timeout=3)
