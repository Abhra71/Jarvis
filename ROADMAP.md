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

## Next

### 2b. Clear states
- [ ] Soft "one moment" tone if the user speaks while Jarvis is busy
- Evidence: 10 of 22 wake-ups on 26 Sep ended in "no speech after wake word"

### 3. Accuracy
- [ ] Do only what was asked ("Go back" turned into back + 3 extra clicks)
- [ ] Say exactly what it opened; never claim the wrong thing ("2026" → said "2024 is open")
- [ ] Still seen after the speed work: "play the second video" → "I've started playing it" without looking to confirm
- [ ] "What's the tallest mountain?" once did a Google search instead of just answering
- [ ] Recognise installed app names in speech ("Claude" heard as "Cloud"; the Claude app wasn't found)

### 4. Bluetooth headphones
- [ ] Jarvis's voice follows the current Windows output device (headphones when connected, no restart)
- [ ] Keep the mic on the laptop (a Bluetooth headset mic forces "phone call" quality on everything)

## Later / ideas
- Hard, code-level confirmation before Send / Buy / Post / Delete-type clicks (now only an AI instruction)
- Git version control for the project
- "Stop" while Jarvis is busy (barge-in)
