"""Keys in .env are found however Notepad users type them (5 Oct: 'NAME = key' wasn't found)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import brain


class KeyFileTest(unittest.TestCase):
    def test_spaces_quotes_and_bom_are_fine(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text('﻿GROQ_API_KEY=abc\nNVIDIA_API_KEY = nvapi-123\nMISTRAL_API_KEY= "m-9"\n',
                                       encoding="utf-8")
            with mock.patch.object(brain, "ROOT", Path(d)), mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(brain.load_api_key("GROQ_API_KEY"), "abc")
                self.assertEqual(brain.load_api_key("NVIDIA_API_KEY"), "nvapi-123")
                self.assertEqual(brain.load_api_key("MISTRAL_API_KEY"), "m-9")
                self.assertIsNone(brain.load_api_key("CLOUDFLARE_API_TOKEN"))


if __name__ == "__main__":
    unittest.main()
