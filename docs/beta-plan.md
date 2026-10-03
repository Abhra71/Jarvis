# Beta, personalization and self-learning: the user's spec (3 Oct)

Agreed with the user on 3 Oct. Build it in the order in `docs/handoff.md` (self-learning in Block 5; the wizard and
reports only in the beta build, when the feel is near 100%). Don't ask the user to explain this again.

## 1. Wake word: "Hi Jarvis" (changed 3 Oct)
- The pretrained openWakeWord model `hey_jarvis` keys on "Jarvis": "Hi Jarvis" scores 1.00 like "Hey Jarvis"
  (synthetic-voice test). `stt.strip_greeting` drops "Hi/Hey/High Jarvis," at the start of a request so code routes.
- Later (beta): the wizard records the person saying "Hi Jarvis" 3-5 times to set their threshold. A custom-trained
  "hi jarvis" model only if false wakes show up.

## 2. Install and wizard
- **Install from the terminal**: one command (PowerShell) gets Python/venv/dependencies, then opens the wizard.
- **Everything after that is GUI**, graphically rich: a desktop window showing web-style screens (animations,
  progress steps, dark theme; e.g. pywebview + HTML/CSS), not Tk. Jarvis itself stays voice-only; the wizard (and
  later a small settings/report viewer) is the only GUI.
- Screens: Welcome + consent → Mic test (live meter, "Hi Jarvis" x3) → Keys (Groq, Gemini: illustrated step-by-step
  guide, each key tested with a green tick, stored in Windows Credential Manager, never in a file) → Welcome survey →
  Done (30-second spoken demo).

## 3. Welcome survey: short, but collects almost everything
Rule: **detect first, ask only what can't be detected**, pre-fill answers, use tiles/toggles (no typing except names).
~2-3 minutes.
- **Detected, only confirmed** (not asked): Windows version, RAM, GPU (decides GPU hearing), screen count + scaling,
  mics/speakers, installed apps, browsers + Chrome profiles, paired Bluetooth devices, top sites from bookmarks and
  history (counted on the PC; only site names kept, never uploaded), coding tools found (BlueJ, VS Code, compilers).
- **Asked:**
  1. About you: name, what Jarvis calls you ("my lord", name, "boss"…), language/accent (Indian English, Hindi words
     mixed in?), student/working/both.
  2. Voice: Jarvis's voice (pick from samples), speed, short or chatty replies, chime vs "Yes, my lord?".
  3. Your sites (tiles, pre-ticked from the scan): YouTube, study (PW, Unacademy, Khan…), shopping (Amazon,
     Flipkart), mail (Gmail/Outlook), social, chess (chess.com/lichess), music, + "add your own".
  4. Your apps (pre-ticked): browser, code editors and languages (Java/BlueJ, C++/VS Code, Python…), Office, games.
  5. Devices: headphones to connect by name (from the paired list), second monitor layout.
  6. Safety: what needs a spoken yes (default: send, buy, post, delete-like actions; can only be made stricter).
  7. Data sharing (consent): off / errors only / errors + what was asked (scrubbed). Shown in plain words.
- Answers → a settings file (`data/profile.json`) that replaces today's hard-coded personal values; abilities and
  site packs are switched on from it.

## 4. Personalizing itself for a new person (three layers)
1. **Asked** (the survey) on day one.
2. **Detected** (the scan): apps, sites, devices, profiles.
3. **Learned from use, forever**: every request counted; a request done 3 times becomes a code shortcut (like the
   user's PW subjects in `data/pw.json`); unused things fade from the planner's list. The user's Jarvis = the same
   engine with this filled in. No personal names in new code: they come from the profile.

## 5. Self-learning ("use AI once, efficiently, then never again"), for the user AND testers (Block 5)
- First time on a new task/site (e.g. Amazon): the AI plans it. If it works, save a **recipe**: the URL, each step's
  target by **name/role** (not screen position), and a check that proves it worked.
- Next time the recipe runs **in code** (~1 s, 0 AI).
- A step breaks (site changed): ask the AI about **that one step only** ("the Search button is gone; what's the new
  one?"), patch it, save. Never re-plan the whole task when one step fails.
- Trust: new after 1 success, trusted after 2; 2 failures in a row → back to AI planning, then relearn.
- Generalize: "search boots on amazon" learns "search {x} on amazon" (`PlanMemory` patterns already started).
- Measured: AI calls per site per day on the status page ("Amazon: 4 AI calls → 0"). The goal is that number
  falling to zero for anything done often.
- Later: recipes that work could be shared between users (opt-in), so a new person's common sites are already learned.

## 6. Reports (beta)
- Consent first; scrubbed: no audio, screenshots, typed text, passwords, keys, emails; site names and step results
  only. "That was wrong" command marks a task. One-way upload to a receiver only the user reads; a dashboard; updates.
- Before building: ask the user for each test laptop's specs and where reports should go.

## 7. Going public: repository refresh (the user, 3 Oct; do it just before the beta build, not now)
Jarvis stops being "only for me" and becomes a product anyone in the world can use. The repo must attract users.
- **Three flagship features** lead everything (README, demo, description) and get the most polish and tests:
  1. **Self-healing / self-learning**: AI once on anything new, then code forever; a broken step is repaired alone;
     it learns each new person's habits by itself.
  2. **Coding mode**: write Java (BlueJ) and C++ (VS Code) by talking; never leaves broken code; undo; error check.
  3. **Chess mode**: play chess by voice (Block 7).
  Everything else is "also does".
- **Remove everything stale**: old plans (`docs/jarvis4-plan.md`, `docs/archive/`, `ROADMAP.md` history),
  `tools/prototypes/`, unused eval tools, dead code; personal values (names, PW batch, Rockerz, paths) move into the
  profile.
- **README as a product page**: one-line pitch, a short demo GIF per flagship, "what you can say", privacy,
  one-command install, requirements, FAQ. GitHub description, topics, tags; LICENSE, CONTRIBUTING, issue template.
- **Every message clear, crisp, friendly**: spoken replies, pop-ups, wizard, errors, status page; commits and
  release notes as a short headline plus one plain line.
- Ask the user then: public name/branding, and whether to keep git history or start a fresh public repo.
