# Agent core: design (28 Sep, not built yet)

## Why
Today every sentence is handled once: hear → one action → reply → forget. An agent holds a goal, plans, checks each step, recovers and keeps context. This is the core gap (see `handoff.md`).

## The loop (one request)
1. **Context snapshot** (code, ~0.1 s):
   - the front window (title, app);
   - the screen as text (`elements.page_elements()`);
   - open windows;
   - the last 3 requests with their results;
   - "it"/"that" = the last object acted on.
2. **Plan:**
   - Known tasks (abilities, site packs, remembered plans) plan in code with **0 AI**.
   - Otherwise **one** Groq call returns the whole plan as a JSON list of steps, each `{do: ability or tool + args, expect: check}`.
3. **Execute + verify each step (code):** run the step, then check its `expect` against a fresh text snapshot:
   - `window_title contains "WhatsApp"`, `element "Search or start new chat" exists`, `text "Mom" visible`, `focus is an edit box`;
   - no screenshot unless the check needs one.
4. **Recover:**
   - A failed check means one repair call: the AI sees the plan, the failed step and the new snapshot, and returns the remaining steps.
   - If it fails again, stop and ask **one specific** question ("I can't find Mom in WhatsApp. Is she saved under another name?").
5. **Narrate:** say a short line when a step starts that the user will notice ("Opening WhatsApp…"); say the verified result at the end. Never claim anything unchecked.
6. **Safety (unchanged):** the action budget covers the whole plan; send/buy/delete/resign still need a spoken yes, asked **inside** the plan before that step; secrets and VMware are blocked.
7. **Remember:** a successful plan for a phrase becomes a *remembered plan* (like phrase memory), so it's 0 AI next time.

## Where it goes in the code
- New `jarvis/agent/`:
  - `context.py` (the snapshot);
  - `plan.py` (Step/Plan, JSON parse + validation against the ability and tool catalog);
  - `checks.py` (the expect-check functions, text only);
  - `run.py` (execute, verify, recover, narrate).
- `brain.py`: for kinds action/screen, the AI returns a plan instead of a tool-by-tool loop. The old loop stays as the fallback until the task suite shows the new one is better.
- Narration needs non-blocking speech while acting: `tts.Speaker` must speak without waiting.

## Task suite (the measure): each run live, scored done / time / AI calls / user help needed
| # | Say | Done when |
|---|---|---|
| 1 | "Play lofi on YouTube and make it full screen" | a video plays full screen |
| 2 | "Open WhatsApp and message Mom: I'll be late" | the message is typed and it asks to send (not sent) |
| 3 | "Connect my Rockerz headphones" | Bluetooth shows Connected |
| 4 | "Open my Downloads and find the newest PDF" | Explorer open, file selected |
| 5 | "Upload my resume here" (a site's file dialog open) | the file is chosen in the dialog |
| 6 | "Open VS Code, go to line 40 and comment it" | line 40 commented |
| 7 | "Snap Chrome left and VS Code right" | both snapped |
| 8 | "Close all YouTube tabs" | none left |
| 9 | "Turn on night light and set brightness to 40" | both done |
| 10 | "What's on my screen?" | correct short description |
| 11 | "Open Physics Wallah, my batch, chemistry" | the chemistry page is open |
| 12 | "Pause, go back 30 seconds, and turn on subtitles" | all three done |

**Target:**
- ≥ 10/12 done without help;
- median ≤ 3 s for code-planned tasks and ≤ 6 s for AI-planned ones;
- ≤ 1 AI call per task on average.

## First build steps (next session)
1. `context.py` + `checks.py`, with unit tests (fake windows and elements, like the other tests).
2. `plan.py`: the JSON plan schema + validation; a Groq prompt that returns a plan using the ability/tool names.
3. `run.py`: execute + verify + one repair; wire it into brain for kind=action behind a config switch (`agent_mode = true`).
4. Run the task suite live; compare with the old loop; flip the default when better.
