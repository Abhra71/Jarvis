"""The agent core (jarvis/agent): snapshot, checks, plans, execute + verify + repair + ask. A fake desktop,
never the real screen."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jarvis.usage
from jarvis.agent import checks, context, plan as planmod
from jarvis.agent.run import Agent
from jarvis.skills.elements import Element


def setUpModule():
    jarvis.usage.usage.persist = False


def _el(name, kind="button"):
    return Element(kind, name, (10, 10, 60, 30))


def _real_tools():
    from jarvis.skills import Skills
    with mock.patch("jarvis.skills.AppLauncher"), mock.patch("jarvis.skills.Browser"):
        return Skills({"volume": {"step": 10}, "apps": {}}, announce=print).tools


TOOLS = _real_tools()


class FakeDesktop:
    """A pretend PC: tools change its state, the snapshot readers read it."""

    def __init__(self):
        self.front = "chrome: New Tab - Google Chrome"
        self.windows = [self.front]
        self.items = []
        self.focus = "document"
        self.url = None
        self.ocr = []
        self.dialog = ""
        self.fullscreen = False
        self.playing = None
        self.calls = []
        self.confirmed = False
        self.tools = TOOLS
        self.effects = {}   # tool name -> fn(args) -> result

    def readers(self):
        return context.Readers(front=lambda: self.front, windows=lambda: list(self.windows),
                               items=lambda: list(self.items), url=lambda: self.url, focus=lambda: self.focus,
                               ocr=lambda: list(self.ocr), dialog=lambda: self.dialog,
                               fullscreen=lambda: self.fullscreen, playing=lambda: self.playing)

    def open(self, app, items=()):
        self.front = f"{app.lower()}: {app}"
        self.windows.insert(0, self.front)
        self.items = [_el(n, k) for n, k in items]

    def call(self, name, args):
        self.calls.append((name, args))
        fx = self.effects.get(name)
        return fx(args) if fx else "Done."


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _agent(desk, answers, tmp):
    """An agent whose AI returns `answers` in order (each a dict = JSON plan)."""
    answers = list(answers)
    think = mock.Mock(side_effect=lambda system, user: json.dumps(answers.pop(0)))
    clock = Clock()
    a = Agent(desk, think, narrate=mock.Mock(), readers=desk.readers(),
              memory=planmod.PlanMemory(Path(tmp) / "plans.json"), sleep=clock.sleep, clock=clock)
    return a, think


class ChecksTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(checks.parse("window: WhatsApp"), checks.Check("window", "WhatsApp"))
        self.assertEqual(checks.parse({"element": "Search"}), checks.Check("element", "Search"))
        self.assertEqual(checks.parse("not text: Loading"), checks.Check("text", "Loading", True))
        self.assertEqual(checks.parse('title = "YouTube"'), checks.Check("window", "YouTube"))
        self.assertIsNone(checks.parse(""))
        for bad in ("nonsense", "colour: red", "window:"):
            with self.assertRaises(checks.BadCheck, msg=bad):
                checks.parse(bad)

    def test_holds(self):
        desk = FakeDesktop()
        desk.front = "code: main.cpp - Visual Studio Code"
        desk.windows = [desk.front, "whatsapp: WhatsApp"]
        desk.items = [_el("Search or start new chat", "field"), _el("Mom", "list item")]
        desk.url = None
        snap = context.take(desk.readers())
        yes = ["window: vs code", "window: Visual Studio Code", "open: WhatsApp", "closed: YouTube",
               "element: search or start new chat", "text: Mom", "not text: Dad"]
        no = ["window: WhatsApp", "open: Spotify", "closed: WhatsApp", "element: Send", "url: youtube"]
        for c in yes:
            self.assertTrue(checks.holds(checks.parse(c), snap), c)
        for c in no:
            self.assertFalse(checks.holds(checks.parse(c), snap), c)
        desk.focus = "field"
        self.assertTrue(checks.holds(checks.parse("focus: field"), context.take(desk.readers())))

    def test_ocr_is_the_last_resort_for_text(self):
        desk = FakeDesktop()
        desk.ocr = ["Match found", "Kick off"]
        desk.readers_ocr = mock.Mock()
        snap = context.take(desk.readers())
        self.assertTrue(checks.holds(checks.parse("text: kick off"), snap))
        self.assertEqual(checks.explain(checks.parse("window: WhatsApp"), snap), "WhatsApp isn't in front; chrome is.")


class SnapshotTest(unittest.TestCase):
    def test_lazy_and_read_once(self):
        items = mock.Mock(return_value=[_el("OK")])
        snap = context.take(context.Readers(front=lambda: "notepad: a.txt", windows=list, items=items,
                                            url=lambda: None, focus=lambda: "document", ocr=list, dialog=str,
                                            fullscreen=bool, playing=lambda: None))
        self.assertIn("Front window: notepad: a.txt", snap.text())
        snap.items, snap.items
        items.assert_called_once()

    def test_never_reads_a_secrets_window(self):
        items = mock.Mock(return_value=[_el("OK")])
        snap = context.take(context.Readers(front=lambda: "notepad: .env - Notepad", windows=list, items=items,
                                            url=lambda: None, focus=lambda: "document", ocr=list, dialog=str,
                                            fullscreen=bool, playing=lambda: None))
        self.assertEqual(snap.items, [])
        items.assert_not_called()

    def test_a_broken_reader_is_just_empty(self):
        snap = context.take(context.Readers(front=lambda: "x: y", windows=list, items=mock.Mock(side_effect=OSError),
                                            url=lambda: None, focus=lambda: "none", ocr=list, dialog=str,
                                            fullscreen=bool, playing=lambda: None))
        self.assertEqual(snap.items, [])

    def test_memory_knows_it(self):
        m = context.Memory()
        m.add("open whatsapp", "Opened WhatsApp.")
        m.it = "WhatsApp"
        self.assertIn('"it"/"that" = WhatsApp', m.text())


class PlanTest(unittest.TestCase):
    def test_parse_a_good_plan(self):
        raw = ('Sure! ```json\n{"steps": [{"do": "open_app", "args": {"name": "whatsapp"}, "expect": "window: WhatsApp",'
               ' "say": "Opening WhatsApp"}, {"do": "snap_left"}], "reply": "Done."}\n```')
        p = planmod.parse(raw, TOOLS)
        self.assertEqual([s.tool for s in p.steps], ["open_app", "do"])
        self.assertEqual(p.steps[1].args, {"ability": "snap_left"})
        self.assertEqual(p.steps[0].check, checks.Check("window", "WhatsApp"))
        self.assertEqual(p.steps[0].say, "Opening WhatsApp")

    def test_bad_plans(self):
        for raw in ('{"steps": [{"do": "teleport"}]}', '{"steps": [{"do": "volume", "args": {"action": "loud"}}]}',
                    '{"steps": [{"do": "open_app", "args": {"name": "x"}, "expect": "vibes: good"}]}',
                    "no json here", '{"steps": []}'):
            with self.assertRaises(planmod.PlanError, msg=raw):
                planmod.parse(raw, TOOLS)

    def test_front_window_abilities_focus_the_named_window_first(self):
        p = planmod.parse('{"steps": [{"do": "snap_left", "args": {"value": "Google Chrome"}}]}', TOOLS)
        self.assertEqual([(s.tool, s.args) for s in p.steps],
                         [("window", {"app": "Google Chrome", "action": "focus"}), ("do", {"ability": "snap_left"})])
        self.assertEqual(p.steps[0].check, checks.Check("window", "Google Chrome"))

    def test_window_moves_by_app_name_need_no_ai(self):
        p = planmod.code_plan("Snap Chrome left and VS Code right")
        self.assertEqual([s.label() for s in p.steps], ["window(app='chrome', action='focus')", "snap_left",
                                                        "window(app='vs code', action='focus')", "snap_right"])
        self.assertEqual([s.label() for s in planmod.code_plan("snap left and maximize").steps],
                         ["snap_left", "maximize_front"])
        self.assertIsNone(planmod.code_plan("snap chrome left and open notepad"))  # a part the code can't do

    def test_youtube_code_plans(self):
        from jarvis.skills.sites import youtube
        p = planmod.code_plan("play lofi on youtube and make it full screen")
        self.assertEqual([s.args for s in p.steps], [{"command": "play lofi on youtube"},
                                                     {"command": "make it full screen"}])
        p = planmod.code_plan("pause, go back 30 seconds, and turn on subtitles", front="chrome: X - YouTube")
        self.assertEqual(len(p.steps), 3)
        self.assertIsNone(planmod.code_plan("pause and turn on subtitles", front="notepad: a.txt"))
        self.assertTrue(youtube.understands("play the second video"))
        self.assertFalse(youtube.understands("play it again"))  # context: the AI decides

    def test_pictures_go_to_the_seeing_loop(self):
        with self.assertRaises(planmod.NeedsEyes):
            planmod.parse('{"steps": [{"do": "click", "args": {"x": 1, "y": 2, "target": "t"}}]}', TOOLS)
        with self.assertRaises(planmod.NeedsEyes):
            planmod.parse('{"need_eyes": true}', TOOLS)

    def test_code_plans_need_no_ai(self):
        p = planmod.code_plan("snap left and maximize")
        self.assertEqual([s.args["ability"] for s in p.steps], ["snap_left", "maximize_front"])
        self.assertEqual(p.source, "code")
        self.assertIsNone(planmod.code_plan("snap left and open notepad"))
        self.assertIsNone(planmod.code_plan("snap left"))  # one part: abilities.handle's job

    def test_prompt_is_compact(self):
        system, user = planmod.planning_prompt("open whatsapp", TOOLS, "Front window: x", "", "", False)
        self.assertLess(len(system), 6000)
        self.assertNotIn("look_at_screen", system)
        self.assertIn("open_app(name)", system)


WHATSAPP_PLAN = {"steps": [
    {"do": "open_app", "args": {"name": "whatsapp"}, "expect": "window: WhatsApp", "say": "Opening WhatsApp"},
    {"do": "click_element", "args": {"name": "Search or start new chat"}, "expect": "focus: field"},
    {"do": "type_text", "args": {"text": "Mom"}, "expect": "element: Mom"},
    {"do": "click_element", "args": {"name": "Mom"}, "expect": "focus: field"},
    {"do": "type_text", "args": {"text": "I'll be late"}},
    {"do": "press_key", "args": {"key": "enter"}}],
    "reply": "Sent your message to Mom."}


def _whatsapp_world(desk):
    def open_app(args):
        desk.open("WhatsApp", [("Search or start new chat", "field")])
        return "Opened WhatsApp."

    def click_element(args):
        desk.focus = "field"
        return f"Clicked the {args['name']}."

    def type_text(args):
        if args["text"] == "Mom":
            desk.items.append(_el("Mom", "list item"))
        return "Typed it."

    def press_key(args):
        if args["key"] == "enter" and not desk.confirmed:
            return ("Needs confirmation: this would press Enter in a chat or mail window, which sends the message. "
                    "Nothing was done. Ask the user one short yes/no question, and do it only after they say yes.")
        return "Pressed enter."

    desk.effects = {"open_app": open_app, "click_element": click_element, "type_text": type_text,
                    "press_key": press_key}


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_whatsapp_message_asks_before_sending_then_sends_on_yes(self):
        desk = FakeDesktop()
        _whatsapp_world(desk)
        agent, think = _agent(desk, [WHATSAPP_PLAN], self.tmp.name)
        reply = agent.run("open whatsapp and message mom I'll be late")
        self.assertEqual(reply, "Your message is ready. Shall I send it?")
        self.assertEqual(think.call_count, 1)
        agent.narrate.assert_called_once_with("Opening WhatsApp")
        self.assertEqual(agent.last.result, "needs_yes")
        self.assertTrue(agent.has_pending())
        desk.confirmed = True  # the user said yes (brain sets Skills.confirmed)
        # Enter can't be checked yet (the WhatsApp ability will): said honestly, not "Sent your message".
        self.assertEqual(agent.resume(), "Pressed enter. I couldn't confirm it worked on screen.")
        self.assertEqual(desk.calls[-1], ("press_key", {"key": "enter"}))
        self.assertFalse(agent.has_pending())
        self.assertEqual(agent.memory.plans, {})  # plans that send are never replayed without thinking

    def test_a_failed_check_gets_one_repair_and_the_fix_is_remembered(self):
        desk = FakeDesktop()
        desk.effects["open_app"] = lambda a: "Opened Spotify."  # says so, but nothing opens
        desk.effects["open_website"] = lambda a: (desk.open("Spotify - Web Player", [("Search", "field")]),
                                                  "Opened it.")[1]
        first = {"steps": [{"do": "open_app", "args": {"name": "spotify"}, "expect": "window: Spotify"}],
                 "reply": "Spotify is open."}
        fix = {"steps": [{"do": "open_website", "args": {"url": "https://open.spotify.com"},
                          "expect": "window: Spotify"}], "reply": "Opened Spotify on the web."}
        agent, think = _agent(desk, [first, fix], self.tmp.name)
        self.assertEqual(agent.run("start spotify for me"), "Opened Spotify on the web.")
        self.assertEqual((agent.last.result, agent.last.ai_calls), ("done", 2))
        self.assertIn("isn't in front", think.call_args_list[1][0][1])  # the repair was told what went wrong
        # next time: straight from memory, no AI
        agent2, think2 = _agent(desk, [], self.tmp.name)
        desk.open("Chrome")
        self.assertEqual(agent2.run("Start Spotify for me."), "Opened Spotify on the web.")
        think2.assert_not_called()
        self.assertEqual(agent2.last.source, "memory")

    def test_stuck_after_the_repair_asks_one_clear_question(self):
        desk = FakeDesktop()
        desk.effects["open_app"] = lambda a: "Opened it."
        step = {"steps": [{"do": "open_app", "args": {"name": "whatsapp"}, "expect": "window: WhatsApp"}]}
        agent, think = _agent(desk, [step, step], self.tmp.name)
        reply = agent.run("open whatsapp and show my chats")
        self.assertEqual(reply, "I'm stuck: WhatsApp isn't in front; chrome is. What should I do?")
        self.assertEqual((agent.last.result, think.call_count), ("stuck", 2))

    def test_a_failing_tool_is_not_waited_on(self):
        desk = FakeDesktop()
        desk.effects["click_element"] = lambda a: "Not clicked: Nothing called 'Mom' is on screen."
        plan = {"steps": [{"do": "click_element", "args": {"name": "Mom"}, "expect": "focus: field"}]}
        agent, _ = _agent(desk, [plan, {"ask": "Is Mom saved under another name?"}], self.tmp.name)
        self.assertEqual(agent.run("open mom's chat"), "Is Mom saved under another name?")
        self.assertLess(agent.clock(), 0.5)  # failed at once, no polling

    def test_checks_wait_for_slow_apps(self):
        desk = FakeDesktop()
        clock_steps = []

        def open_app(args):
            clock_steps.append(1)
            return "Opened VS Code."
        desk.effects["open_app"] = open_app
        plan = {"steps": [{"do": "open_app", "args": {"name": "vs code"}, "expect": "window: vs code"}],
                "reply": "VS Code is open."}
        agent, _ = _agent(desk, [plan], self.tmp.name)
        real_sleep = agent.sleep

        def sleep(s):  # the window appears after ~1 s
            real_sleep(s)
            if agent.clock() >= 1.0 and "code" not in desk.front:
                desk.open("Code", [])
                desk.front = "code: Welcome - Visual Studio Code"
        agent.sleep = sleep
        self.assertEqual(agent.run("launch vs code"), "VS Code is open.")
        self.assertGreaterEqual(agent.clock(), 1.0)

    def test_code_plan_runs_with_no_ai(self):
        desk = FakeDesktop()
        agent, think = _agent(desk, [], self.tmp.name)
        agent.run("snap left and maximize")
        think.assert_not_called()
        self.assertEqual([c[1]["ability"] for c in desk.calls], ["snap_left", "maximize_front"])

    def test_pictures_fall_back_to_the_old_loop(self):
        desk = FakeDesktop()
        agent, _ = _agent(desk, [{"need_eyes": True}], self.tmp.name)
        self.assertIsNone(agent.run("click the red thumbnail"))
        self.assertEqual(agent.last.result, "fallback")

    def test_unusable_plan_gets_one_retry(self):
        desk = FakeDesktop()
        desk.effects["volume"] = lambda a: "Muted."
        agent, think = _agent(desk, [{"steps": [{"do": "teleport"}]},
                                     {"steps": [{"do": "volume", "args": {"action": "mute"}}], "reply": "Muted."}],
                              self.tmp.name)
        self.assertEqual(agent.run("silence please"), "Muted.")
        self.assertIn("wasn't usable", think.call_args_list[1][0][1])

    def test_just_an_answer(self):
        desk = FakeDesktop()
        agent, _ = _agent(desk, [{"ask": "Which file do you mean?"}], self.tmp.name)
        self.assertEqual(agent.run("open the file"), "Which file do you mean?")
        self.assertEqual(desk.calls, [])

    def test_context_requests_are_not_remembered(self):
        desk = FakeDesktop()
        plan = {"steps": [{"do": "window", "args": {"app": "chrome", "action": "close"}}], "reply": "Closed it."}
        desk.effects["window"] = lambda a: (desk.windows.pop(0), "Closed Chrome.")[1]
        agent, _ = _agent(desk, [plan], self.tmp.name)
        agent.run("close it")
        self.assertEqual(agent.memory.plans, {})
        self.assertEqual(agent.context.it, "chrome")


class HonestyTest(unittest.TestCase):
    """29 Sep, live: 'Click F and resume the video' was reported as done; nothing had happened."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.desk = FakeDesktop()
        self.desk.front = "chrome: PW Video Player - Google Chrome"
        self.desk.windows = [self.desk.front]

    PLAN = {"steps": [{"do": "press_key", "args": {"key": "f"},
                       "expect": "window: chrome: PW Video Player - Google Chrome"},
                      {"do": "press_key", "args": {"key": "space"},
                       "expect": "window: chrome: PW Video Player - Google Chrome"}],
            "reply": "Video resumed in fullscreen."}

    def test_keys_that_did_nothing_are_not_claimed(self):
        self.desk.playing = False
        self.desk.effects["press_key"] = lambda a: f"Pressed {a['key']}."
        agent, _ = _agent(self.desk, [self.PLAN, {"ask": "Is the video player in front?"}], self.tmp.name)
        reply = agent.run("click F and resume the video")
        self.assertNotIn("resumed", reply.lower())
        self.assertEqual(reply, "Is the video player in front?")  # full screen never came true: repair, then ask
        self.assertEqual(agent.memory.plans, {})

    def test_keys_that_worked_are_checked_by_code(self):
        self.desk.playing = False

        def press(a):
            if a["key"] == "f":
                self.desk.fullscreen = True
            if a["key"] == "space":
                self.desk.playing = True
            return f"Pressed {a['key']}."
        self.desk.effects["press_key"] = press
        agent, _ = _agent(self.desk, [self.PLAN], self.tmp.name)
        self.assertEqual(agent.run("click F and resume the video"), "Video resumed in fullscreen.")
        self.assertEqual(agent.last.result, "done")
        self.assertIn("click f and resume the video", agent.memory.plans)  # verified: remembered

    def test_a_dialog_blocks_keys_until_answered(self):
        self.desk.dialog = "pw.live says"
        self.desk.playing = False

        def click(a):
            self.desk.dialog = ""
            return "Clicked the Cancel button."

        def press(a):
            self.desk.playing = True
            return "Pressed k."
        self.desk.effects.update(click_element=click, press_key=press)
        plan = {"steps": [{"do": "press_key", "args": {"key": "k"}, "expect": "playing"}], "reply": "Resumed."}
        fix = {"steps": [{"do": "click_element", "args": {"name": "Cancel"}, "expect": "not dialog"},
                         {"do": "press_key", "args": {"key": "k"}, "expect": "playing"}], "reply": "Resumed."}
        agent, think = _agent(self.desk, [plan, fix], self.tmp.name)
        self.assertEqual(agent.run("resume the video"), "Resumed.")
        self.assertIn("dialog box is open", think.call_args_list[1][0][1])
        self.assertEqual([c[0] for c in self.desk.calls], ["click_element", "press_key"])  # no key behind the dialog

    def test_unchecked_steps_are_said_honestly(self):
        self.desk.effects["press_key"] = lambda a: "Pressed f5."
        plan = {"steps": [{"do": "press_key", "args": {"key": "f5"}}], "reply": "Refreshed the page."}
        agent, _ = _agent(self.desk, [plan], self.tmp.name)
        self.assertEqual(agent.run("refresh"), "Pressed f5. I couldn't confirm it worked on screen.")
        self.assertEqual(agent.last.result, "unconfirmed")

    def test_clicked_item_is_not_its_own_proof(self):
        c = checks.parse("element: Cancel")
        snap = context.take(self.desk.readers())
        self.assertIsNone(checks.auto_check("click_element", {"name": "Cancel"}, c, snap))
        self.assertIsNone(checks.auto_check("press_key", {"key": "k"}, checks.parse("text: Playing"), snap))

    def test_closing_one_of_two_windows_counts(self):
        self.desk.windows = ["chrome: A - Google Chrome", "chrome: B - Google Chrome"]
        before = context.take(self.desk.readers())
        self.assertFalse(checks.proves_nothing(checks.parse("closed: chrome"), before))  # reads it now, as run.py does
        self.desk.windows = ["chrome: B - Google Chrome"]
        after = context.take(self.desk.readers())
        self.assertTrue(checks.holds(checks.parse("closed: chrome"), after, before))

    def test_a_repair_never_repeats_the_failed_step(self):
        self.desk.front = "explorer: Desktop"
        self.desk.effects["click_element"] = lambda a: "Clicked the Google Chrome item."
        step = {"do": "click_element", "args": {"name": "Google Chrome"}, "expect": "window: chrome"}
        agent, _ = _agent(self.desk, [{"steps": [step]}, {"steps": [step]}], self.tmp.name)
        reply = agent.run("reopen chrome")
        self.assertTrue(reply.startswith("I'm stuck"))
        self.assertEqual(len(self.desk.calls), 1)

    def test_parse_media_checks(self):
        self.assertEqual(checks.parse("paused"), checks.Check("playing", "", True))
        self.assertEqual(checks.parse("not fullscreen"), checks.Check("fullscreen", "", True))
        self.assertEqual(checks.parse({"playing": True}), checks.Check("playing"))


class LiveFindingsTest(unittest.TestCase):
    """30 Sep live runs."""

    def test_multi_command_requests_skip_the_site_pack(self):
        from jarvis.skills import sites
        self.assertTrue(sites.several_commands("pause, go back 30 seconds, and turn on subtitles"))
        self.assertFalse(sites.several_commands("play rock and roll songs on youtube"))
        self.assertFalse(sites.several_commands("search tom and jerry"))
        with mock.patch.object(sites.youtube, "handle") as pack:
            self.assertIsNone(sites.handle("pause and mute", None))
        pack.assert_not_called()

    def test_play_with_a_query_is_not_a_play_pause_toggle(self):
        desk = FakeDesktop()
        desk.playing = True
        snap = context.take(desk.readers())
        self.assertIsNone(checks.auto_check("youtube", {"command": "play lofi on youtube"}, None, snap))
        self.assertEqual(checks.auto_check("youtube", {"command": "pause"}, None, snap),
                         checks.Check("playing", "", True))


class GroundedReplyTest(unittest.TestCase):
    def test_the_plans_claim_needs_a_seen_result(self):
        """30 Sep: a Google search, then "Opened the Physics Wallah chemistry batch page"."""
        desk = FakeDesktop()
        desk.effects["web_search"] = lambda a: "Searching google for pw chemistry."
        plan = {"steps": [{"do": "web_search", "args": {"query": "pw chemistry"}}],
                "reply": "Opened the Physics Wallah chemistry batch page."}
        with tempfile.TemporaryDirectory() as tmp:
            agent, _ = _agent(desk, [plan], tmp)
            self.assertEqual(agent.run("open physics wallah, my batch, chemistry"), "Searching google for pw chemistry.")

    def test_the_claim_is_said_when_the_result_was_seen(self):
        desk = FakeDesktop()
        desk.effects["open_website"] = lambda a: (desk.open("PW Chemistry - Google Chrome"), "Opened it.")[1]
        plan = {"steps": [{"do": "open_website", "args": {"url": "https://pw.live"}, "expect": "window: Chemistry"}],
                "reply": "Your chemistry page is open."}
        with tempfile.TemporaryDirectory() as tmp:
            agent, _ = _agent(desk, [plan], tmp)
            self.assertEqual(agent.run("open pw chemistry"), "Your chemistry page is open.")


class SecretsOnScreenTest(unittest.TestCase):
    def test_secrets_windows_are_blacked_out_even_behind_the_front_one(self):
        from PIL import Image
        from jarvis.skills import desktop
        img = Image.new("RGB", (200, 100), "white")
        wins = [(1, "claude.exe", "Claude"), (2, "code.exe", ".env - Visual Studio Code")]
        with mock.patch.object(desktop, "_app_windows", return_value=wins), \
                mock.patch.object(desktop.win32gui, "IsIconic", return_value=False), \
                mock.patch.object(desktop.win32gui, "GetWindowRect", return_value=(100, 0, 200, 100)):
            self.assertEqual(desktop.blank_secret_windows(img), 1)
        self.assertEqual(img.getpixel((150, 50)), (0, 0, 0))
        self.assertEqual(img.getpixel((50, 50)), (255, 255, 255))


class OcrFindTest(unittest.TestCase):
    def test_find_words_inside_a_line(self):
        from jarvis.agent import ocr
        raw = ["L	10,10,200,20	Recents Jarvis agent core",
               "W	10,10,60,20	Recents", "W	80,10,50,20	Jarvis", "W	135,10,40,20	agent",
               "W	180,10,30,20	core",
               "L	10,50,100,20	Settings", "W	10,50,100,20	Settings"]
        lines = ocr.parse_lines(raw, scale=2.0, ox=100, oy=0)
        text, rect = ocr.find("jarvis agent core", lines)
        self.assertEqual(text, "Jarvis agent core")
        self.assertEqual(rect, (260, 20, 520, 60))  # scaled x2 and moved by the window's position
        self.assertIsNone(ocr.find("bluetooth", lines))


class BrainWiringTest(unittest.TestCase):
    def _brain(self):
        from jarvis import brain
        b = brain.Brain.__new__(brain.Brain)
        b.agent = mock.Mock()
        b.skills = mock.Mock(confirmed=False, calls_made=0)
        b.history, b.last_turn, b.cfg = [], 0.0, {}
        return b

    def test_questions_skip_the_agent(self):
        b = self._brain()
        b.agent.has_pending.return_value = False
        b.kind = "chat"
        self.assertIsNone(b._agent_turn("what's the capital of peru", False))
        b.agent.run.assert_not_called()

    def test_yes_resumes_and_no_cancels(self):
        b = self._brain()
        b.agent.has_pending.return_value = True
        b.agent.resume.return_value = "Sent."
        b.skills.confirmed = True
        b.kind = "chat"
        self.assertEqual(b._agent_turn("yes", False), "Sent.")
        b.skills.confirmed = False
        self.assertEqual(b._agent_turn("no, don't", False), "Okay, I won't.")
        b.agent.drop_pending.assert_called()

    def test_screen_requests_that_need_pictures_skip_the_agent(self):
        b = self._brain()
        b.agent.has_pending.return_value = False
        b.kind = "screen"
        self.assertIsNone(b._agent_turn("move the pawn to e4", False))
        b.kind = "action"
        b.agent.run.return_value = "Done."
        self.assertEqual(b._agent_turn("open whatsapp and message mom", False), "Done.")
        self.assertEqual(b.answered_by, "agent")


if __name__ == "__main__":
    unittest.main()
