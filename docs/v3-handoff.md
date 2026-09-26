# Jarvis v3: handover (26 Sep 2026)

Start here in a new chat: "start the Jarvis v3 build". Read this file, [v3-plan.md](v3-plan.md) and [ai-provider-report.md](ai-provider-report.md).

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
