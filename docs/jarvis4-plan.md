# Jarvis 4: run the whole PC by voice (new beginning, same core)

## Context
After v3 steps 1–5b, the user said Jarvis still doesn't feel like their project: it's fast in places but doesn't serve the main purpose. That purpose: **sit back, look at the screen, and do ~99% of computer work by voice, reliably, for hours a day.** That covers:
- typing and voice coding;
- videos;
- Bluetooth, Wi-Fi and settings;
- file uploads;
- zoom and windows;
- WhatsApp and Gmail;
- games (on/off).

Deleting and security actions stay off-limits.

The v3 work optimized speed, tokens and three sites: too narrow.

**Pillars:** reliability, very high speed, accuracy.

**Constraint:** only two free AI accounts (Groq, Gemini). **The AI is a luxury:**
- Everyday work must run in code with zero AI.
- The AI is kept for real judgement: open-ended requests, writing code or text, understanding a screen.

We keep the core that works:
- safety gates, action budget, secrets block;
- screen-as-text (`jarvis/skills/elements.py`);
- the shortcut engine (`keys.py`, `shortcuts.py`);
- routing (`router.py`, `brain.py`);
- site packs (`skills/sites/`);
- tests and logs.

What changes is **what we build on top, and how progress is measured**.

## User decisions (27 Sep)
- **Messaging:** WhatsApp **desktop app** + **Gmail**.
- **Coding:**
  - VS Code for **C++** and "vibe coding" (driving AI chat/Claude by voice).
  - **BlueJ** for school Java.
  - Webots: low priority.
  - **VMware / Kali: never control.** Treat the VMware window as off-limits.
- **Games:** simple on/off controls (launch, minimize, switch away, close) for **eFootball** and any future installed game, plus **chess.com**.
- **AI limits:** announce the switch to the backup AI, and announce when the backup is used up too.
- Chess polish last; Physics Wallah stays on the list.

## Architecture: "AI is a luxury"
Every request passes through four layers and stops at the first that can do it:
1. **Command catalog (code, 0 AI, <0.3 s):**
   - One registry of *abilities*, each with phrases, slots, a function, a safety class and a spoken reply.
   - Parsing is grammar plus fuzzy matching over the user's vocabulary: app names, contacts, Bluetooth devices, Wi-Fi networks.
   - New module `jarvis/abilities/` (one file per area). `nlu.py`'s rules and the site packs move in as abilities; behaviour is unchanged.
2. **Phrase memory (0 AI):** when layer 3 resolves a new phrasing to a catalog call, the phrase→call pair is saved (`data/learned.json`). The next time it's instant. Unsafe calls are never learned.
3. **Groq as translator (~1 s, small):**
   - Unmatched requests go to Groq with a *compact catalog* of ability names and slots, not 30 raw tools.
   - It returns a short plan of catalog calls, several at once.
   - Code executes the plan with text checks (window title, `page_elements`), speaking as it goes.
   - Raw clicks and keys remain as a fallback tool group.
4. **Gemini (vision/backup):** only for "what's on screen / looks like", or when Groq is out. Switches are announced: "Using the backup AI" and "The backup is used up too; only offline commands for now".

**Budget manager** (in `usage.py`):
- tracks tokens per minute per model, waits instead of spilling over, and handles Groq 400 retries;
- `max_tokens` about 300, a capped item list, a daily budget view on the status page.

## Step 0 (first, user's request): clean up the repo and the PC
Surveyed 27 Sep (read-only). Only Jarvis-related clutter; nothing personal outside Jarvis is touched.

**Delete (safe, nothing depends on it):**
- `logs/eval_*.txt` / `*.err` (10 files): raw output from the 26 Sep provider tests of dropped providers. The results live in `docs/ai-provider-report.md` and `logs/ai_eval.jsonl`, which are kept.
- `tools/prototypes/read_chrome_tabs.py`, `read_chrome_window.py`: superseded by `jarvis/skills/elements.py`. Keep `find_board.py` for chess later.
- `docs/v3-plan.md` → move to `docs/archive/`. It's replaced by this plan, which gets copied to `docs/jarvis4-plan.md`. `v3-handoff.md` becomes the living `docs/handoff.md`.
- Branch `wip/multi-provider-routing`, local **and on GitHub**: everything useful was reused on main. (Deleting the GitHub branch is outward-facing; it's covered by this approval.)
- All `__pycache__/` folders (regenerated automatically).
- **PC:**
  - my scratch scripts in `%TEMP%` (`fix*.py`, `brain*.py`, `prompt.py`, `c.py`, `g.py`, `r.py`, `b4.py`);
  - the **pip download cache (~600 MB)**, via `pip cache purge`: only re-downloads if a package is reinstalled.

**Keep:**
- `.venv` (547 MB, needed);
- `models/whisper` base.en (141 MB): removed only after the GPU `small.en` model proves better in Phase 2;
- `logs/jarvis.log` and `usage-*.json` (the evidence for tuning);
- `.env`: already down to the Gemini and Groq keys only.

**Not touched:** other apps' files in `%TEMP%` (262 MB total, used by running programs), anything outside `C:\Syntax_Assembler\Jarvis`.

**Add:** `.gitignore` entries for the future `data/learned.json` and model files; log rotation, so `jarvis.log` can't grow without limit.

**Verify:** tests pass, Jarvis starts, `git status` is clean, and the space freed is reported.

## Build order (each phase is shippable, tested, committed, and updates the capability map)

**Phase 0: Capability map + test harness.**
- `docs/capabilities.md`: every ability by area, with status (works / weak / missing) and example phrases. Coverage becomes the progress measure.
- `tools/smoke.py`: a read-only live check of each ability (for example, reads the Bluetooth state without toggling it).

**Phase 1: Foundation.**
- The catalog + parser, moving the existing rules in.
- Phrase memory.
- Groq as plan-translator.
- The budget manager, Groq fixes (`max_tokens`, 400 retry, capped items) and backup announcements.
- Fixes from the voice test:
  - `ai_status` misfire (`nlu.py`);
  - budget split on commas in numbers (`skills/__init__.py` `action_budget`);
  - launches not counted;
  - Claude window matching.

**Phase 2: Hearing + dictation.**
- faster-whisper `small.en` on CUDA (`stt.py`, `device="cuda"`, int8_float16). Measure VRAM and latency against CPU `base.en`; fall back to CPU automatically. Needs the NVIDIA cuBLAS/cuDNN pip wheels; check Smart App Control.
- Vocabulary hints from the catalog (apps, contacts, devices, sites).
- **Dictation mode:** "start dictation" types everything said, with spoken punctuation ("new line", "comma", "full stop"), "scratch that", "stop dictation". Zero AI.

**Phase 3: System abilities.**
- Volume per app, brightness, night light, Wi-Fi on/off/connect, **Bluetooth on/off/connect device**, airplane mode, display/projection (win+p), power plan, battery status, open any Settings page (`ms-settings:` URIs).
- **Windows:** snap left/right, move to other screen, maximize, min/max/close by name, virtual desktops.
- Implemented with Windows APIs/PowerShell/UI Automation (for example, Bluetooth via the Radio API or Settings + `click_element`), not screenshots.

**Phase 4: Apps, files, messaging.**
- **WhatsApp desktop:** "message Mom: I'll be late" → open chat by search, type, **confirm, then send**; "read my last message from X".
- **Gmail:** compose/reply (confirm before send), open unread.
- **File-picker upload:** in any Open/Upload dialog, "upload resume from Downloads" types the path into the dialog's File name box through UI Automation.
- Explorer: go to folder, new folder, rename, copy/move (existing `files.py`).

**Phase 5: Voice coding.**
- **VS Code (C++):**
  - editor commands in code (go to line, select line, comment, run/build task, terminal, next error);
  - spoken code with correct syntax ("for int i from 0 to n" → `for (int i = 0; i < n; i++) {}`). The AI generates the snippet, then it's pasted.
  - "Vibe coding": dictate into Claude/AI chat boxes.
- **BlueJ (Java):** compile/run/new class via its shortcuts and UIA.
- **VMware window: never touched.** A block list in the safety layer.

**Phase 6: Game mode + agent feel.**
- **Games:** "start eFootball", "minimize the game", "switch to Chrome", "close the game" (with a yes). Detect a full-screen game to use safe keys (alt+tab, win+d) and quieter wake-word handling. Chess.com menus by name.
- **Agent feel:**
  - speak while acting ("Opening WhatsApp…");
  - a constant front-window text snapshot, so there's no "look around" step;
  - retry once with the next best option, then ask;
  - use context before "what do you mean?".

**Phase 7: Site packs.** Physics Wallah (needs one discovery session with the user), then chess autoplay last.

## Critical files
- **New:** `jarvis/abilities/` (catalog, parser, areas), `data/learned.json`, `docs/capabilities.md`, `tools/smoke.py`.
- **Changed:**
  - `jarvis/assistant.py` (layer order);
  - `jarvis/brain.py` (plan-translator, announcements);
  - `jarvis/router.py` (compact catalog);
  - `jarvis/usage.py` (budget manager);
  - `jarvis/groq_backup.py` (400 retry, `max_tokens`);
  - `jarvis/stt.py` (GPU, hints, dictation);
  - `jarvis/nlu.py` (rules move into abilities);
  - `jarvis/skills/*` reused as the doers (`keys.py`, `elements.py`, `desktop.py`, `files.py`, `volume.py`, `sites/`).

## Verification
- Unit tests per ability: phrase → call, safety class, dialog/window mocks (the existing pattern: tests never touch the real screen).
- `tools/smoke.py`: read-only live checks on this PC after each phase.
- `tools/ai_eval.py`: AI accuracy/speed per model stays ≥ 15/16; token use per request is tracked.
- Real voice session per phase, scored from `logs/jarvis.log`:
  - share of requests with no AI (target 80–90%);
  - median time;
  - misheard rate;
  - unasked actions (target 0).
- `docs/capabilities.md` coverage rises each phase; ROADMAP and handoff are updated at every checkpoint.

## Definition of done: "industry-grade agent" (set by the user, 27 Sep)
Jarvis 4 is finished only when all of these hold, measured on real voice sessions (a scoring script reads `logs/jarvis.log`), not just unit tests:

| Pillar | Bar |
|---|---|
| **Reliable** | ≥ 95% of requests end in the right result, with no hang or crash in a 2-hour session. It restarts itself if it dies and survives sleep/wake and mic changes. It never loses the user's clipboard or files. |
| **Fast** | Everyday commands (code layer) ≤ 0.5 s from end of speech to action. AI requests median ≤ 1.5 s. Vision requests ≤ 5 s and rare (< 5%). |
| **Accurate** | Misheard rate ≤ 5%. 0 unasked actions. 0 wrong-target clicks in a session. Risky actions always ask first. |
| **Coverage** | ≥ 90% of `docs/capabilities.md` works (live-checked). |
| **Frugal** | ≥ 80% of requests use no AI. The free tiers are never exhausted in a normal day. Backup switches are announced. |
| **Quality** | Every ability has unit tests plus a read-only live check (`tools/smoke.py`). Errors are logged with a cause. No personal data in the repo before any public release. |
