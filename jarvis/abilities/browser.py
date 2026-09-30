"""Browser tabs by name: instant, no AI, and checked (the tabs are read again afterwards)."""

from . import ability
from ..skills import desktop

_NOT_A_NAME = r"(?!(?:this|that|the current|current|it|my|all|the|other|every|these|those)\b)"


@ability("close_tabs", "close every browser tab whose title has this name",
         rf"close (?:all|every|each) (?:of )?(?:the |my )?{_NOT_A_NAME}(?P<value>.+?) tabs?",
         rf"close (?:the |my )?{_NOT_A_NAME}(?P<value>.+?) tabs", value="tab name")
def close_tabs(name: str):
    return desktop.close_tab(name, every=True)


@ability("close_tab", "close the browser tab with this name (the current tab: press_key ctrl+w)",
         rf"close (?:the |my )?{_NOT_A_NAME}(?P<value>.+?) tab", value="tab name")
def close_tab(name: str):
    return desktop.close_tab(name)
