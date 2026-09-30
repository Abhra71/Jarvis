"""Physics Wallah: your batch and its subjects, in code (see jarvis/skills/sites/pw.py)."""

from . import ability
from ..skills.sites import pw

_PW = r"(?:pw|physics wallah|p w)"


@ability("pw_batch", "the user's PW batch",
         rf"(?:open|go to|show)(?: me)? (?:my )?{_PW}(?: batch)?",
         rf"(?:open|go to|show)(?: me)? my (?:{_PW} )?batch(?: on {_PW})?")
def pw_batch():
    return pw.open_study()


@ability("pw_khazana", "PW Khazana (old recorded classes)",
         r"(?!.*\b(?:youtube|google|search)\b)(?P<value>.*\bkhazana\b.*)", value="subject year")
def pw_khazana(request: str):
    return pw.open_khazana(request)


@ability("pw_subject", "a subject in the user's PW batch",
         rf"(?:open|go to|show)(?: me)? (?:my )?(?:{_PW},? )?(?:my batch,? )?(?P<value>[a-z ]+?)(?: (?:on|in|from) (?:my )?{_PW}(?: batch)?)",
         value="subject")
def pw_subject(subject: str):
    return pw.open_subject(pw.subject_in(subject) or subject)
