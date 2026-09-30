"""Physics Wallah: your batch and its subjects, in code (see jarvis/skills/sites/pw.py)."""

from . import ability
from ..skills.sites import pw

_PW = r"(?:pw|physics wallah|p w)"


@ability("pw_batch", "open the user's batch on Physics Wallah (PW)",
         rf"(?:open|go to|show)(?: me)? (?:my )?{_PW}(?: batch)?",
         rf"(?:open|go to|show)(?: me)? my (?:{_PW} )?batch(?: on {_PW})?")
def pw_batch():
    return pw.open_study()


@ability("pw_khazana", "open Khazana (the PW batch's old recorded classes), optionally a subject/year/teacher",
         r"(?!.*\b(?:youtube|google|search)\b)(?P<value>.*\bkhazana\b.*)", value="subject year")
def pw_khazana(request: str):
    return pw.open_khazana(request)


@ability("pw_subject", "open a subject of the user's PW batch (chemistry, maths, 'chemistry by sanya'…)",
         rf"(?:open|go to|show)(?: me)? (?:my )?(?:{_PW},? )?(?:my batch,? )?(?P<value>[a-z ]+?)(?: (?:on|in|from) (?:my )?{_PW}(?: batch)?)",
         value="subject")
def pw_subject(subject: str):
    return pw.open_subject(pw.subject_in(subject) or subject)
