# Jarvis roadmap

Running list of agreed work, done one at a time. Evidence comes from `logs/usage-*.json` and `logs/jarvis.log`.

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
- To do: measure Gemini speed settings

## Next / ideas
- Rotate the Gemini key (user)
- Follow-ups spoken while Jarvis is still talking get cut off (by design, it ignores its own voice).
  Idea: a very short tick when it's ready for the follow-up.
- An app that starts making sound after "mute" isn't muted
- Faster end-of-speech detection (0.8 s → 0.6 s), risky with mid-sentence pauses
