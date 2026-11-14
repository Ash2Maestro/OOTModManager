"""Longshot-only discovery; old installations must not enter the new pipeline."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modmanager.engines.longshot_launcher import tools_candidates, default_build
from modmanager.pipeline import check_tools


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root), "LONGSHOT_TOOLS": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def test_discovers_launcher_toolchains_and_ignores_old_builder(self):
        expected = self.root / "LongshotLauncher/toolchains/v3/LongshotBuilder/tools"
        for folder in (expected, self.root / "HookshotBuilder/versions/v2/HookshotBuilder/tools"):
            for name in ("nx2/make_game.py", "python/python.exe"):
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
        self.assertEqual(tools_candidates(), [expected])

    def test_reads_selected_build_without_writing_launcher_settings(self):
        metadata = self.root / "LongshotLauncher/builds.json"
        metadata.parent.mkdir()
        builds = [{"folder": "first"}, {"folder": "selected", "default": True, "nup": "game.nup"}]
        metadata.write_text(json.dumps({"builds": builds}))
        before = metadata.read_bytes()
        self.assertEqual(default_build(), builds[1])
        self.assertEqual(metadata.read_bytes(), before)

    def test_optional_metadata_can_be_missing_or_malformed(self):
        self.assertEqual(default_build(), {})
        metadata = self.root / "LongshotLauncher/builds.json"
        metadata.parent.mkdir()
        for content in ("{", '{"builds":null}', '{"builds":[null]}'):
            metadata.write_text(content)
            self.assertEqual(default_build(), {})

    def test_old_loader_layout_alone_does_not_qualify_as_longshot(self):
        for name in ("nx2/make_game.py", "nx2/image.py", "nx2/lift.py", "nx2/standalone.py",
                     "third_party/a64-kit/tools/nso.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("class EdenImage: pass\nCODE_39BIT = 0x80000000" if name.endswith("image.py") else "")
        with self.assertRaisesRegex(ValueError, "Longshot prise en charge"):
            check_tools(self.root)
