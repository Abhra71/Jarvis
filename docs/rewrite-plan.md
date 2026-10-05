# Jarvis rewrite plan (5 Oct 2026)

## Why
The trial (3 and 5 Oct) showed that only about **35% of real requests did what the user wanted**. Coding mode wrote code
for 3 of 14 sentences, and one of those broke the code. The user would not use it, and no one else would either.

The foundation is wrong:
- **Command-line thinking.** 343 hand-written sentence patterns in 5 layers decide before anything understands the
  user. Jarvis works only when the user speaks "its" way.
- **Measured on the wrong thing.** The scores came from tasks written by the builder, never from the user's own
  sentences, so "better" was reported while the real experience stayed the same.
- **Patches, not design.** 128 commits in 10 days, mostly "this sentence failed → add a pattern".
- **"Least AI" applied too early.** The AI was a costly last resort, so Jarvis guessed instead of understanding.
- **Hearing never fixed properly.** About 1 sentence in 7 arrives as junk.
- **Invisible failures.** "Not a coding command" was logged as "done".
- **Self-learning was never built.** The user's main strategy existed only as a doc.

## The goal (the yardstick for every decision)
A person who is tired of bending over a keyboard **sits back and talks; the work gets done reliably, fast and
correctly**. It is not a toy: it is a tool for work, for anyone on **Windows 10 or 11**.
- **No commands to learn.** Anything a person would say to a capable assistant is understood.
- **Reliable:** it does what was meant, or asks one short, sensible question. It never does the wrong thing confidently.
- **Fast:** learned tasks feel instant; new ones take a few seconds at most.
- **Self-healing and self-learning** after every mistake, **at once**, with no restart.
- **Talks like a good assistant:** short, sensible, encouraging; honest about what it did.
- Strong on some sites (PW, YouTube, Spotify, chess) is fine. Built so it works on every PC, not just this one.

### Targets (measured only on the user's real sentences)
| Measure | Target |
|---|---|
| Requests that do what was meant (or ask one good question) | ≥ 95% |
| Wrong actions done confidently | ≤ 1% |
| Learned tasks: said → done | ≤ 1.5 s median |
| New tasks (AI plans) | ≤ 4 s median |
| Coding: sentence → correct, compiling Java in the file | ≥ 95% |
| Junk heard and acted on | 0 |

## The new foundation

```
 voice ─► EARS ─► UNDERSTAND ─► (learned skill? run it) ─► HANDS ─► VERIFY ─► REPLY
                     │  ▲                                     │
                     ▼  └──── MEMORY: skills, lessons, ◄──────┘  (every result, every correction,
                  EXPERTS         corrections, profile               saved at once)
           (coding, web, system, chess)
```

1. **Ears (hearing).**
   - Groq Whisper, with hints taken from what is on screen: the words in the window, the names in the code, the
     user's own names.
   - Junk is dropped silently.
   - When the hearing is unsure, a small caption shows what was heard, so a mishearing is never acted on blindly.
2. **Understand: one brain for every sentence.**
   - No pattern layers. Each sentence goes to one fast AI call with:
     - what was said and the last few turns;
     - the screen as text (front app, focused field, visible items);
     - the user's profile;
     - the most relevant learned skills and lessons.
   - The answer is a fixed, small action format: what to do, the steps, how to check each step, or one question.
   - Only stop / yes / no / cancel / undo are hard-wired, for speed and safety.
3. **Experts.** The brain hands specialist work to an expert with deeper knowledge:
   - **Coding expert (flagship):**
     - Sees the whole file and the cursor, and turns any Java (and C++) said in plain words into a precise edit:
       add, change, delete, move or rename.
     - **Every edit is compiled before it is written.** If it would break the code or repeat a declaration,
       nothing is written and Jarvis says why ("v is already a String. Change it, or use a new name?").
     - Asks when the meaning is unclear ("last index of what?"); undo and redo always work.
   - **Web expert:** pages read by structure, with site packs for PW, YouTube, Spotify and chess.com.
   - **System expert:** apps, windows, files, settings, Bluetooth, volume.
   - **Chess expert (flagship):** sees the board and plays moves said in words.
4. **Hands (kept from today):**
   - clicking and reading the screen (UI Automation, OCR);
   - keys, the mouse, windows;
   - BlueJ and VS Code read/write, the compile check;
   - the PW and YouTube knowledge;
   - the safety rules (a spoken yes before send, buy, post or delete).
5. **Verify.** Every step is checked against the screen. If a step fails: one repair of **that step only**, then an
   honest answer.
6. **Memory: self-learning, instant (flagship).**
   - **Skills:** a task that worked is saved as a recipe:
     - the meaning, not the exact words;
     - the steps, with targets by name and role;
     - the check.
     The next time it runs in code with **no AI** (about 1 s). After 1 success it is "new", after 2 "trusted". 2
     failures in a row send it back to the AI to relearn.
   - **Lessons:** every mistake and every correction ("No, I meant…", "that's wrong", undo, a failed check) is
     written as a short lesson **the moment it happens**. It is fed to the brain whenever a similar request comes,
     so the same mistake is not repeated, even in the same conversation.
   - **The small model that trains itself:** a small local text-matching model on the CPU (sentence embeddings)
     finds the closest skill or lesson for anything said. It "learns" instantly because adding an example IS the
     training: no retraining, no restart. Real fine-tuning of a language model on a laptop after each mistake is not
     practical; this gives the same effect at once.
   - **Profile:** the user's sites, apps, names and devices, from the wizard and from use.
7. **Smart logging, with a storage budget.**
   - One compact record per request: what was heard and how sure, what was understood, the steps, the checks, time,
     AI calls, the result and why.
   - A **screenshot only when something fails**, shrunk and greyscale (~50 KB). Never of password fields or
     private windows.
   - Old records are summarised then removed: a total budget (e.g. 200 MB), and 30 days for screenshots.
   - The record is honest: "done" only when the check proved it.
8. **AI providers: a chain with fallbacks** (all free, no card; see `docs/api-keys-guide.md`).
   - **Groq** is the main brain: 3 models, each with its own 1,000 a day.
   - **Gemini:** the screen (vision) and a backup.
   - **NVIDIA:** a large backup (Nemotron 3 Super 0.8 s; Nemotron Nano Omni 1.4 s can read images).
   - **Cloudflare:** the last resort.
   - The same instructions are sent every time, so Groq's cache doesn't count them against its 8,000-a-minute limit.
   - The status page shows each provider's allowance left.
9. **Portable from day one.**
   - No personal paths or names in the code: everything comes from the profile.
   - Apps, browsers, editors and compilers are found on any Windows 10/11 PC.

## The AI pipeline (the user, 5 Oct): every job goes to the model that is best at it, proven on real data
No single model is used until it fails. Each kind of job is assigned to the model that **measurably** does it best:
- understanding a sentence → an action plan;
- deciding "ask, or act?";
- spotting noise;
- Java/C++ edits;
- fixing a failed step;
- reading the screen (vision);
- summarising, chat.

1. **Benchmark first.** Every candidate model is run on the same real test cases for each job: the user's sentences
   with their screens, and the coding sentences compiled and checked. The score is accuracy, speed (median and
   slowest 10%), tokens and failures (timeouts, bad JSON).
2. **Assign by the numbers.** Each job gets a ranked chain (best → next best → …), written down with the scores that
   justify it (`docs/model-benchmark.md`).
3. **Spread the load.** The pipeline tracks each model's minute and day allowance live, and sends work to the next
   model in the chain **before** a limit is hit, not after a failure. Repeated instructions are kept identical so
   Groq's cache doesn't count them.
4. **Re-run the benchmark** when a provider changes its models or limits, and after each trial (new real sentences).
   The chain changes only when the numbers say so.

## How progress is measured
- **The gold set.** Every real sentence the user has said: 480 before the trial and all from the trial. Each one has
  what should happen written down. Coding ones must produce code that compiles and matches.
- **An offline run:** the brain's decision for each sentence, with no clicking. **A live run:** a sample done for
  real in scratch windows.
- **Reports quote only this set.** Every new trial adds its sentences to it.

## Build order (same repo; the new core is built next to the old, and replaces it only when it wins on the gold set)
| Phase | What | Done when |
|---|---|---|
| **0. Ground truth** | The gold set from all real sentences; the eval runner; honest task records; the provider chain + key guide | The gold set scores today's Jarvis (expected ~35%) |
| **1. The brain** | Understand-every-sentence core with the fixed action format, wired to today's hands; old pattern layers bypassed | ≥ 85% on the gold set offline |
| **2. Coding expert** | Whole-file Java/C++ edits from any phrasing, the compile gate, duplicate checks, questions, undo | ≥ 95% on 150+ coding sentences (the user's own + a broad Java set), live in a scratch BlueJ project |
| **3. Memory** | Skills, lessons, the local matching model, instant learning from corrections | A corrected mistake isn't repeated; a repeated task runs with 0 AI calls |
| **4. Ears** | Screen- and code-aware hints, junk filter, the "heard" caption | Junk acted on = 0; misheard code words (e.g. "public glass") fixed |
| **5. Sites and chess** | PW (lectures, mark done), YouTube, Spotify, chess.com; chess mode | Each site's top 20 requests ≥ 95% |
| **6. Speed, logging, voice** | Storage budget, failure screenshots, reply style | Targets table met |
| **7. The user's trial again** | 2–3 days | ≥ 90% from the trial logs; the user says they'd use it |
| **Then** | Portability on the second laptop → the beta → going public (`docs/beta-plan.md`) | |

## Rules for this rewrite
- One measure: the user's real sentences. Nothing is "done" until the user's own trial says so.
- No new sentence patterns. If something isn't understood, the fix goes into the brain's instructions, a skill or a
  lesson, never a regex.
- Every failure is visible in the logs, in plain words.
- Live tests only in scratch windows (`scratch/`).
