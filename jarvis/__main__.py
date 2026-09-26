"""Entry point.

    python -m jarvis                  voice assistant with a tray icon (normal use)
    python -m jarvis --console        voice assistant, no tray, logs in the terminal
    python -m jarvis --text           type commands instead of speaking (for testing skills)
    python -m jarvis --list-devices   show microphones
    python -m jarvis --install-autostart / --remove-autostart
"""

import argparse
import logging

from .config import load_config
from .log import setup_logging

log = logging.getLogger("jarvis")


_mutex = None


def _claim_single_instance() -> bool:
    """Two copies would both answer every command, so only one may listen at a time."""
    import ctypes

    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\JarvisVoiceAssistant")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def text_mode(config: dict):
    from .assistant import Assistant

    assistant = Assistant(config)
    assistant.start_dashboard()
    print(f"AI status page: {assistant.dashboard_url}")
    print("Type a command (empty line to quit). e.g. 'open notepad', 'volume 30', 'timer 10 seconds'")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        assistant.speaker.say(assistant.handle_text(text))


def main():
    p = argparse.ArgumentParser(prog="jarvis")
    p.add_argument("--console", action="store_true")
    p.add_argument("--text", action="store_true")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--install-autostart", action="store_true")
    p.add_argument("--remove-autostart", action="store_true")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    setup_logging(logging.DEBUG if args.debug else logging.INFO)

    if args.list_devices:
        from .audio import list_devices
        print(list_devices())
        return
    if args.install_autostart or args.remove_autostart:
        from . import autostart
        print(autostart.install() if args.install_autostart else autostart.remove())
        return

    config = load_config()
    if args.text:
        text_mode(config)
        return

    if not _claim_single_instance():
        log.warning("Jarvis is already running; not starting a second copy")
        return

    from .assistant import Assistant

    assistant = Assistant(config)
    if args.console:
        try:
            assistant.run()
        except KeyboardInterrupt:
            assistant.stop()
    else:
        from .tray import run_with_tray
        run_with_tray(assistant)


if __name__ == "__main__":
    main()
