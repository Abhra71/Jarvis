"""The brain's first job: understand ONE sentence in its situation and say what it means, in a fixed small format.

No sentence patterns decide anything. The model sees what was said, how sure the hearing was, the last couple of
sentences, the screen (as text) and the user's profile, and answers with one JSON object:

    {"kind": "act",     "steps": [{"do": "tab", "action": "close", "which": "current"}], "say": "Closing this tab."}
    {"kind": "ask",     "say": "Last index of what in v? A letter like 'a'?"}
    {"kind": "chat",    "say": "Tokyo."}
    {"kind": "ignore"}                                  # not said to Jarvis: room talk, a song, noise
    {"kind": "control", "control": "stop"}             # stop | yes | no | cancel | undo | coding_on | coding_off
    {"kind": "code",    "code": "declare String v = \"AEIOUaeiou\"; v already exists as int: change its type"}
    {"kind": "refuse",  "say": "I don't edit the keys file, so your keys stay safe."}

The instructions (SYSTEM) never change between calls, so the providers' prompt caches keep them for free.
"""

import json

from .providers import Reply, call, parse_json

KINDS = ("act", "ask", "chat", "ignore", "control", "code", "refuse")
CONTROLS = ("stop", "yes", "no", "cancel", "undo", "redo", "coding_on", "coding_off")
DOS = ("open_app", "open_site", "chrome_profile", "tab", "window", "click", "type", "keys", "scroll", "search", "play",
       "media", "volume", "display", "bluetooth", "settings", "folder", "file", "timer", "screen", "pw", "chess",
       "bluej", "upload", "mouse")

SYSTEM = """You are the understanding step of Jarvis, a voice assistant that runs a Windows PC for its user.
You get ONE heard sentence with its situation. Decide what the user means and answer with ONE JSON object only.

kinds:
- "act": do something on the PC. Give "steps" (in order) and a short "say" (what you are doing, max 8 words).
- "ask": the meaning is unclear or a needed detail is missing. "say" = ONE short, specific question.
- "chat": a question or talk that needs only an answer. "say" = the answer, short and friendly.
- "ignore": not said to Jarvis: background talk, a song or video playing, other languages, scraps of noise,
  fragments that ask for nothing. Most garbled lines with odd words are noise: ignore them.
- "control": "control" is one of stop, yes, no, cancel, undo, redo, coding_on, coding_off.
- "code": coding mode is on (or the sentence is clearly code) and the user describes code to write or change.
  "code" = a precise description of the change (names, types, values). If it would make an error (for example
  declaring a variable that already exists), still describe it; the coding expert checks it.
- "refuse": the request would edit or reveal a secrets file (.env, API keys, passwords) or is harmful.
  "say" = a short, kind reason.

Each step is a flat object with "do" and its fields, exactly like these (fields with ? are optional):
{"do":"open_app","app":"Notepad"}
{"do":"open_site","site":"youtube.com","browser?":"Brave","profile?":"main"}
{"do":"chrome_profile","profile":"Miscellaneous"}
{"do":"tab","action":"close|new|switch|close_others|close_matching","which?":"current|youtube|2nd","count?":2}
{"do":"window","action":"close|minimize|maximize|snap|minimize_all|show_all|move_monitor","target?":"Chrome","side?":"left"}
{"do":"click","target":"Play Bots","double?":false}
{"do":"type","text":"Jarvis","into?":"Repository name"}
{"do":"keys","keys":"ctrl+c"}            (also "enter", "f5", "alt+left", "ctrl+a", "delete", "win+d")
{"do":"scroll","direction":"up|down|top|bottom"}
{"do":"search","query":"best biryani in kolkata","site?":"youtube"}
{"do":"play","query":"Ari Ari","site?":"youtube"}
{"do":"media","action":"play|pause|fullscreen|exit_fullscreen|seek|skip_ad|next","seconds?":30}
{"do":"volume","level?":40,"change?":"up|down","mute?":true}
{"do":"display","night_light?":"on","brightness?":40}
{"do":"bluetooth","device":"Rockerz 480","connect":true}
{"do":"settings","page":"bluetooth"}
{"do":"folder","folder":"Downloads"}
{"do":"file","name?":"report","size?":"37272 KB","newest?":"pdf"}
{"do":"timer","seconds":120}
{"do":"screen","question":"what is on the screen?"}
{"do":"pw","target":"batch|subject|khazana","subject?":"chemistry","year?":2026}
{"do":"chess","move":"f2f4"}
{"do":"bluej","action":"new_class|open_class|delete_class","name":"Test"}
{"do":"upload","file":"newest screenshot"}
{"do":"mouse","action":"move|double_click|right_click","direction?":"right"}

Full answers look like:
{"kind":"act","steps":[{"do":"tab","action":"close","which":"current"},{"do":"tab","action":"close_matching","which":"chess"}],"say":"Closing both tabs."}
{"kind":"ask","say":"Which class should I open?"}
{"kind":"ignore"}
{"kind":"control","control":"coding_on"}
{"kind":"code","code":"add a for loop: int i from 0 while i < 10, i++ inside main"}

Rules:
- Use the screen: "close this", "click Start", "the first one", "apply" mean things on the front window.
- Hearing mistakes are common: fix obvious ones from context ("public glass" = public class, "Clawed"/"Cloud app" =
  Claude, "graves"/"Brave Show" = Brave, "Physics Voila"/"Kazana" = Physics Wallah/Khazana, "Rockers" = Rockerz).
- A word that is a name on screen is not a command: "Click on Sound 3" on a page with a chapter "Sound" is a click,
  not the volume.
- Several requests in one sentence = several steps, in order.
- Never guess text to type or a site from one odd word: ask.
- Deleting, sending, buying, posting need a yes: still give the step; Jarvis asks before doing it.
- Corrections ("No, I meant X", "it did not work") refer to the previous sentence: act on the corrected meaning.
- If unsure between doing and asking, ask. Doing the wrong thing is the worst outcome."""


# The same instructions in about half the tokens (Groq's free tier allows 200,000 tokens a day per model, so the
# prompt's size decides how many requests a day each model can take). Benchmarked against SYSTEM before use.
SYSTEM_SHORT = """You understand ONE sentence heard by Jarvis, a voice assistant running a Windows PC. Reply with ONE JSON object.
kind: act (do it: "steps" + short "say") | ask (unclear/missing detail: "say" one short question) | chat (just answer: "say") |
ignore (not said to Jarvis: room talk, songs, videos, other languages, noise scraps) | control ("control": stop|yes|no|cancel|undo|redo|coding_on|coding_off) |
code (coding mode: "code" = precise description of the code change) | refuse (edits/reveals .env, API keys, passwords, or harmful: "say" why).
Steps are flat {"do":..., fields}:
open_app app | open_site site browser? profile? | chrome_profile profile | tab action(close|new|switch|close_others|close_matching) which? count? |
window action(close|minimize|maximize|snap|minimize_all|show_all|move_monitor) target? side? | click target double? | type text into? |
keys keys("ctrl+c","enter","f5","alt+left") | scroll direction(up|down|top|bottom) | search query site? | play query site? |
media action(play|pause|fullscreen|exit_fullscreen|seek|skip_ad|next) seconds? | volume level?|change?(up|down)|mute? |
display night_light? brightness? | bluetooth device connect | settings page | folder folder | file name?|size?|newest? |
timer seconds | screen question | pw target(batch|subject|khazana) subject? year? | chess move | bluej action(new_class|open_class|delete_class) name |
upload file | mouse action(move|double_click|right_click) direction?
Example: {"kind":"act","steps":[{"do":"tab","action":"close","which":"current"}],"say":"Closing this tab."}
Rules: use the screen for "this/that/the first one". Fix obvious mishearings (public glass=public class, Clawed/Cloud app=Claude,
graves=Brave, Physics Voila/Kazana=Physics Wallah/Khazana, Rockers=Rockerz). A name on screen is not a command ("Click on Sound 3" on a
page with chapter "Sound" = click, not volume). Several requests = several steps. Never guess text to type or a site from one odd word.
Corrections refer to the previous sentence. Delete/send/buy/post: give the step (Jarvis asks first). Unsure between doing and asking: ask."""


def build_user(said: str, screen: str, previous: list[str] | None = None, unsure: bool = False,
               profile: str = "", coding: bool = False) -> str:
    lines = []
    if profile:
        lines.append(f"User: {profile}")
    lines.append(f"Screen: {screen or 'unknown'}")
    if coding:
        lines.append("Coding mode: on")
    if previous:
        lines.append("Just before: " + " | ".join(f'"{p}"' for p in previous[-2:]))
    lines.append(f'Heard{" (hearing unsure)" if unsure else ""}: "{said}"')
    return "\n".join(lines)


def understand(model: str, said: str, screen: str, previous=None, unsure=False, profile="", coding=False,
               timeout: float = 20.0, system: str | None = None) -> tuple[dict | None, Reply]:
    reply = call(model, [{"role": "system", "content": system or SYSTEM},
                         {"role": "user", "content": build_user(said, screen, previous, unsure, profile, coding)}],
                 timeout=timeout, max_tokens=1200)
    if not reply.ok:
        return None, reply
    meaning = parse_json(reply.text)
    if meaning is None:
        reply.error, reply.detail = "bad_json", reply.text[:200]
        return None, reply
    return normalize(meaning), reply


def _step(s: dict) -> dict:
    """One step in the flat form {"do": ..., fields}. Models also write {"open_site": {...}}, {"step": "keys", ...}
    or "do": "chess{move}"; those mean the same thing."""
    s = dict(s)
    do = str(s.pop("do", "") or s.pop("step", "") or s.pop("action_type", "") or "").strip().lower()
    do = do.split("{")[0].replace(" ", "_")
    if do not in DOS:
        for k in list(s):
            if k in DOS:
                inner = s.pop(k)
                do = k
                if isinstance(inner, dict):
                    s.update(inner)
                elif inner not in (None, True, ""):
                    s.setdefault("value", inner)
                break
    s["do"] = do
    return s


def normalize(m: dict) -> dict:
    """Small, forgiving clean-up of the shape (never of the meaning): "type"/"step" used for "kind", a single step
    given as a dict, steps nested under their name, a top-level step with no "steps" list."""
    m = dict(m)
    kind = str(m.get("kind") or "").strip().lower()
    if kind not in KINDS:
        for alt in ("type", "step", "intent"):
            v = str(m.get(alt) or "").strip().lower()
            if v in KINDS:
                kind = v
                break
            if v in DOS and not m.get("steps"):  # {"step": "chess", "move": ...}: one action, said flat
                kind = "act"
                m["steps"] = [{k: val for k, val in m.items() if k not in ("say", "kind", "type", "step", "intent")}
                              | {"do": v}]
                break
    m["kind"] = kind
    steps = m.get("steps") or []
    if isinstance(steps, dict):
        steps = [steps]
    m["steps"] = [_step(s) for s in steps if isinstance(s, dict)]
    if m.get("control"):
        m["control"] = str(m["control"]).strip().lower().replace(" ", "_")
    return m


def as_text(m: dict) -> str:
    """Everything the meaning says, lower-case, for checking that the right words are in it."""
    return json.dumps(m, ensure_ascii=False).lower()
