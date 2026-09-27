# Jarvis roadmap

Running list of agreed work, done one at a time. Evidence comes from `logs/usage-*.json` and `logs/jarvis.log`.

## Goal (set by the user, 27 Sep)
Within about a week, Jarvis should behave like a **proper everyday application** on the user's laptop, not a demo you play with for a few minutes. In order of importance:
1. **Reliable:** works every time and never gets stuck.
2. **Accurate:** never opens or clicks the wrong thing, and never does anything unasked.
3. **Fast:** simple commands in about 1 s; the three main sites near-instant.
4. **Smart use of AI:** the code does what it can; the AI is asked only for real judgement and gets exactly the context it needs.

Measure against this goal after every change, with real voice sessions and the logs.

**How Jarvis sees (agreed 27 Sep).** It tries these in order and uses the first that works:
1. Site pack code (0 AI).
2. The screen as text via UI Automation (0.05 s read, Groq text).
3. Reading pixels on the PC: the chess board finder, Windows OCR (no AI; measure first).
4. A cropped screenshot to Gemini, only when the request is about what something looks like, or 1–3 found nothing.

Results are checked by re-reading the text or the window title, not with a screenshot, where possible.

**Keyboard and cursor control (27 Sep), done:**
- [x] `press_key` takes any combination or chord ("ctrl+enter", "win+shift+s", "ctrl+k ctrl+s"), in `jarvis/skills/keys.py`.
  - Refused: Shift+Delete, Ctrl+Alt+Delete, Delete/Ctrl+D in File Explorer.
  - Needs a yes: Enter in chat apps, Win+L.
- [x] A shortcut sheet for the app in front (browser, YouTube, Explorer, VS Code, Office, Notepad), plus the Windows and text sheets when relevant. The prompt says "prefer a shortcut over the mouse".
- [x] Offline, instant, no AI: new/close/reopen/next tab, back/forward, reload, zoom, copy/paste/cut/undo/redo, select all, save, switch window, show desktop, screenshot snip, clipboard history, and "press control shift T"-style commands.
- [x] Text longer than 30 characters is pasted in one go; the clipboard is restored (typed instead if it holds an image or files).
- [x] Cursor glide 0.12 s (was 0.35 s), shorter pauses around clicks.

**Order from here (user, 27 Sep):** PW pack → the fixes from the voice test → the agent-feel phase → chess last. Chess is "a fascinating extra", not needed now.

**Planned after the site packs: the "agent feel" phase (~2–3 h).** The user wants Jarvis to feel like a human helper, not "look around, then act":
- Constant awareness: a background text view of the front window, refreshed when the window or page changes.
- Plan, then act: the AI returns several steps at once; code runs them with text checks and asks the AI again only when something is unexpected.
- Speak while acting ("Opening YouTube…").
- Recover once from a click that changed nothing, then ask.
- Use context (the screen, the last request) before asking "what do you mean?".
- Then: better hearing (Whisper on the GPU, the user's vocabulary) and remembered preferences.

**Later, not now:** a public GitHub release that anyone can install on their PC with terminal commands. Before that:
- scrub the personal data from the files and the git history (the repo stays private until then);
- add an installer / setup script;
- add first-run setup for keys and Chrome profiles;
- write docs.

## Done

### 1. Speed (26 Sep)
Found: screen tasks took 11–42 s although each Gemini call took ~2 s. Too many round trips, plus the newest
Gemini Lite models hang on ~half of requests.
- [x] Single-step actions finish on the action's own result (1 AI round trip instead of 2–3)
- [x] find_on_page (Ctrl+F) instead of scroll → screenshot loops
- [x] Smaller screenshots (83 KB → 65 KB)
- [x] Trimmed tools + prompt: 3,898 → 2,773 tokens per request (merged volume/timer tools, dropped list_windows)
- [x] Hedge slow Gemini requests to `gemini-3.1-flash-lite` (never hung in testing) after 2.5 s
- [x] When Gemini stalls, ask Groq first for 3 minutes
- [x] Daily Gemini limits (e.g. 20/day on full Flash) park that model for an hour
- [ ] Not done: faster end-of-speech (0.8 s → 0.6 s). Risky, since you pause mid-sentence; revisit after the chimes.
- Result: simple actions 2–7 s (was 5–18 s); "play the second video" 13 s with 1 screenshot (was 12–25 s).
  Most remaining time is Gemini's own speed on the free tier today.

### 2a. Chimes (26 Sep)
- [x] "Hey Jarvis" → spoken "Yes, my lord?" (pre-recorded at startup, plays instantly); "Jarvis online" at startup
- [x] Soft falling chime when it stops listening and goes back to waiting for "Hey Jarvis"
- [x] Main AI switched to gemini-3.1-flash-lite after the accuracy test (16/16, never hung)
- [x] Bug: "Mute" muted the whole PC, so "Yes, my lord?" and the chimes went silent too. Now "mute" silences
      every other app and keeps Jarvis audible; if the PC is muted by hand, Jarvis does the same before speaking.
      Known gap: an app that starts making sound *after* "mute" isn't muted.

### 2b. Clear states + stop (26 Sep)
- [x] Say "Hey Jarvis" while it's busy → it stops at the next step, says "Stopped.", then "Yes, my lord?"
      (wake-word based, so background video/music can't interrupt it). Replaces the "one moment" tone idea.
- [x] Wake reply and back-to-sleep chime are written to the log

### 3. Accuracy (26 Sep)
- [x] Do only what was asked; say exactly what it opened (prompt rules)
- [x] Code check: after a click, it can't report success without a screenshot of the result
- [x] Answer general-knowledge questions directly; search only when asked or for live data
- [x] Speech recogniser primed with installed app names; "cloud" alias for the Claude app;
      failed app lookups suggest the closest installed names

### 4. Bluetooth headphones (26 Sep)
- [x] Voice plays via Windows' Sound Mapper = always the current default output (headphones when connected)
- [x] Mic never uses a Bluetooth "Hands-Free" headset, so headphones stay in high-quality music mode
- Not yet tried with the Rockerz 480 connected

### 5. Safety + housekeeping (26 Sep)
- [x] Hard, code-level confirmation before send/post/buy/delete-type clicks and Enter in chat/mail apps
- [x] Git repository, pushed to https://github.com/Abhra71/Jarvis

### 6. Fixes from the headphone session (26 Sep, 19:21–19:37)
- [x] Chrome profile nicknames: "main"/"personal", "AI", "backup" (3 profiles are all named "Abhra")
- [x] Never speak garbled AI replies ("hob", "thought", broken characters); garbled answers get one retry
- [x] Code-enforced: look at the screen before every click (a click landed on Gmail; "1,2,4" = 3 blind clicks)
- [x] Codes/OTPs/passwords/card numbers are replaced with "(hidden)" before speaking
- [x] Typing is checked on screen before claiming success; "cut" key; close_all windows
- [x] Questions answered via search are read from the results, not from memory
- [x] Backup Gemini request after 5 s (was 2.5 s: fired 18/29 times, won once)
- [x] Speech-to-text: command hints + beam size 3 (no measured cost; real benefit unproven)
- Open question: did Jarvis's voice come through the headphones, and did music keep full quality?

### 7. Fixes from the chess session (26 Sep, 20:15–20:24)
- [x] Freeze: sound playback and voice download have time limits (Jarvis went silent for 6 minutes)
- [x] Screen requests send a screenshot with the first AI request (one round trip less)
- [x] click_pair: a chess move / drag is one step from one look, not look-click-look-click
- [x] The screen check runs after the *last* click (up to 2), so moves aren't claimed unseen
- [x] Replies say the outcome ("Moved the pawn to f4"), not page titles
- [x] Speech: noise dropped (Whisper "heard" its own hint: "Open Chrome." ×4); repeated sentences removed;
      chess words in the hints; shaky transcripts are marked so the AI asks instead of guessing
- [x] "Open chess" opens chess.com; "play …" unmutes first (Aari Aari played silently after an old "mute")
- Tip: say moves as "pawn f2 to f4" (letter first); "2F to 4F" confuses it
- [x] "Close the chess tab" closes the tab with that name (it used to close the front tab)
- [x] Measured (tools/ai_eval.py, 18 requests): default thinking 18/18, median 1.3 s; "minimal" thinking
      17/18, median 1.8 s, and it opened Chrome for "1, 2, 4". Kept default. Smaller screenshots (800px)
      were a bit faster but aimed less precisely, so kept 1100px.

## v3 (plan: docs/v3-plan.md, handover: docs/v3-handoff.md)
### Step 1. Guardrails (26 Sep)
- [x] Action budget in code: each request may only take as many clicks/drags/typing/key presses as it
      asked for ("click No thanks" = 1, "pawn e2 to e4" = 1, "type X" = 2, open-ended = 3 per part);
      anything beyond is refused in `Skills.call` (the extra chess move, the clicks after "No thanks")
- [x] The after-click screen check says "Report the result. Do nothing that wasn't asked." (was "carry on")
- [x] Tool args checked before running: missing/garbled/off-screen values come back as "Not done: missing
      y2…" so the AI fixes them in the same round, instead of crashing
- [x] Leaked "…thought" labels ("atthought") stripped from replies
- [x] "chess dot com" / "chess.com" / "wikipedia dot org" / "physics wallah" open the site offline

### Steps 2–3. Smaller requests + routing (26 Sep)
- [x] `jarvis/router.py` sorts each request: chat / live / action / screen / files
- [x] Only that kind's tools are sent (chat: 1 tool, commands: ~10 instead of 30), plus `more_tools` so the
      AI can ask for a missing group; the prompt is built from sections (profiles/windows only when relevant)
- [x] Past turns are remembered as plain words, not tool calls and screenshots
- [x] Groq (gpt-oss-120b → 20b) goes first for commands and questions; Gemini (3.5 → 3.1 Flash-Lite) first for
      the screen and live facts, and the fallback. When Groq needs to see, the request is handed to Gemini
      with the steps already done and the screenshot, so nothing is repeated
- [x] Measured: Groq 16/16 at ~1,070 tokens (was 15/16 at 2,200); Gemini 11/12 screen clicks at 3,360 (was
      10/12 at 4,400). See docs/ai-provider-report.md

### Step 4. Click by name (26 Sep)
- [x] `page_elements`: the front window's named buttons/links/fields as a numbered list, read with Windows UI
      Automation in ~0.05-0.2 s (in Chrome: only the web page)
- [x] `click_element(id | name)`: re-reads the screen, finds the item, checks it (a "Send"/"Resign" item still
      needs your yes, even by id; counts in the action budget) and glides the mouse to its centre
- [x] Screen requests with named items go to Groq as text, no screenshot; boards/pictures still go to Gemini.
      "Open chemistry" with the PW page in front clicks the Chemistry link
- [x] Measured: Groq 12/12 right item in 0.8 s (screenshot clicking was 10-11/12 in 1.5-2.5 s)

### Step 5b. YouTube pack (27 Sep) — `jarvis/skills/sites/youtube.py`, no AI
- [x] "Play X (on YouTube)": opens the results and plays the first real video. A real video's title link ends with
      its length; ads, Shorts, channels and live streams don't. 4 s including page load (was 10-40 s)
- [x] Player by voice with YouTube in front: play/pause (and "it's already paused"), skip ad, next, mute/unmute
      the video, full screen, theatre, subtitles: 0.03-0.1 s, buttons pressed via UI Automation (no mouse, no focus
      trouble); forward/back N seconds, faster/slower via YouTube's keys
- [x] "Play the second video", "search X" on YouTube; anything else goes to the AI as before
- [x] `.env` / key / password files can't be read or moved, and no screenshots while one is in front

### Still to do
- [ ] Step 5: site packs (chess → YouTube → PW)
- [ ] Step 6: Whisper on the GPU

## Next / ideas
- Rotate the Gemini key (user)
- Follow-ups spoken while Jarvis is still talking get cut off (by design, it ignores its own voice).
  Idea: a very short tick when it's ready for the follow-up.
- An app that starts making sound after "mute" isn't muted
- Faster end-of-speech detection (0.8 s → 0.6 s), risky with mid-sentence pauses
