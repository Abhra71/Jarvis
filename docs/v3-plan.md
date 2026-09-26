# Jarvis v3: "mastery on 3 sites, fast everywhere, fewest tokens"

## Context
The live test on 26 Sep (21:01–21:08) showed Jarvis is too slow and inaccurate to use:
- Screen tasks took 40–55 s.
- It did things nobody asked for: an extra chess move, and clicks after "No thanks".
- The user had to grab the mouse twice.

Root cause: every on-screen step is *screenshot → AI (4–6 s) → one click → screenshot again*, and each round is a chance to go off-script. Tuning that loop gave small gains. The architecture has to change.

**Goals (user's words: "150 fps on 3 sites, 70–80 fps elsewhere"):**
- **chess.com, YouTube, Physics Wallah (pw.live): flawless and near-instant.**
  - Built as dedicated site skills that need no AI (or one tiny text call).
  - Covers these user choices:
    - PW: open batch/subject, play lecture.
    - YouTube: search & play, player control.
    - Chess: voice moves, plus **autoplay mode** on chess.com.
- **Every other site/app: good and fast.** The screen is read as text (Windows UI Automation), not as pictures. Fast text models choose the action. Screenshots are a last resort.
- **Least tokens for the most output.**
  - Tiered routing: free rules → tiny text model → vision model only when needed.
  - Measured per provider (Gemini, Groq, Cerebras, Mistral, GitHub Models).
  - The user is creating the 3 new keys first and pastes them into `.env` themselves.

## Targets (measured, not guessed)
| Request type | Now | Target |
|---|---|---|
| Simple command (volume, open app/site) | 1–5 s | < 1.0 s after speech ends |
| Chess move by voice | 13–50 s | < 1.5 s, 100% correct square |
| YouTube "play X" / player control | 10–40 s | < 3 s / < 0.5 s |
| PW "open batch / play lecture" | n/a | < 4 s |
| "Click <named button>" on any site | 15–40 s | < 2.5 s |
| Unasked actions | 3 in 14 requests | 0 |
| Tokens per typical request | ~6–10k (with screenshots) | < 1.5k average |

## Phase 0: Measure first (small)
- Extend `tools/ai_eval.py` into an end-to-end benchmark:
  - time per stage (speech end → STT → AI → action → speech start);
  - tokens per request;
  - number of actions compared with what was asked.
- Add stage timings to the log lines in `jarvis/assistant.py` and `jarvis/usage.py`, so real sessions can be scored with one command (`tools/score_log.py`: per-request time, route, tokens, interventions).
- Record a baseline from the 20:15 and 21:01 sessions.

## Phase 1: Guardrails and quick fixes (small; lands first)
- Verification message in `jarvis/brain.py` `_ask_gemini`: replace "If more steps are needed, carry on" with "Report the result. Do nothing that wasn't asked."
- **Action budget in code:**
  - The router estimates how many actions the request needs ("click X" = 1, "move e2 e4" = 1 move).
  - Anything beyond the budget is blocked in `Skills.call` (`jarvis/skills/__init__.py`), like the existing confirmation gate.
- `_clean`: strip any leading "…thought" label ("atthought" leaked).
- Offline rules: "chess com" / "chess dot com" → chess.com (normalize in `nlu.py` / `SITES`).
- Validate tool args before running (a missing `y2` in `click_pair` crashed). Return "Missing y2" so the AI fixes it in the same round.

## Phase 2: Screen as text ("70–80 fps" everywhere)
- **Spike (day 1):** confirm Chrome exposes web-page buttons and links through UI Automation, and how fast it is.
  - `desktop._uia()` / `_browser_tabs()` already read Chrome tabs this way.
  - If page content isn't exposed, add `--force-renderer-accessibility` to how Jarvis launches Chrome (`skills/browser.py` `Browser.open`).
- New `desktop.page_elements()`:
  - A compact list of clickable and visible items in the front window: `[12] button "No thanks"`, `[13] link "Play Bots"`. Only on-screen items, capped at ~60.
  - Works for Chrome and desktop apps.
- New tool `click_element(id | name)`: exact click by accessibility element. The visible mouse glide stays (`mouse.click`).
- `look_at_screen` becomes a fallback, only when an element has no name (thumbnails, canvas).
- Result: most requests become one text-only call of about 500 tokens, which fast models answer in about 0.3–1 s.

## Phase 3: Site skills — the "150 fps" trio (`jarvis/skills/sites/`)
Each site is a module with its own offline phrase rules. A request on these sites never goes to the general AI loop unless it's truly open-ended.
- **YouTube (`youtube.py`):**
  - "play X": open the results URL, read the first real video (not ads/Shorts) via page elements, and click it.
  - Player control uses YouTube's own keys:
    - `k` pause
    - `j`/`l` back/forward 10 s
    - `Shift+>` faster
    - `f` fullscreen
    - `Shift+N` next
    - "skip ad" clicks the Skip button by name.
  - Zero AI tokens for control; at most one tiny call to pick a result.
- **chess.com (`chess.py`, uses `python-chess`):**
  - Find the board on screen locally: square colours via numpy on one screenshot, no AI. Detect orientation (playing white or black).
  - Read the game's move list (page text) to know the exact position.
  - Voice: "pawn e2 to e4", "e4", "knight f3", "castle", "takes on d5" → a legal move → one exact drag (`mouse.click_pair` drag). Illegal or ambiguous → "Which knight?"
  - Menus by voice (play bots, coach, new game, rematch, resign with confirmation) → `click_element`.
  - **Autoplay mode, only on command:** "auto mode on" / "auto mode off". It never switches on by itself when chess.com opens. When on, Jarvis plays the moves itself.
    - Engine: Stockfish, local and free, zero tokens.
    - **Only in games against bots, the coach, or analysis.** Refused in games against people: that breaks chess.com's fair-play rules and gets accounts banned. Detected by the page (`/play/computer`, coach) and stated plainly.
    - Spike: Windows Smart App Control may block the unsigned Stockfish .exe (it already blocked one sklearn DLL). If so, fall back to a pure-Python engine (weaker) and tell the user.
- **Physics Wallah (`pw.py`):**
  - "Open my <batch>, <subject>" and "play the latest / chapter N lecture / resume".
  - Uses a discovery session: the user opens PW in their logged-in profile while Jarvis records page structure (element names, URL patterns). No passwords are ever handled.
  - Batches and subjects are cached locally, so it's instant next time.

## Phase 4: AI routing and token economy (branch `wip/multi-provider-routing`, rebased onto main)
- Reuse what exists:
  - `jarvis/router.py` `classify()` (action/screen/chat/writing/live);
  - `jarvis/providers.py` `OpenAICompatProvider` / `NeedsVision` hand-over;
  - `[ai.routing]` / `[ai.providers.*]` in config.
  - Fix the 1 failing test first.
- **Tiers:**
  1. Rules and site skills (0 tokens).
  2. Fast text model for choosing actions from `page_elements` (Cerebras / Groq, ~0.3–1 s).
  3. Gemini vision only when the screen has no text handle.
  4. Backups.
- **Token savers:**
  - Send only the tools relevant to the routed type (not all 30).
  - A shorter system prompt per tier.
  - The profile and window lists only when relevant.
  - History keeps old turns as short summaries.
  - Screenshots are cropped to the active window when vision is needed.
  - The AI plans several actions in one response where safe.
- **Key onboarding** (the user pastes keys into `.env`; I only check they exist):
  - list each provider's models via its API;
  - check real free limits;
  - run the eval per model;
  - pick chains by measured accuracy × speed × quota.
- Status page (`jarvis/dashboard.py`): tokens and requests per provider per day, and the remaining free allowance.

## Phase 5: Voice pipeline latency
- Measure, then tune:
  - end-of-speech wait (0.8 s now);
  - Whisper time;
  - edge-tts time to first sound.
- Start speaking short confirmations while acting ("Opening…").
- Pre-record common replies, like the wake reply.

## Order and checkpoints (user decision: AI keys and provider testing FIRST)
1. **Keys and provider testing:**
   - The user creates Cerebras, Mistral and GitHub Models accounts and pastes the keys into `.env`. I guide step by step, only check that each key exists, and never read its value.
   - For each provider: list its models via the API, check the real free limits, and run `tools/ai_eval.py` (extended to OpenAI-compatible providers) for accuracy, speed and tokens.
   - Output: a comparison table and the chosen model per job (action / screen / chat / writing / live).
2. Phase 4 routing built on those measured results (branch `wip/multi-provider-routing`).
3. Phase 0 + Phase 1 (measure + guardrails) → user test.
4. Phase 2 spike (screen as text) → decides the Phase 2/3 method.
5. Chess skill → YouTube skill → PW skill (PW needs one discovery session with the user).
6. Phase 5 (voice latency).

Each step is committed and pushed separately, and ROADMAP.md is updated. Recommend starting a **new chat** after Phase 1; this plan file plus ROADMAP.md carry the context.

## Verification
- Unit tests (`python -m unittest discover tests`):
  - chess speech → move parsing;
  - board square maths;
  - action-budget blocking;
  - YouTube/PW phrase rules;
  - routing chains;
  - arg validation.
- `tools/ai_eval.py`: accuracy and median/slowest time per provider; must stay ≥ 17/18 on every chosen model.
- `tools/score_log.py` on a real voice session per phase, compared against the targets table. The user plays a bot game by voice plus autoplay, uses YouTube, and uses PW.
- Live checks on this PC (1920×1080, 125% scaling): the chess drag lands on the right square in both orientations; YouTube ad skip; PW lecture opens in the right profile.
