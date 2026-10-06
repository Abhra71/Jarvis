# Jarvis: start here

> **5 Oct: REWRITE decided.** The trial showed ~35% of real requests worked; the pattern-based foundation is wrong.
> Read `docs/rewrite-plan.md` first (goal, targets, new foundation, phases). Keys: `docs/api-keys-guide.md`.
> Everything below is history of the old foundation.
>
> **Phase 0 status (5 Oct, in progress):**
> - Gold set: `data/gold/understand.jsonl` (537 real sentences, hand-labelled with the screen; local only) and
>   `data/gold/coding.jsonl` (`tools/gold_coding.py`: 25 of the user's coding sentences + 93 student-style).
> - AI pipeline: `jarvis/llm/` (`providers.py` one caller for Groq/Gemini/NVIDIA/Cloudflare; `understand.py` the
>   brain's format; `coder.py` the coding expert with one compile-repair; `router.py` chains + live budgets).
> - Benchmarks: `tools/bench.py understand --all`, `tools/bench_coding.py --repair --all`; results in `data/bench/`
>   (re-graded on report); `tools/assign.py --write` makes `data/pipeline.json` + `docs/model-benchmark.md`.
> - Keys: Groq, Gemini, NVIDIA, Cloudflare work (account id in config.toml). Mistral skipped (payment).
> - Findings so far: Groq qwen3.8-27b and Gemini 3.5 Flash-Lite lead understanding; Gemini 3.5/3.8 Flash and Gemma
>   were mostly unavailable (overloaded free tier); Llama 3.3 70B acts wrongly ~22%. Groq's free 200K tokens/day
>   per model is the binding limit (~1,400 tokens per understanding call): the prompt must get smaller.
> - Prompt-size test (Gemini 3.5 Flash-Lite, same 167 sentences): full prompt 85% right; half-size prompt 77%
>   (noise recognised 19/22 -> 11/22, coding 24/28 -> 19/28). Keep the full one; try a middle version that keeps the
>   noise and coding guidance, and use it only if it scores the same.
>
> **6 Oct session (user away 1.5 h, PC given):**
> - Chains chosen by `tools/assign.py` (`data/pipeline.json`, `docs/model-benchmark.md`): understand = Groq qwen3.8
>   (90%, 0.6 s) -> Gemini 3.5 Flash-Lite (85%, 1.0 s) -> NVIDIA Nemotron -> Cloudflare gpt-oss; code = Gemini 3.5
>   Flash-Lite (94%, 1.6 s) -> Nemotron (93%, 5.9 s) -> Groq gpt-oss-120b (92%, 0.8 s) -> gpt-oss-20b. 0% of edits
>   failed to compile (one repair try). Cloudflare's 10,000 neurons/day run out fast: understanding only, a little.
> - Hands: right-click + pop-up menus in any app (`elements.open_menu/choose`, tools `right_click`,
>   `choose_menu_item`); 'kind' picks between same-named items. Live in Explorer: menu read in 0.95 s.
> - Executor `jarvis/llm/act.py`: 323/337 real steps map to valid tool calls (gaps: chess, bare mouse moves).
> - New brain `jarvis/llm/brain2.py` (understand -> act -> reply; noise silent; yes before delete), live-tested
>   (open Downloads, noise ignored, close window). NOT switched on in the assistant yet.
> - BlueJ can't be started from Claude's session (Windows Application Control blocks it; not bypassed): the
>   BlueJ delete/open live checks need BlueJ opened by the user. BlueJ's delete item is assumed "Remove": verify.
> - Next: Qwen 3.8 coding run; wire NewBrain into `assistant._handle` behind a switch; Phase 1 live checks.

New chat? Say "continue Jarvis". Read only this page; open other docs when a task needs them.

## The goal
Run the **whole PC by voice**: sit back and do ~99% of computer work reliably, fast and accurately.
- The end bar is an **industry-grade agent**: see "Definition of done" in `docs/jarvis4-plan.md`.
- AI is a **luxury** (free Groq + Gemini only). Everyday work runs in code.
- Never: deleting, secret files (`.env`, keys), typing into VMware/Kali, sending or buying without a spoken yes.

## Where we are (3 Oct, after Blocks 1-3)
- Block 1 (trust) done and live-tested: background talk ignored, Share needs a yes, 8 live bugs fixed, the 20-task
  reliability run at 99%.
- Block 2 (coding mode) done and live-tested in scratch BlueJ/VS Code files.
- Block 3 (speed) done. **Next: Block 4, the user's 2-3 day trial** ("continue Jarvis: block 4" after it, to review).

## Where we were (1 Oct)
- Honest score: agent ~64%, **the dream overall ~60%**, but **daily-use feel ~30-35%** (the user: "I still won't
  use it as an app"). What's missing is trust: fewer confident wrong actions, human replies, speed on failures.
- ~310 tests pass (~45 s): `.venv\Scripts\python -m unittest discover tests`. Everything is committed and pushed to `main`.
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

## The plan from 3 Oct: blocks (one new chat per block; say "continue Jarvis: block N")
Full plan: ~/.claude/plans/yea-agent-industry-grade-adaptive-lampson.md. The user allows full PC use when idle.
**Block 1: Trust first. DONE 3 Oct** (all committed):
- `jarvis/addressed.py`: speech not said to Jarvis is ignored, silently, and logged as `ignored` (two in a row =
  back to sleep): not English (words that are 3+ pieces of Whisper's vocabulary; the hint's names count as words),
  lists of scraps, the same scrap repeated, filler only, and very unsure (< -1.2) with no request. A command word
  starting a sentence always keeps it. Checked on all 365 heard lines with their real confidence: only noise
  dropped. Tests: `tests/test_addressed.py` (1 Oct Hindi talk, 3 Oct lofi song that woke Jarvis at score 0.94).
- Share/Forward/Invite/Accept/Agree/Approve/Unsubscribe clicks need a yes. Device/switch/game/BlueJ-new-class
  abilities' "Not done" is the answer (`abilities.FINAL`), never handed to the AI; "Not done:" isn't spoken.
- Live-tested and fixed: `open_folder` never got its folder (always went to the AI; now 0.2 s, brought to the
  front); "close it" right after opening a folder closes that window in code (`desktop.just_opened`; the AI had
  closed a PW tab); Chrome's "Pin Chrome" infobar isn't a dialog; BlueJ's New Class box is an owned window (now
  seen; new class 2.2 s live in the scratch project `scratchpad/JarvisScratch`); "open Chrome" = main profile
  (plain Chrome opened "Who's using Chrome?", which is never taken for a page); PW opens Chrome itself; PW's streak
  notice is closed during waits and found before the feedback form under it; the guard's notes to the AI are never
  read out; the review page says reasons in plain words.
- Live OK: Did-you-mean, "No, I meant", "forget that", close this tab (+ the chess tab), folders, BlueJ new
  class/open/compile, review page.
- `tools/reliability.py` has 20 tasks (with expected answers: a wrong action can sound like success). Stop the
  voice Jarvis while it runs (YouTube music wakes it). RESULT 3 Oct: **99/100 (99%)** over 5 rounds; the
  one miss was the test reusing a class name (fixed: it picks an unused one). Slow ones for Block 3: "close all
  YouTube tabs" 7.5 s, PW batch / Khazana ~7 s, YouTube play ~6 s.
- Not done in Block 1: the user's BlueJ class "test" junk code (offer to clean it in Block 2); "Open Calculus"
  still goes to the AI (Did-you-mean didn't catch it).

**Block 2: Controllable coding mode. DONE 3 Oct** (all committed; live in BlueJ + VS Code scratch files):
- `jarvis/codeedit.py`: the whole file is edited by its structure (blocks found by matching braces, strings and
  comments ignored). Statements go inside a method (cursor's, else Jarvis's last, else main, made if missing);
  methods inside the class (C++: before main); a class/main that exists is never made again. wrap/move into main,
  into a loop/if, into a new method (extract + call); rename; delete lines; C++ `#include`s and `using namespace std`
  added when needed. Laid out in the file's own style (BlueJ braces on their own line).
- `jarvis/codecheck.py`: javac (from BlueJ's jdk) / g++ (MSYS2) on a hidden copy, ~0.6-1 s. Moves, wraps, renames
  and AI code are refused if they add a new error ("That would break the code (count isn't known there)…"); "fix
  the errors" fixes a missing semicolon/brace in code, else the AI offers a small fix (yes first).
- `jarvis/codemode.py`: the fixed command set (see `docs/coding-cheatsheet.html`, "show me the coding commands");
  short pattern lines go in at once and are said back ("Added a for loop, i from 1 to n"); AI code is offered
  first (pop-up) and written after a yes; undo/redo from Jarvis's own record (refused if the user edited since);
  noise/unclear speech writes nothing (quiet pop-up); questions and normal requests go the normal way.
- Editors: whole-file read/write (`Editor.read/write/place/insert_below`). BlueJ: UIA text + caret, cursor moved by
  arrows (~0.1 s). VS Code: code read by copy (clipboard restored), caret from the status bar "Ln x, Col y", each
  paste waited for. Speed live: BlueJ ~0.6-1 s per line, VS Code ~1.2-1.6 s (Block 3 can cut VS Code).
- Fixed on the way: bringing a window that's already in front tapped Alt and opened VS Code's menu.
- Tests: `tests/test_codeedit.py`, `test_codecheck.py` (real compilers), `test_codemode.py` (the 3 Oct session and
  every 30 Sep sentence). The suite now takes ~45 s (compiler tests).
- Open: offer to clean the user's own BlueJ class "test" (old junk code); not touched.

**Block 3: Speed. DONE 3 Oct** (targets: code ≤1.5 s, AI ≤4 s median; met by the task logs: code ~1.5 s, AI ~1.9 s):
- Tabs read from the browser's own tab strip only (`desktop._tab_strip`, remembered per window): closing YouTube
  tabs 7.5 s -> ~1 s (the page's "All / For you" chips no longer count as tabs).
- PW subjects and Khazana courses opened once are remembered in `data/pw.json` and opened straight by address.
- In code now (were AI, 2-9 s): plain searches ("search X on youtube/amazon", `_SEARCH_CONTEXT` keeps "search it
  here" with the AI), "open main profile in Chrome", "close this" with an app in front (`plan._CLOSE_APP`;
  editors/terminals/Notepad/Office/Claude still go to the AI).
- Keys: 20 ms pause (was 50); repeated arrows 10 ms in one call. VS Code coding 1.2-1.6 s -> 0.5-0.8 s per line
  (clipboard restored as soon as the paste shows; its cursor after reading is known: its status bar lags ~0.1 s).
- Also: arrays in coding mode ("create a 2D int array called arr with 3 rows and 4 columns"; no size = Jarvis
  asks), navigation ("go to the end of the file", "next line", "go down 3 lines", "read line 12").
- YouTube play stays ~4-5 s: page load and the video starting, checked.
- Reliability run after Block 3: **100/100**. Medians: close all YouTube tabs 7.5 -> 0.5 s, PW batch chemistry
  7.8 -> 1.4 s, Khazana 6.9 -> 4.2 s, snap 5.3 -> 0.5 s, newest pdf 1.3 -> 0.8 s. "What's on my screen?" ~6 s
  (Gemini vision; the only slow one left).

**Release order (the user, 3 Oct; memory `jarvis-release-order`):** Block 4 trial → fixes → Blocks 5-7 → only when
the feel is near 100%: the full beta (wizard, own keys + guide, terminal install, consent, scrubbed reports) →
tested on the user's second laptop → then friends. Plan: ~/.claude/plans/try-again-tidy-creek.md.
**Beta, personalization and self-learning spec (the user, 3 Oct): `docs/beta-plan.md`** (GUI wizard after a
terminal install, the welcome survey, learning a new person, recipes: AI once then code). Wake word is now "Hi Jarvis".
**Going public (3 Oct):** after the trial Jarvis becomes a product for everyone; flagships = self-learning,
coding mode, chess mode; repo refresh just before the beta (`docs/beta-plan.md` section 7).
**Logs before the trial were deleted (3 Oct, the user's ask);** every sentence heard is kept in
`data/heard-history.json` (not in git; read by `tools/replay.py` and `tests/test_addressed.py`). Live-test scratch
files live in `scratch/` (not in git): the BlueJ project JarvisScratch, scratch.cpp, `live.py` (ONLY:/FOCUS: guards).
**Block 4: Trial** (2–3 days) and review. **Block 5:** Phase 5 rest (site notes, daily self-review).
**Block 6:** Hardening. **Block 7:** Chess mode (vision board, voice moves, a mode switch). **Block 8:** the beta,
then the EXE (see the release order).

Also open: the user's BlueJ class "test" has junk code from the old coding mode; offer to clean it.

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
