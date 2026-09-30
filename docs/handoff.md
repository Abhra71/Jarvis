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
- 162 tests pass: `.venv\Scripts\python -m unittest discover tests`. Everything is committed and pushed to `main`.

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

## Live notes from the user (30 Sep)
- **pw.live shows a "Student Feedback Form" pop-up on opening.** Jarvis must either close it or ask "Do you want to submit the feedback form, or shall I close it?". The user may say "close" (close it) or tell Jarvis what to fill in and submit. The batches page is `pw.live/study-v2/batches`; the batch cards have no accessible names, but OCR reads them.
- **PW mapped live (30 Sep), all in code, no AI** (`jarvis/skills/sites/pw.py`, abilities `pw_batch`, `pw_subject`, `pw_khazana`; code plans in `plan._pw_plan`):
  - batch = VICTORY 2027 (Class 10th ICSE) on `pw.live/study-v2/study` → All Classes → subject (two Chemistries: Sunil Sir 24 % and Sanya; the most-studied one opens, the reply names the other). 2.8–6.5 s.
  - Khazana = the batch's old recorded classes; the user studies Chemistry there from Sunil Sir ("Chemistry 2026"). "Khazana chemistry [year]" opens the Continue Learning course; a year that's said is matched exactly, else Khazana's search (`…/khazana-search?query=`). Its address is remembered in `data/pw.json`: 3 s.
  - Pop-ups (`jarvis/skills/popups.py`): forms (Student Feedback Form) → the agent asks "close it, or fill it in?" (answer routed first in `assistant._handle` via `brain.answer_agent`; "always close it" kept in `data/popups.json`); notices (Milestone Achieved streak) are closed on their own. Close button found through the page structure (PW's X is unnamed).
  - PW cards have no accessible names: clicked by OCR, after the text stops moving (`_find_steady`). OCR clicks never use the browser's own tab strip (`elements.page_top`).
- The user works on the PC in between: live tests only while they say it's free; stop at once when they say pause.

## Next, in the user's order
1. **Agent core**: design and task suite in `docs/agent-core.md`. Build it there.
2. **Remaining abilities** (Phase 3, started 30 Sep): done: dictation, switches (night light, Bluetooth, Wi-Fi, airplane mode, energy saver, captions, hotspot), brightness, Bluetooth connect, Gmail (draft in code, send only after a yes). Left: file-upload dialogs, voice coding (VS Code C++, BlueJ), game on/off (eFootball). **WhatsApp dropped by the user (30 Sep).**
3. **Better logging**, then the user's 2–3 day trial, then a log review and fixes.
4. **Self-healing**: corrections, visible names, per-app notes (site notes Jarvis writes for itself: search address, pop-ups, menus), **pattern learning** ("search X on Amazon" learned once works for any X; approved 30 Sep), daily self-review, "forget that".
5. **Chess** last.

- **Phase 6 speed note (30 Sep):** every ability goes to the AI with every request (27 now, ~1,900 tokens per action request). Send only the ones that fit the screen (code abilities only with an editor in front, PW only on PW…).

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
