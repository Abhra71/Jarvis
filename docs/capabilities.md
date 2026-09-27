# Jarvis capability map

What "run the whole PC by voice" means, and how much of it works. **This is the progress measure**: every phase moves rows up this table. Status is only "works" after a live voice check.

- **works**: does it reliably, fast
- **weak**: sometimes, slowly, or through the AI with screenshots
- **missing**: can't do it yet
- **AI**: needs the AI (a luxury, used sparingly) · **0 AI**: done in code

Updated 27 Sep 2026 (after Jarvis 4 phase 1).

## 1. Speaking to Jarvis
| Ability | Example | Status | AI |
|---|---|---|---|
| Wake word | "Hey Jarvis" | works | 0 AI |
| Follow-up without the wake word | answer within 5 s | works | 0 AI |
| Stop mid-task | "Hey Jarvis" while it works | works | 0 AI |
| Understanding speech | anything | weak: ~1 in 4 misheard (Whisper base on the CPU) | 0 AI |
| Dictation mode | "start dictation … new line … stop dictation" | missing | 0 AI |

## 2. Windows and the desktop
| Ability | Example | Status | AI |
|---|---|---|---|
| Open an app | "open notepad", "open VS Code" | works | 0 AI |
| Switch / focus an app | "switch to Chrome", "switch window" | works | 0 AI / AI |
| Minimize / maximize / restore / close | "maximize Brave" | works | AI (~1 s) |
| Show desktop, minimize all | "show desktop" | works | 0 AI |
| Snap left/right, move to other screen | "snap this left" | works (not yet checked live) | 0 AI |
| Virtual desktops | "new desktop", "next desktop" | works (not yet checked live) | 0 AI |
| Close a specific app | "close Claude" | weak (didn't find the Claude window) | AI |
| Screenshot / snip | "take a screenshot" | works | 0 AI |
| Clipboard history | "clipboard history" | works | 0 AI |

## 3. System settings
| Ability | Example | Status | AI |
|---|---|---|---|
| Volume set/up/down/mute | "volume 30" | works | 0 AI |
| Per-app volume / mute | "mute Chrome only" | missing (mutes everything else) | — |
| Brightness | "brightness 50" | missing | — |
| Night light | "turn on night light" | missing | — |
| Wi-Fi on/off/connect | "turn off Wi-Fi" | missing | — |
| Bluetooth on/off/connect device | "connect my headphones" | missing | — |
| Airplane mode | "airplane mode on" | missing | — |
| Display / projector mode | "duplicate screen" | missing | — |
| Power plan, battery | "how much battery?" | missing | — |
| Open any Settings page | "open Bluetooth settings" | works (not yet checked live) | 0 AI |
| Timers | "timer 10 minutes" | works | 0 AI |
| Time | "what's the time" | works | 0 AI |

## 4. Keyboard, mouse, typing
| Ability | Example | Status | AI |
|---|---|---|---|
| Any shortcut by voice | "press control shift T" | works (not yet checked live) | 0 AI |
| Everyday shortcuts | "copy", "paste", "undo", "select all", "save" | works (not yet checked live) | 0 AI |
| Type a short phrase | "type hello" | works | AI |
| Paste long text fast | (automatic) | works | — |
| Click a named button/link | "click Trust" | works (~1–2 s) | AI (text only) |
| Click something without a name | "click the red one" | weak (screenshot, 5–25 s) | AI + vision |
| Scroll | "scroll down" | works | AI |
| Zoom in/out | "zoom in" | works | 0 AI |

## 5. Browser (Chrome, Brave)
| Ability | Example | Status | AI |
|---|---|---|---|
| Open a site | "open youtube", "open chess dot com" | works | 0 AI |
| Tabs: new/close/reopen/next | "close this tab" | works | 0 AI |
| Close a tab by name | "close the chess tab" | works | AI |
| Back/forward/reload | "go back" | works | 0 AI |
| Search | "search python tutorials" | works | AI |
| Chrome profiles | "open my main profile" | works | 0 AI |
| Fill a form / log in | — | not allowed to log in; forms weak | AI |

## 6. YouTube
| Ability | Example | Status | AI |
|---|---|---|---|
| Play X | "play lofi music on YouTube" | works (4 s) | 0 AI |
| Play/pause/next/mute/fullscreen/subtitles | "pause" | works (<0.3 s) | 0 AI |
| Skip ad | "skip the ad" | works (not yet checked live) | 0 AI |
| Seek, speed | "forward 30 seconds" | works | 0 AI |
| Nth result, search | "play the second video" | works | 0 AI |

## 7. Files and uploads
| Ability | Example | Status | AI |
|---|---|---|---|
| Find / open a file | "open my resume" | works | AI |
| New folder, copy, move, rename | "make a folder Trips on the desktop" | works | AI |
| Upload in a file-picker window | "upload resume from Downloads" | missing | — |
| Delete | — | never (by design) | — |
| Secret files (.env, keys) | — | never read (by design) | — |

## 8. Messaging and mail
| Ability | Example | Status | AI |
|---|---|---|---|
| WhatsApp desktop: message someone | "message Mom: I'll be late" | missing | — |
| WhatsApp: read latest message | "what did Rahul say?" | missing | — |
| Gmail: open unread / compose / reply | "reply: sounds good" | missing | — |
| Sending always needs a yes | — | works (safety gate) | 0 AI |

## 9. Coding
| Ability | Example | Status | AI |
|---|---|---|---|
| VS Code commands | "go to line 40", "open terminal", "comment this line" | weak (shortcut sheet only) | AI |
| Spoken C++ with correct syntax | "for int i from 0 to n" | missing | AI |
| Vibe coding: talk to an AI chat box | dictate a prompt into Claude | weak (short typing only) | — |
| BlueJ (school Java): compile/run/new class | "compile" | missing | — |
| Never control VMware / Kali | — | missing (block to add) | — |

## 10. Games
| Ability | Example | Status | AI |
|---|---|---|---|
| Start a game | "start eFootball" | weak (as an app, untested) | 0 AI |
| Minimize / switch away from a full-screen game | "minimize the game" | missing | — |
| Close a game (with a yes) | "close the game" | missing | — |
| chess.com menus | "show hint", "resign" (yes) | works (click by name) | AI |
| Chess moves by voice | "pawn e2 to e4" | weak (screenshot, slow) | AI + vision |
| Chess autoplay | "auto mode on" | missing (last) | — |

## 11. Sites
| Ability | Example | Status | AI |
|---|---|---|---|
| Physics Wallah: batch, subject, lecture | "open chemistry" | weak (click by name only) | AI |

## 12. Being an agent
| Ability | Status |
|---|---|
| Plans several steps at once | missing (one AI round per step) |
| Says what it's doing while doing it | missing |
| Fixes its own small mistakes | missing |
| Remembers new phrasings (no AI next time) | works |
| Announces backup AI / out of AI | works |
| Never does unasked things | works (action budget); small gaps |

## Score
73 abilities:
- **40 work (55%)**;
- 8 weak (11%);
- 22 missing (30%);
- 3 off-limits by design.

Goal: 90%+ work.
