"""The AI pipeline's reading of model answers, and the benchmark's grading (5 Oct rewrite, Phase 0)."""

import sys
import unittest
from pathlib import Path

from jarvis.llm import understand as U
from jarvis.llm.providers import parse_json, split

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import bench  # noqa: E402


class ReadAnswerTest(unittest.TestCase):
    def test_json_is_found_in_fences_and_sentences(self):
        self.assertEqual(parse_json('```json\n{"kind": "ignore"}\n```'), {"kind": "ignore"})
        self.assertEqual(parse_json('Sure! {"kind": "chat", "say": "hi {there}"} done'),
                         {"kind": "chat", "say": "hi {there}"})
        self.assertIsNone(parse_json("no json here"))

    def test_the_shapes_models_really_used_mean_the_same(self):
        # 5 Oct smoke test: three models, three shapes for the same meaning
        a = U.normalize({"kind": "act", "steps": [{"open_site": {"site": "chess.com"}}]})
        b = U.normalize({"step": "act", "steps": [{"step": "open_site", "site": "chess.com"}]})
        c = U.normalize({"kind": "act", "steps": [{"do": "chess{move}", "from": "F2", "to": "F4"}]})
        self.assertEqual(a["steps"][0]["do"], "open_site")
        self.assertEqual(a["steps"][0]["site"], "chess.com")
        self.assertEqual((b["kind"], b["steps"][0]["do"]), ("act", "open_site"))
        self.assertEqual(c["steps"][0]["do"], "chess")
        d = U.normalize({"step": "chess", "move": "f2f4", "say": "Moving."})
        self.assertEqual((d["kind"], d["steps"][0]["do"], d["steps"][0]["move"]), ("act", "chess", "f2f4"))

    def test_model_names(self):
        self.assertEqual(split("cloudflare:@cf/openai/gpt-oss-120b"), ("cloudflare", "@cf/openai/gpt-oss-120b"))
        with self.assertRaises(ValueError):
            split("gpt-4")


class GradeTest(unittest.TestCase):
    G = {"kind": "act", "intent": "volume", "must": ["mute"], "ok": []}

    def test_right_wrong_and_missing(self):
        mute = U.normalize({"kind": "act", "steps": [{"do": "volume", "mute": True}]})
        pause = U.normalize({"kind": "act", "steps": [{"do": "media", "action": "pause"}]})
        level = U.normalize({"kind": "act", "steps": [{"do": "volume", "level": 0}]})
        self.assertEqual(bench.grade(self.G, mute), "pass")
        self.assertEqual(bench.grade(self.G, pause), "wrong_action")
        self.assertEqual(bench.grade(self.G, level), "missing")
        self.assertEqual(bench.grade(self.G, None), "error")

    def test_acting_on_noise_is_the_worst_grade(self):
        noise = {"kind": "ignore", "intent": "", "must": [], "ok": []}
        self.assertEqual(bench.grade(noise, U.normalize({"kind": "act", "steps": [{"do": "open_app", "app": "WhatsApp"}]})),
                         "wrong_action")
        self.assertEqual(bench.grade(noise, U.normalize({"kind": "ask", "say": "What?"})), "wrong_kind")
        self.assertEqual(bench.grade(noise, U.normalize({"kind": "ignore"})), "pass")


if __name__ == "__main__":
    unittest.main()
