# Jarvis: start here

New chat? Say "continue Jarvis". Read only this page; open other docs when a task needs them.

## The goal
Run the **whole PC by voice**: sit back and do ~99% of computer work reliably, fast and accurately.
- The end bar is an **industry-grade agent**: see "Definition of done" in `docs/jarvis4-plan.md`.
- AI is a **luxury** (free Groq + Gemini only). Everyday work runs in code.
- Never: deleting, secret files (`.env`, keys), typing into VMware/Kali, sending or buying without a spoken yes.

## Where we are (30 Sep)
- Honest score:
  - abilities ~55% (`docs/capabilities.md`);
  - agent behaviour ~35% (the core is built but not yet proven live);
  - **the dream overall ~44%**.
- **The core gap:** Jarvis is a one-shot command runner, not an agent. It has no plan, no step checks, no recovery and no context.
- 143 tests pass: `.venv\Scripts\python -m unittest discover tests`. Everything is committed and pushed to `main`.

## Agent core (Phase 1): built, 30 Sep; Phase 2 (live runs on the real PC) is next
- **In `jarvis/agent/`:**
  - `context` (the screen as text, plus dialog / full screen / media playing);
  - `ocr` (Windows' offline OCR with positions + media status via one PowerShell helper that closes when idle);
  - `checks` (a check must change BECAUSE of the step; `auto_check` supplies code checks for keys and closing);
  - `plan` (JSON, validated; code plans incl. YouTube; remembered plans, only verified ones);
  - `run` (execute, verify, one repair that can't repeat the failed step, look_again, dialog guard, the yes before send, an honest "couldn't confirm" reply).
- **Lessons from the 29 Sep live log** (fixed on 30 Sep): it claimed "video resumed in fullscreen" after two unchecked keys; it checked for the button it had just clicked; "close it" with two Chrome windows counted as a failure; a repair repeated the failed click; it said it was "made by OpenAI".
- **Dry run on 30 Sep** (`tools/agent_suite.py`, plan only): plans in 0.6–1.5 s.
- **Still to check live:**
  - task 11 (PW deeper pages via look_again) once wrote a broken step;
  - WhatsApp search, Bluetooth and night light need the Phase 3 abilities.
- **Phase 2:** restart Jarvis, then `tools/agent_suite.py --live N` while the user is away from the PC; score it, fix it, repeat.
- **Permissions:** `.claude/settings.json` pre-approves edits, tests and git. Use only those command shapes; the user can't sit and approve prompts.

## Next, in the user's order
1. **Agent core**: design and task suite in `docs/agent-core.md`. Build it there.
2. **Remaining abilities**: dictation, Bluetooth/Wi-Fi/brightness/night light, WhatsApp desktop + Gmail, file-upload dialogs, voice coding (VS Code C++, BlueJ), game on/off (eFootball).
3. **Better logging**, then the user's 2–3 day trial, then a log review and fixes.
4. **Self-healing**: corrections, visible names, per-app notes, daily self-review, "forget that".
5. **Chess** last.

Report the % done at each phase end.

## How Jarvis works (request order)
`assistant._handle`:
1. site packs (`jarvis/skills/sites/`: YouTube);
2. abilities (`jarvis/abilities/`: code + phrases);
3. phrase memory (`data/learned.json`);
4. offline rules (`jarvis/nlu.py`: volume, apps, shortcuts…);
5. AI (`jarvis/brain.py`), which sorts requests by kind (`router.py`):
   - Groq first for text: gpt-oss-120b/20b, load-shared by tokens left;
   - Gemini for the screen and as fallback, with switches announced.

**Hands:**
- `skills/keys.py`: any shortcut, with safety;
- `skills/elements.py`: the screen as text, click by name;
- `skills/desktop.py`, `files.py`, `mouse.py` (glide 0.12 s).

**Hearing:**
- `stt.py` + `stt_worker.py`: small.en on the GPU **only during a conversation**. It starts on the wake word and exits after 120 s idle; the user's rule is **never continuous GPU use**.
- base.en on the CPU is the fallback.

**Adding an ability:** `@ability(name, summary, *phrase_regexes, value=hint)` in `jarvis/abilities/<area>.py`, imported at the bottom of `jarvis/abilities/__init__.py`.

## Working rules and lessons
- **The user:** vibe-codes, uses Jarvis **by voice only**, wants plain-language reports. Commit and push after each piece; restart Jarvis after changes (stop the `-m jarvis` processes, then run `start_jarvis.bat`).
- **Tests never touch the real screen:** they patch `load_api_key`, `elements.front_is_browser`, `sites.handle` and `abilities.handle`.
- **Bash heredocs mangle backslashes** (`\b` becomes a backspace, `\n` becomes a newline). Put regexes and `\n` in with the Edit/Write tools. Python `write_text` needs `newline="\n"` (the repo is LF).
- **Measure, don't guess:**
  - `tools/ai_eval.py` (AI accuracy/tokens);
  - `tools/stt_eval.py` (hearing);
  - `logs/jarvis.log` (real sessions).
- **History:** `docs/archive/` (v3 plan and handover), `ROADMAP.md` (everything done).
