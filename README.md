# Jarvis v2

Background voice assistant for Windows. Say **"Hey Jarvis"**, wait for the beep, then just talk.
After it answers, you have ~5 seconds to say something else without "Hey Jarvis" again.

## How it decides what to do

1. **Simple commands run instantly, offline:** volume, mute, timers, the time, "open <app>", "open YouTube", plain Google searches.
2. **Everything else goes to Gemini** (needs internet and a key in `.env`). Gemini can use Jarvis's tools
   (open apps and websites, pick a Chrome profile, control tabs and windows, type, press keys, media keys,
   volume, timers) or simply answer a question in a sentence or two.
3. With no internet or no key, the simple commands still work.

## Things to try

| Say | What happens |
|---|---|
| open YouTube in my work profile | Chrome opens in that profile |
| search lofi music on YouTube | YouTube search results |
| open Gmail in the third profile | Profiles by name, email or position |
| new tab / close this tab / next tab / go back / scroll down | Acts on the browser in front |
| minimise Chrome / bring back Notepad / close WhatsApp | Window control (apps can still ask "save?") |
| (on YouTube) search for lofi here → play the second video | Searches inside the site, looks at the screen, moves the real mouse and clicks |
| scroll down / click Subscribe / what's on my screen? | Mouse + screenshots. Asks before Send/Buy/Post/Subscribe/Delete-type clicks |
| find my resume / open Downloads / make a folder called Trips on the desktop | File handling: find, open, show, create, copy, move, rename, read, write |
| delete that file | Refuses: deleting (and overwriting) is deliberately impossible |

Move the mouse yourself at any time to make Jarvis stop what it's doing.
| pause the music / next song | Media keys |
| what's the capital of Peru → "and its population?" | Short answers, remembers context ~5 min |
| volume 30 / mute / set a timer for 10 minutes / what time is it | Offline |

## Running

```
start_jarvis.bat                 # background + tray icon (normal use; also starts at login)
run_console.bat                  # same, but with live logs in a window
.venv\Scripts\python -m jarvis --text            # type instead of speaking
.venv\Scripts\python -m jarvis --list-devices    # find your mic's name for config.toml
.venv\Scripts\python -m jarvis --remove-autostart   # stop starting at login (--install-autostart to redo)
.venv\Scripts\python -m unittest discover tests  # run tests
```

Tray icon colours: blue = waiting for "Hey Jarvis", green = listening, orange = thinking,
**purple = looking at your screen (screenshot)**, pink = moving your mouse, cyan = speaking, grey = paused,
red = error (see `logs/jarvis.log`). Right-click the icon to pause or quit.

## Seeing what the AI is doing

- **Double-click the tray icon** (or say "open the status page") for the AI status page at http://127.0.0.1:8765/
  (only reachable from this PC). It shows the model in use right now, requests / failures / limits per model,
  screenshots, Groq's remaining allowance, and a timeline of what you said and who handled it.
- Say **"AI status"** or **"which model are you using"** for a spoken summary (works offline).
- Daily numbers are kept in `logs/usage-YYYY-MM-DD.json`.

## Gemini key

Get a free key at https://aistudio.google.com/apikey and paste it after `GEMINI_API_KEY=` in `.env`.
Jarvis picks it up without a restart. Never commit `.env`.

## Setup from scratch

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

Models (~150 MB) download to `models/` on first run.

## Layout

```
jarvis/
  __main__.py    entry point, CLI flags, single-instance guard
  assistant.py   main loop: wake word -> record -> STT -> rules or Gemini -> speak -> follow-up
  brain.py       Gemini REST client: tool-calling loop, short replies, conversation memory
  nlu.py         offline rules: text -> Intent
  audio.py       mic stream (sounddevice) + end-of-speech detection (webrtcvad)
  wakeword.py    "hey jarvis" via openWakeWord
  stt.py         faster-whisper, offline
  skills/
    __init__.py  the tool list shared by rules and Gemini
    apps.py      launch apps (Start Menu + config aliases), bring them to the front
    browser.py   Chrome profiles, websites, site searches
    desktop.py   window focus/min/max/close, tabs, address bar, site search, typing, keys, media keys, screenshots
    mouse.py     visible cursor movement, clicks, scrolling; stops if you move the mouse
    files.py     find/open/create/copy/move/rename/read/write files (no delete, no overwrite)
    volume.py    pycaw
    timer.py
  tts.py         edge-tts neural voice, falls back to offline Windows voice
  tray.py        tray icon
  autostart.py   Startup-folder shortcut
config.toml      all settings and app aliases
.env             your Gemini key (not in git)
```

## Tuning

- Triggers by itself -> raise `wakeword.threshold` to 0.6-0.7. Misses you -> lower to 0.3-0.4.
- Cuts you off mid-sentence -> raise `listen.silence_seconds` to 1.2.
- Follow-up listening annoying -> `listen.followup_seconds = 0`.
- `stt.model = "small.en"` was tested: same accuracy on commands, 2x slower, so `base.en` stays.

## Notes on this PC

- Windows Smart App Control blocks a scikit-learn DLL. openWakeWord only needs scikit-learn for training,
  so `wakeword.py` stubs out that import.
- Gemini is called over plain HTTPS (httpx) rather than Google's SDK, whose compiled parts might be blocked the same way.
