from pathlib import Path
import sys
import tempfile
import unittest
import json
from unittest.mock import patch

sys.path.insert(0, str((Path(__file__).resolve().parents[2] / "src/core")))
from modmanager.models import choose_action
from modmanager.engines.longshot_progress import LongshotProgress as Progress
from modmanager.engines.longshot_signatures import prepared_signature
from modmanager.formats import Nso, Record
from test_builder import make_nso


class GuiBackendTests(unittest.TestCase):
    def test_image_signature_masks_exactly_four_bytes_across_read_boundary(self):
        import hashlib
        from modmanager.signatures import image_digest
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.bin"
            original = b"x" * ((8 << 20) + 8)
            path.write_bytes(original)
            for offset in ((8 << 20) - 2, (8 << 20), len(original) - 4):
                with self.subTest(offset=offset):
                    expected = bytearray(original)
                    expected[offset:offset + 4] = bytes(4)
                    self.assertEqual(image_digest(path, offset), hashlib.sha256(expected).hexdigest())

    def test_shared_cache_discovery_uses_projects_and_selected_builder(self):
        from modmanager.pipeline import shared_cache_sources, REPORT, write_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            builder = root / "LongshotLauncher"
            tools = builder / "toolchains/v3/LongshotBuilder/tools"
            tools.mkdir(parents=True)
            (builder / "work/objcache").mkdir(parents=True)
            builds = root / "Builds"
            for name in ("wheel", "shield", "unowned"):
                project = builds / name
                (project / "build-work/objcache").mkdir(parents=True)
                write_json(project / REPORT, {"workspace": str(project), "tools_path": str(tools)})
                if name != "unowned":
                    write_json(project / "build-work/.hmb-owner.json", {"workspace": str(project)})
            with patch.dict("os.environ", {"LOCALAPPDATA": str(root / "redirected")}, clear=False):
                found = shared_cache_sources(tools, builds / "shield", builds)
            self.assertEqual(set(found), {builder / "work/objcache", builds / "wheel/build-work/objcache"})

    def test_audit_uses_selected_tools_instead_of_historical_path(self):
        from manager_worker import Worker
        from modmanager.models import Settings
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory).resolve() / "current-builder"
            worker = Worker(Settings(workspace=directory, tools_path=str(selected)))
            with patch.object(worker, "run") as run:
                worker.audit()
            argv = run.call_args.args[0]
            self.assertEqual(argv[argv.index("--tools") + 1], str(selected))

    def test_progress_is_per_stage_and_eta_resets(self):
        progress = Progress()
        progress.feed("@@stage compile Compiling")
        self.assertIn("469 déjà en cache", progress.feed("@@plan 17 486")["detail"])
        self.assertEqual(progress.feed("@@progress 0.32")["percent"], 32)
        self.assertEqual(progress.feed("@@eta 80")["eta"], 80)
        self.assertIn("cache", progress.feed("@@file code_001.c 0.0 cached")["detail"])
        new_stage = progress.feed("@@stage finish Installing")
        self.assertIsNone(new_stage["percent"])
        self.assertIsNone(new_stage["eta"])
        self.assertEqual(progress.feed("@@done game")["percent"], 100)

    def test_planner_avoids_build_for_settings_only(self):
        base = dict(prepared=True, code_matches=True, game_exists=True)
        self.assertEqual(choose_action(**base, settings_match=False).action, "configure")
        self.assertEqual(choose_action(**base, settings_match=True).action, "ready")
        self.assertEqual(choose_action(**base, settings_match=True, force=True).action, "build")
        self.assertEqual(choose_action(prepared=True, code_matches=False, game_exists=True, settings_match=True).action, "build")
        self.assertEqual(choose_action(prepared=False, code_matches=False, game_exists=False, settings_match=False).action, "prepare")

    def test_code_signature_ignores_only_config_word(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exefs = root / "prepared/exefs"
            exefs.mkdir(parents=True)
            module = Nso(make_nso(0x80000, 0x1E000))
            module.apply([Record(0x1E100, (100).to_bytes(4, "little"))])
            path = exefs / "subsdk1"
            path.write_bytes(module.encode())
            report = {"manifest_sha256": "synthetic", "audit": {"layout": [{"name": "subsdk1", "base": 0x80000000}]},
                      "native_adapters": [{"revision": 2, "runtime_config": 0x8001E100}]}
            before = prepared_signature(root, report)
            module.apply([Record(0x1E100, (80).to_bytes(4, "little"))])
            path.write_bytes(module.encode())
            self.assertEqual(before, prepared_signature(root, report))
            module.apply([Record(0x100, b"CODE")])
            path.write_bytes(module.encode())
            self.assertNotEqual(before, prepared_signature(root, report))
