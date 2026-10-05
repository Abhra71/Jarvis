# Working on Jarvis: the user's standing instructions (read before anything else)

## Think like the person who will use it
Before every decision, picture a **stressed worker** who has been bent over a keyboard all day and just wants to
sit back and say what they need. Ask: *would this person trust it, wait for it, or give up on it?*
- They will not learn commands. Anything a person would say to a capable assistant must just work.
- One wrong action (closing the wrong window, typing in the wrong place, the volume set to 3%) and they stop using
  it. A short, sensible question is fine; a confident mistake is not.
- Slow is frustrating, silent failure is worse, fake success ("done" when it isn't) is worst of all.
- Every spoken line should be short, sensible and encouraging. Never robotic or blaming.
- Autocorrect towards what makes sense right now (screen, code, past corrections). When a guess is cheap to
  undo, use the sensible default and say it ("Added int i = 0"); ask only when a wrong guess would cost them.

## The goal
Run the whole Windows 10/11 PC by voice: **reliable, fast, accurate**, for anyone, on any PC (not just this one).
Some sites can be extra strong (PW, YouTube, Spotify, chess.com). Flagships: self-learning, coding mode, chess mode.

## How to work (non-negotiable)
- **Measure only on the user's real sentences** (`data/gold/`, `tools/bench.py`, the trial logs). Never report a
  score from tests you wrote as progress. "Done" means the user's own trial says so.
- **No cosmetic work.** Real tests, real data, real compilers, real screens (scratch windows only).
- **No sentence patterns.** If something isn't understood, fix the understanding (prompt, skill, lesson), never add
  a regex.
- **AI is allowed at first but must fall drastically**: recipes and the local matcher make repeats cost 0 AI.
  Report AI calls per request against the targets in `docs/rewrite-plan.md`.
- **Each AI job goes to the model proven best for it** on benchmarks (`tools/assign.py`, `docs/model-benchmark.md`),
  with backups from other providers. One account per provider (no multi-account key rotation).
- **Self-heal and learn at once** after every mistake and correction: no restart, no waiting.
- **Log smartly:** what's needed to debug, a storage budget, screenshots only on failure (never of passwords).
- **Safety means ask, never block.** Delete, send, buy and post need a spoken yes, then are done.
  Never: secrets files (`.env`, keys), typing into VMware/Kali, sending or buying without a yes.

## Keeping the user informed (also in auto mode)
- The user works by voice and reads plain language. Say what you are doing, why, and what you found, including bad
  news and your own mistakes, in plain words with numbers. No jargon walls.
- Say **before** you take over the screen, and when you'll need the PC or the user.
- End every reply with the progress footer: `Dream: ~N% · Daily-use feel: ~N%`. The feel number comes from the
  user's trial, not your tests.
- Give honest timelines; when a date slips, say so and why.

## Practical rules
- Plan and status: `docs/rewrite-plan.md` (the rewrite, 5 Oct), `docs/handoff.md`, `docs/beta-plan.md` (later).
- Commit and push after each working piece, only when `.venv\Scripts\python -m unittest discover tests` ends in OK.
- Use only pre-approved command shapes (`cd /c/Syntax_Assembler/Jarvis && .venv/Scripts/python ...`): the user
  can't sit to approve prompts.
- Live tests only in scratch windows (`scratch/`), and stop unless that window is in front (never the Claude app).
- The GPU only while a conversation is going (hearing loads on the wake word, exits when idle).
- The release order: near-100% on this PC → the beta (`docs/beta-plan.md`) → the user's second laptop → friends.
