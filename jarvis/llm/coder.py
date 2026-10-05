"""The coding expert: turns what the user says into a precise edit of the WHOLE file, or one good question.

It sees the file with line numbers and the cursor, and answers with one JSON object:
    {"kind": "edit",   "code": "<the complete new file>", "say": "Added String v."}
    {"kind": "ask",    "say": "v is already an int. Change it to a String, or use a new name?"}
    {"kind": "cursor", "line": 7, "say": "Inside main."}
    {"kind": "ignore"}                                    # noise, nothing to write

Nothing it writes reaches the user's file before the compiler has checked it (jarvis/codecheck.py): a result
with new errors is refused or fixed, never written. The instructions never change between calls (cacheable).
"""

from .providers import Reply, call, parse_json

SYSTEM = """You are the coding expert inside Jarvis, a voice assistant. A student is speaking code out loud while
editing a {lang} file. You get the file (with line numbers), the cursor line, and what they said (speech
recognition can mishear: "public glass" = public class, "IE" = i, "iOS stream" = iostream, "system out print" =
System.out.print). Answer with ONE JSON object only:

{{"kind":"edit","code":"<the COMPLETE new file>","say":"<what you changed, max 10 words>"}}
{{"kind":"ask","say":"<one short specific question>"}}
{{"kind":"cursor","line":<line number>,"say":"<where>"}}
{{"kind":"ignore"}}

Rules:
- Write exactly what was asked, in correct {lang}, and nothing more. Keep everything else in the file unchanged
  (same names, same order, same comments, same style).
- Put new code where it belongs: statements inside the method at the cursor, else inside main (create main or the
  class only if they are missing; never a second class or a second main); methods inside the class; imports or
  #includes at the top when needed (Scanner, ArrayList, Arrays, HashMap; iostream, vector, string).
- Match the file's brace style (Java here: braces on their own line, 4 spaces).
- The result must compile. If what was said would not compile or would clash with the code (for example
  declaring a variable that already exists, or a for loop declaring a variable already declared), do NOT write
  it: ask ONE question that offers the fix ("v is already an int. Change it to a String, or use another name?").
  Exception: a direct instruction to change something ("change v to a string") is an edit, not a clash.
- If the request is missing something needed (a size, what to search for, which variable), ask.
- Deleting all of the user's code needs a confirmation: ask.
- "move the cursor"/"go to" requests are "cursor".
- Fragments that are clearly noise: ignore."""


def numbered(text: str) -> str:
    return "\n".join(f"{i:3}| {line}" for i, line in enumerate(text.split("\n"), 1)) if text else "(empty file)"


def build_user(said: str, text: str, cursor: int, previous=(), file_name: str = "") -> str:
    lines = []
    if file_name:
        lines.append(f"File: {file_name}")
    lines.append(f"Cursor: line {cursor}")
    lines.append(numbered(text.rstrip("\n")))
    if previous:
        lines.append("Said just before: " + " | ".join(f'"{p}"' for p in previous[-2:]))
    lines.append(f'Said now: "{said}"')
    return "\n".join(lines)


def edit(model: str, lang: str, said: str, text: str, cursor: int, previous=(), file_name: str = "",
         timeout: float = 30.0) -> tuple[dict | None, Reply]:
    name = {"java": "Java", "cpp": "C++"}.get(lang, lang)
    reply = call(model, [{"role": "system", "content": SYSTEM.format(lang=name)},
                         {"role": "user", "content": build_user(said, text, cursor, previous, file_name)}],
                 timeout=timeout, max_tokens=2500)
    if not reply.ok:
        return None, reply
    out = parse_json(reply.text)
    if out is None:
        reply.error, reply.detail = "bad_json", reply.text[:200]
        return None, reply
    out["kind"] = str(out.get("kind", "")).strip().lower()
    return out, reply
