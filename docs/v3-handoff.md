# Jarvis v3: handover (26 Sep 2026)

Start here in a new chat: "continue the Jarvis v3 build". Read this file, [v3-plan.md](v3-plan.md) and [ai-provider-report.md](ai-provider-report.md).

## Progress (updated 27 Sep, end of session 1)
**Done, committed and pushed** (ROADMAP.md has details, the report has measurements):
- **Step 1, guardrails** (`9d4d728`): action budget in `Skills.call`, arg checks, "carry on" removed, "thought" leak, spoken addresses.
- **Steps 2–3, smaller requests + routing** (`182facc`):
  - `jarvis/router.py` sorts requests by kind and picks the tool groups; `more_tools` lets the AI ask for more.
  - The prompt is built from sections.
  - Groq goes first for text, Gemini for the screen and as fallback, with a hand-over (`NeedsVision`).
  - Groq 16/16 at ~1,070 tokens.
- **Step 4, click by name** (`7dec1eb`): `jarvis/skills/elements.py` (`page_elements`, `click_element`). Named screen items go to Groq as text. Groq 12/12 in 0.8 s.
- 72 unit tests pass: `.venv\Scripts\python -m unittest discover tests`.

**Not started / next: step 5a, chess pack** (`jarvis/skills/sites/chess.py`):
- `python-chess` is installed in `.venv` and listed in requirements.txt.
- **Move list via UI Automation** (read 27 Sep from a live coach game): the page Document has Text nodes in order.
  - They read: `'1.' 'f4' 'e5' '2.' 'c4' 'Ä' 'e7'`.
  - **Pieces are icon-font glyphs in their own Text node**: 'Ä' + 'e7' = Be7. Map the glyphs to K/Q/R/B/N; so far only 'Ä' = bishop is known, so read the others from a game.
  - The page also shows the opponent ("Coach Nadia (100)"), the title "Play Chess with a Virtual Coach" (use it for the autoplay check: bots/coach only), and the buttons Resign / Show Hint / Undo.
- **Board:**
  - Port `tools/prototypes/find_board.py`.
  - Tighten the ~8 px offset: refine each edge with the 7 inner grid lines.
  - Orientation: compare which squares look occupied with the position from the move list, in both orientations (sturdier than piece brightness).
  - Test on the synthetic boards in `tools/eval_screens.py` (both orientations).
- **Voice moves:**
  - Parse "pawn e2 to e4 / e4 / knight f3 / castle / takes on d5" into constraints, then filter python-chess's legal moves.
  - One match: drag it. Several: "Which knight?".
  - Promotion defaults to queen.
  - Verify by re-reading the move list.
- **Hook:** add `jarvis/skills/sites/__init__.py` `handle(text, skills)`, called in `assistant._handle` before the offline rules when the site is in front. Usage route: `site:chess`.
- **Autoplay:** only on "auto mode on", only vs bots or coach. Use Stockfish if its path is configured, else a small Python engine; say which.

**Then:** 5b YouTube, 5c PW, 6 Whisper on the GPU (estimate ~3 h of build in total).

**Ask the user at the end, in one go:**
- the PW discovery session (logged in);
- permission to download Stockfish (an .exe; Smart App Control may block it);
- a voice test of the three sites;
- rotating the Gemini key.

**Order the user chose for the next session:** site packs first (YouTube, chess, PW), then the fixes below. Exception, recommended to the user: the `.env` secrets block is a 5-minute fix and should go in right away.

**Live voice test 27 Sep 00:18–00:38 (68 requests; fix after the site packs):**
- Results: 43 handled by Groq (median 1.1 s), 17 by Gemini (median 6.5 s, slowest 26 s), 6 by offline rules.
  Click by name worked well (Maps directions, "Manage", "Trust", "Trust Folder & Continue").
- **Secrets:** Jarvis ran `read_text_file` on `.env`, so the API keys went to the AI. Block `.env`, key and credential files in `files.read_text` / `find_files`.
- **Groq rate limits:** 429 errors on 14 turns, then fell back to Gemini (slow).
  - Groq counts `max_tokens` (1024) against the 8k/min limit up front: cut it to ~300.
  - The item list adds ~700 tokens: cap it and skip it for plain commands.
- **Groq 400 errors** ("failed to parse tool call JSON", tried to call a tool named `keys`, `window` args didn't match the schema) are treated as an outage. Retry once, telling the model what was wrong, before switching provider.
- **Budget gaps:**
  - "Select the lines 7, 8, and 9" was split at the commas, giving a budget of 7.
  - Launches aren't counted: "Open notifications" opened Action Center twice.
  - It typed its own question "What should I type?" into Claude's search bar.
- **Offline-rule bug:** "…only Google and Groq AI services are used" matched `ai_status` (`nlu.py`: ai … used) and read out the status.
- **Keys:** no combinations like Ctrl+Enter, and no general shortcuts. Add `press_keys("ctrl+enter")` with a safe list.
- **Text editing** (VS Code `.env`) was weak: 26 s, several attempts, an error dialog. Use editor keys (Ctrl+G line, Shift+Down select) instead of drags.
- **Hearing:** 17/68 marked unsure. Misheard: Physics Wallah → "Physics, Voila", Groq → "Brock"/"Grok", tab → "deck", Claude → "cloud". Add hint words; step 6 (Whisper on the GPU) matters.
- "Close … Claude": the `window` tool couldn't find the Claude app window (4 tries).

**Lessons for the next session:**
- Don't put regexes or `\n` in bash heredoc Python scripts: backslashes got mangled (`\b` became a backspace). Use the Edit tool.
- Python `write_text` on Windows writes CRLF: pass `newline="\n"`. The repo is LF.
- Tests patch `load_api_key` and `elements.front_is_browser` in `setUpModule`, so the real `.env` keys and the real front window never leak into tests.

## Decisions made with the user
- **AI providers: Groq + Gemini only.** Everything else is dropped (Mistral, NVIDIA, OpenRouter, Cerebras, GitHub Models, SambaNova, DeepSeek).
  - Groq (gpt-oss-120b, then gpt-oss-20b): commands and questions, ~1 s. Limits per model: 8k tokens/min, 200k tokens/day.
  - Gemini 3.5 Flash-Lite (then 3.1 Flash-Lite): anything that needs the screen, and the big fallback (~1,000–1,500 requests/day).
- **Mindset:** the AI decides, the code does and checks.
  - Click by element name (Windows UI Automation), not pixel guesses. Screenshots only when nothing else works.
  - Send only the tools each request type needs; target < 1,500 tokens per request.
- **Priority sites, near-flawless:** chess.com, YouTube, Physics Wallah (pw.live).
  - Layer A: every common action in code (0 tokens).
  - Layer B: the AI plus a site cheat-sheet plus the page's element list.
  - Logs promote frequent Layer B actions into Layer A.
- **Chess autoplay only on command** ("auto mode on"), and only against bots or the coach (fair play).
- **No local LLM for now.** Try Whisper on the RTX 2050 (4 GB) for better hearing.

## Proof check results (read-only, on the user's PC)
- **UI Automation** reads page buttons, links and text in 0.03–0.16 s.
  - **YouTube:** player (Play (k), Mute (m), seek slider, Settings, Full screen (f), Theatre, Autoplay, Next), video titles, menus.
  - **PW:** menu (Study, Batches, Test Series, My Test, …), "YOUR BATCH: VICTORY 2027 (Class 10th ICSE)", All Classes, All Tests, My Doubts.
  - **chess.com:** Resign, Show Hint, Undo, pop-up buttons ("No, thank you"), and the **move list as text**.
  - **Chrome must be in front,** or the page tree is empty. Right after a page load the tree can come back garbled; read it again.
- **The chess.com board is NOT exposed** (drawn). `tools/prototypes/find_board.py` finds it with numpy in ~1.9 s:
  - It gets the square size from the grid lines, then runs a checker-pattern search refined pixel by pixel.
  - On the wooden theme, all 6 test squares landed correctly, about 8 px off-centre (to tighten).
  - Orientation comes from the piece brightness.
  - Cache the board per game.
- Other prototypes: `tools/prototypes/read_chrome_window.py` and `read_chrome_tabs.py`.

## Build order
1. **Guardrails:**
   - An action budget in `Skills.call`.
   - Remove "If more steps are needed, carry on" from the verification message in `brain.py`.
   - Catch "…thought" leaks in `_clean`.
   - Map "chess com" / "chess dot com" to chess.com.
   - Validate tool args, or replace `click_pair`'s six numbers with squares or element names.
2. **Smaller requests:** a tool subset per request type, and a shorter prompt.
3. **Routing:** Groq first for text, Gemini for the screen and as fallback. Only reuse small parts of branch `wip/multi-provider-routing`.
4. **Click by name:** `desktop.page_elements()` plus a `click_element` tool.
5. **Site packs** in `jarvis/skills/sites/`: chess (python-chess, board finder, voice moves, menus, autoplay with Stockfish if Smart App Control allows it), then YouTube, then PW (read inside the batch first).
6. **Whisper on the GPU:** compare accuracy and speed.
7. Measure each step with `tools/ai_eval.py` and real voice sessions.

## Open items
- Rotate the Gemini key (it was pasted in chat once). Mistral's key was also pasted, but Mistral is dropped.
- The repo must stay private until the personal data is scrubbed from files and git history.
