# Jarvis: start here

New chat? Say "continue Jarvis". Read only this page; open other docs when a task needs them.

## The goal
Run the **whole PC by voice**: sit back and do ~99% of computer work reliably, fast and accurately.
- The end bar is an **industry-grade agent**: see "Definition of done" in `docs/jarvis4-plan.md`.
- AI is a **luxury** (free Groq + Gemini only). Everyday work runs in code.
- Never: deleting, secret files (`.env`, keys), typing into VMware/Kali, sending or buying without a spoken yes.

## Where we are (1 Oct)
- Honest score: agent ~64%, **the dream overall ~60%**, but **daily-use feel ~30-35%** (the user: "I still won't
  use it as an app"). What's missing is trust: fewer confident wrong actions, human replies, speed on failures.
- ~250 tests pass: `.venv\Scripts\python -m unittest discover tests`. Everything is committed and pushed to `main`.
- Commit only when the tests pass (a failed run once got committed: check the last line says OK).

## Background batch (1 Oct, no screen used; all committed)
- Misheard app names: sound-alike match asks "Did you mean Claude?" (a yes opens it and is remembered); apps are
  checked by the name that really opened, 9 s to appear; letter-soup transcripts ignored (spellings kept).
- Speech (`agent/speech.py`): failures said like a person ("Chrome didn't close. What should I do?"); unchecked
  steps: "I pressed Windows Up, but I can't tell if it worked." `tools/reliability.py` knows the new phrasing.
- Planner diet: only the tools/abilities/rules a request or the front window needs (~25% fewer tokens); repairs
  see everything. New planner rules: "close this" in a browser = the tab; never invent text to type; never guess a
  site from one odd word; a statement isn't a request.
- Speed: `open_folder` ability (Downloads/Documents/Desktop/Pictures/Screenshots, instant); screenshots live in
  OneDrive "Screenshots 1". Timing from the logs: median ~2-3 s per request since agent mode; the slow ones are
  FAILURES (check waits + repair call), so reliability is the speed fix.
- `tools/replay.py [--ai N --skip M]`: every sentence the user ever said, routed offline (and N planned by Groq, dry
  run) -> `logs/replay.txt`. Its findings are fixed and locked in `tests/test_replay.py`.
- Fixes: "Open File Explorer" was a VS Code file; rules no longer take one part of a several-part sentence; names
  fixed everywhere (`nlu._MISHEARD`: Physics Voila, Kazana, d football); "maximize Claude" in code; "close this tab
  and close the chess tab as well" in code; an unreadable check drops the check, not the plan; the backup AI no
  longer redoes a half-done request; GPU helper stopped while loading no longer counts as broken; "Back on …"
  pop-ups for every fallback (`notify.fell_back/recovered`).
- **Phase 4 logging done:** `jarvis/tasklog.py`: one line per request in `logs/tasks-<date>.jsonl` + a `Task:` line
  in jarvis.log (result done/unconfirmed/asked/stuck/failed/stopped, why, time, AI calls, plan source, hearing).
  The status page (http://127.0.0.1:8765/) has "Today's review" with what went wrong.
- **Phase 5 started:** corrections (`jarvis/corrections.py`: "No, I meant Claude" redoes it and learns sound-alike
  mishearings, applied to what's heard; "forget that"); pattern learning in `PlanMemory` ("search {x} on amazon").
- BlueJ "create a new class called X" (`editors.new_class`, types only into BlueJ's own box, checks the class
  appears); the dialog guard lets typing into a dialog's own focused box through. **Both untested live.**
- Hearing check (synthetic voices, cloud): a coding-specific hint gains ~1 point only; not added (hint words can be
  "heard" in noise).

## Agent core (Phase 1, built 29-30 Sep)
- `jarvis/agent/`: `context` (screen as text, dialog/full screen/media of the FRONT app/pop-up), `ocr`, `checks`
  (a check must change BECAUSE of the step; URLs ignore www and slashes), `plan` (code plans: YouTube, windows,
  PW, Gmail; remembered plans; the planner plans ONLY the new request), `run` (verify, one repair, look_again,
  dialog guard, pop-up question, the yes before send with what's about to go said first).
- `tools/agent_suite.py --live N [--then "close it"]`; `tools/reliability.py N` (the 10x run, answers pop-ups
  with "close it", puts brightness/night light back).

## Hearing (30 Sep)
- Groq's hosted **Whisper large-v3** first (free: 2,000 a day, 20 a minute; ~0.5 s; the GPU never on). If it fails,
  the CPU base.en takes that sentence and the GPU small.en (one sentence, then its helper exits: 0 MB between
  sentences) is used for a minute. large-v3-turbo was tested and deleted (worse once music is ducked).
- Other apps are ducked to 12 % while Jarvis listens. Fallbacks are **pop-ups, never spoken** (`jarvis/notify.py`,
  tray icon notifications): hearing cloud/GPU/CPU, Gemini<->Groq, model switches.

## Phase 3 abilities (30 Sep)
- Switches via Quick Settings ids (`skills/quick.py`): night light, Bluetooth, Wi-Fi, airplane mode, energy saver,
  captions, hotspot; brightness via WMI; connect/disconnect Bluetooth devices via Settings (Rockerz 480 paired;
  success not yet seen live: the headphones were off).
- Dictation (`assistant._dictate`): types quietly, never Enter (Shift+Enter for "new line"), "scratch that".
- Gmail (`skills/sites/gmail.py`): draft in code (URL + To box contact lookup; the address said back belongs to the
  picked contact); `gmail_send` needs a spoken yes (`SENDING_ABILITIES`). The user's Drafts hold ~5 test drafts.
- Uploads (`abilities/upload.py`): file by name or "newest pdf", never a guess or a secrets file; clicks the page's
  upload button if needed. No resume file exists on this PC.
- Files: "open the file called X / with size N KB" in the open Explorer folder.
- Code editors (`skills/editors.py`): BlueJ (portable install in OneDrive Documents; its code is readable via
  TextPattern: every edit checked; Ctrl+L go to line, F8/F7 comment, Compile button, run = compile then
  right-click > "void main" > OK, output read from the terminal window; the class menu's "Delete" is never
  clicked) and VS Code (line read by copying; Ctrl+K Ctrl+C / Ctrl+K Ctrl+U).
- **Coding mode** (`jarvis/coding.py`, `assistant._code`): speech -> Java (BlueJ, braces on their own line) / C++
  (VS Code); common patterns in code, the rest one AI call (JSON, complete code, balanced, laid out); Scanner +
  import added when missing; "come out of the loop". Commands still work in coding mode.
- Games (`abilities/games.py`): start/close eFootball (normal close only; a crash on start is a pop-up). On 30 Sep
  eFootball crashed on its own at start (error 0xc0000005). Gaming mode = no follow-up listening.
- **WhatsApp dropped by the user.** Modes spec: memory `jarvis-modes`. Chess mode comes with Phase 7.

## Live notes from the user (30 Sep)
- **pw.live shows a "Student Feedback Form" pop-up on opening.** Jarvis must either close it or ask "Do you want to submit the feedback form, or shall I close it?". The user may say "close" (close it) or tell Jarvis what to fill in and submit. The batches page is `pw.live/study-v2/batches`; the batch cards have no accessible names, but OCR reads them.
- **PW mapped live (30 Sep), all in code, no AI** (`jarvis/skills/sites/pw.py`, abilities `pw_batch`, `pw_subject`, `pw_khazana`; code plans in `plan._pw_plan`):
  - batch = VICTORY 2027 (Class 10th ICSE) on `pw.live/study-v2/study` → All Classes → subject (two Chemistries: Sunil Sir 24 % and Sanya; the most-studied one opens, the reply names the other). 2.8–6.5 s.
  - Khazana = the batch's old recorded classes; the user studies Chemistry there from Sunil Sir ("Chemistry 2026"). "Khazana chemistry [year]" opens the Continue Learning course; a year that's said is matched exactly, else Khazana's search (`…/khazana-search?query=`). Its address is remembered in `data/pw.json`: 3 s.
  - Pop-ups (`jarvis/skills/popups.py`): forms (Student Feedback Form) → the agent asks "close it, or fill it in?" (answer routed first in `assistant._handle` via `brain.answer_agent`; "always close it" kept in `data/popups.json`); notices (Milestone Achieved streak) are closed on their own. Close button found through the page structure (PW's X is unnamed).
  - PW cards have no accessible names: clicked by OCR, after the text stops moving (`_find_steady`). OCR clicks never use the browser's own tab strip (`elements.page_top`).
- The user works on the PC in between: live tests only while they say it's free; stop at once when they say pause.

## Open items
- Live-test when the user says the PC is free: BlueJ new class, stricter coding mode, "Did you mean Claude?",
  "No, I meant …", "close this" in Chrome, the review page. The user's BlueJ class "test" has junk code from the old
  coding mode: offer to clean it (undo / delete all).

## Next, in the user's order
1. Live tests of the 1 Oct batch (above), then the user's 2–3 day trial; review with the status page and
   `logs/tasks-*.jsonl`, plus `tools/replay.py`.
2. **Self-healing** (Phase 5) rest: per-app/site notes Jarvis writes itself, daily self-review (corrections,
   patterns and "forget that" are built).
4. Hardening (Phase 6), chess (Phase 7, with chess mode), then the EXE.


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
