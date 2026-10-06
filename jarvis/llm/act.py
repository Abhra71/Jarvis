"""The executor: the brain's steps (jarvis/llm/understand.py) -> the existing hands (jarvis/skills, abilities).

The brain says WHAT ("close this tab", "right-click the class Oval and delete it"); this module turns each step
into one or more tool calls, in code, with no AI. Every call goes through Skills.call, so every existing safety rule
applies (a yes before delete/send/buy/post, secrets files off-limits, the dialog guard).

calls(step) is pure (no screen), so it is unit-tested on every kind of step; run(steps) does them in order and stops
at the first one that doesn't happen, with the hands' own words for why.
"""

import re

_SITES = {"youtube": "youtube", "amazon": "amazon", "github": "github", "maps": "maps", "google": "google"}
_DONT = ("Not ", "Needs confirmation", "Unknown tool", "Bad ")


def _url(site: str) -> str:
    s = site.strip()
    if re.match(r"^https?://", s):
        return s
    if "." not in s:
        s += ".com"
    return "https://" + s


def calls(step: dict, front: str = "") -> list[tuple[str, dict]] | str:
    """The tool calls for one step, or a plain sentence when this step can't be done yet (said to the user)."""
    do = step.get("do", "")
    g = step.get
    front_l = (front or "").lower()
    if do == "open_app":
        return [("open_app", {"name": g("app") or g("value", "")})]
    if do == "open_site":
        site, browser = str(g("site", "")), str(g("browser") or "").lower()
        if browser and "chrome" not in browser:
            return [("open_app", {"name": browser}), ("address_bar", {"text": site})]
        args = {"url": _url(site)}
        if g("profile"):
            args["profile"] = str(g("profile"))
        return [("open_website", args)]
    if do == "chrome_profile":
        return [("open_chrome", {"profile": str(g("profile", ""))})]
    if do == "tab":
        action, which, count = str(g("action", "")), str(g("which") or ""), int(g("count") or 1)
        if action == "new":
            return [("browser", {"action": "new_tab", "times": count})]
        if action == "switch":
            return [("browser", {"action": "next_tab", "times": count})]
        if action == "close_matching" and which:
            return [("close_tab_named", {"name": which, "all": True})]
        if action == "close_others":
            return "Closing all the other tabs isn't something I can do yet."
        if action == "close":
            if which and which not in ("current", "this", "it"):
                if which.isdigit() or which in ("last", "2", "two"):
                    return [("browser", {"action": "close_tab", "times": count})]
                return [("close_tab_named", {"name": which, "all": False})]
            return [("browser", {"action": "close_tab", "times": count})]
    if do == "window":
        action, target, side = str(g("action", "")), str(g("target") or ""), str(g("side") or "")
        if action == "snap":
            pre = [("window", {"app": target, "action": "focus"})] if target else []
            return pre + [("do", {"ability": "snap_right" if side.startswith("r") else "snap_left"})]
        if action == "minimize_all":
            return [("press_key", {"key": "win+d"})]
        if action == "show_all":
            return [("do", {"ability": "task_view"})]
        if action == "move_monitor":
            pre = [("window", {"app": target, "action": "focus"})] if target else []
            return pre + [("do", {"ability": "other_screen"})]
        if action in ("minimize", "maximize", "close", "focus", "restore"):
            if target and target.lower() not in ("this", "current", "screen", "window"):
                return [("window", {"app": target, "action": action})]
            if action == "close":
                return [("press_key", {"key": "alt+f4"})]
            if action in ("minimize", "maximize"):
                return [("do", {"ability": f"{action}_front"})]
    if do == "click":
        return [("click_element", {"name": str(g("target", "")), "double": bool(g("double"))})]
    if do == "type":
        out = [("click_element", {"name": str(g("into"))})] if g("into") else []
        return out + [("type_text", {"text": str(g("text", ""))})]
    if do == "keys":
        return [("press_key", {"key": str(g("keys", ""))})]
    if do == "scroll":
        d = str(g("direction", "down"))
        if d in ("top", "bottom"):
            return [("browser", {"action": d})]
        return [("scroll", {"direction": d if d in ("up", "down") else "down"})]
    if do == "search":
        site = str(g("site") or "").lower()
        if site and site not in _SITES and site.split(".")[0] in front_l:
            return [("site_search", {"query": str(g("query", ""))})]  # the site in front has its own search box
        return [("web_search", {"query": str(g("query", "")), "site": _SITES.get(site.split(".")[0], "google")})]
    if do == "play":
        return [("youtube", {"command": f"play {g('query', '')}"})]
    if do == "media":
        action, secs = str(g("action", "")), g("seconds")
        on_youtube = "youtube" in front_l
        yt = {"play": "play", "pause": "pause", "fullscreen": "full screen", "exit_fullscreen": "exit full screen",
              "skip_ad": "skip ad", "next": "next video"}
        if action == "seek":
            return [("youtube", {"command": f"forward {int(secs or 10)} seconds" if int(secs or 10) >= 0
                                 else f"back {-int(secs)} seconds"})]
        if on_youtube and action in yt:
            return [("youtube", {"command": yt[action]})]
        if action in ("play", "pause"):
            return [("media", {"action": "play_pause"})]
        if action == "next":
            return [("media", {"action": "next"})]
        if action in yt:
            return [("youtube", {"command": yt[action]})]
    if do == "volume":
        if g("mute") is not None and g("level") is None and g("change") is None:
            return [("volume", {"action": "mute" if g("mute") else "unmute"})]
        if g("level") is not None:
            return [("volume", {"action": "set", "level": int(g("level"))})]
        return [("volume", {"action": "up" if str(g("change", "up")) == "up" else "down"})]
    if do == "display":
        out = []
        if g("night_light"):
            out.append(("do", {"ability": "switch_setting", "value": f"night light {g('night_light')}"}))
        if g("brightness") is not None:
            out.append(("do", {"ability": "set_brightness", "value": str(g("brightness"))}))
        return out or "Which display setting should I change?"
    if do == "bluetooth":
        ability = "disconnect_bluetooth" if g("connect") is False else "connect_bluetooth"
        return [("do", {"ability": ability, "value": str(g("device", ""))})]
    if do == "settings":
        return [("do", {"ability": "open_settings", "value": str(g("page") or "")})]
    if do == "folder":
        return [("do", {"ability": "open_folder", "value": str(g("folder", ""))})]
    if do == "file":
        if g("newest"):
            return [("do", {"ability": "find_newest", "value": str(g("newest"))})]
        return [("do", {"ability": "open_file_here", "value": str(g("name") or g("size") or "")})]
    if do == "timer":
        return [("timer", {"action": "start", "seconds": int(g("seconds") or 60)})]
    if do == "pw":
        target, subject, year = str(g("target", "batch")), str(g("subject") or ""), str(g("year") or "")
        if target == "khazana" or g("khazana"):
            return [("do", {"ability": "pw_khazana", "value": f"{subject} {year}".strip()})]
        if subject:
            return [("do", {"ability": "pw_subject", "value": subject})]
        return [("do", {"ability": "pw_batch"})]
    if do == "bluej":
        action, name = str(g("action", "")), str(g("name", ""))
        if action == "new_class":
            return [("do", {"ability": "bluej_new_class", "value": name})]
        if action == "open_class":
            return [("do", {"ability": "bluej_open_class", "value": name})]
        if action == "delete_class":
            return [("right_click", {"name": name, "kind": "class"}), ("choose_menu_item", {"name": "Remove"})]
    if do == "upload":
        return [("do", {"ability": "upload_file", "value": str(g("file", ""))})]
    if do == "mouse":
        if g("action") == "double_click":
            return [("click_element", {"name": str(g("target", "")), "double": True})] if g("target") else \
                "Double-click on what?"
        return "Moving the mouse by itself isn't something I do yet; tell me what to click."
    if do == "chess":
        return "Chess moves come with chess mode, which isn't built yet."
    if do == "screen":
        return [("look_at_screen", {})]
    return f"I don't know how to do '{do}' yet."


def run(steps: list[dict], skills, front: str = "") -> tuple[bool, list[str]]:
    """Do the steps in order. (all done, what each call said). Stops at the first call that didn't happen."""
    said = []
    for step in steps:
        plan = calls(step, front)
        if isinstance(plan, str):
            return False, said + [plan]
        for tool, args in plan:
            out = skills.call(tool, args)
            text = out.get("text", "") if isinstance(out, dict) else str(out)
            said.append(text)
            if text.startswith(_DONT):
                return False, said
    return True, said
