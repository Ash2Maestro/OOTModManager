"""A second test-only layout exercises the core without Longshot file conventions."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ast

from modmanager.engines import BuildRequest, get_engine
from modmanager.engines.longshot import LongshotBackend
from modmanager.pipeline import REPORT, build_command, inventory, write_json
from modmanager.deployment import replace_installation
from modmanager.reuse import cache_build, restore_build, native_key
from modmanager.state import normalize_report


class AlternateBackend(LongshotBackend):
    """Test double only: not an advertised or playable second engine."""

    id = "test-engine"
    name = "Test engine"
    layout = replace(LongshotBackend.layout, executables=("run.exe",), image="guest.bin",
                     version="release.txt", stored_exefs=".inputs", native_roots=("runtime", ".inputs"),
                     preferences=("preferences.ini",), audit_file="guest-audit.json",
                     extra_files=(), library_roots=("runtime",))

    def build_command(self, request: BuildRequest) -> list[str]:
        return ["test-compiler", str(request.tools), str(request.game), str(request.jobs)]

    def native_cache_options(self, report: dict) -> dict:
        return report.get("build_options", {})


class EngineBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        registry = patch.dict("modmanager.engines._FACTORIES", {AlternateBackend.id: AlternateBackend})
        registry.start()
        self.addCleanup(registry.stop)

    def test_unknown_engine_does_not_fall_back(self):
        with self.assertRaisesRegex(ValueError, "Moteur non pris en charge"):
            get_engine("not-installed")

    def test_layout_paths_are_relative_and_portable(self):
        with self.assertRaises(ValueError):
            replace(LongshotBackend.layout, image="../outside.bin")
        with self.assertRaises(ValueError):
            replace(LongshotBackend.layout, executables=())
        with self.assertRaises(ValueError):
            replace(LongshotBackend.layout, native_roots=("romfs",))

    def test_core_build_command_uses_the_selected_backend(self):
        report = {"engine": AlternateBackend.id, "tools_path": str(self.root / "tools"),
                  "romfs": str(self.root / "romfs"), "game_dir": str(self.root / "game")}
        self.assertEqual(build_command(self.root, report, 3, None),
                         ["test-compiler", str(self.root / "tools"), str(self.root / "game"), "3"])

    def test_native_cache_is_scoped_to_engine_and_rejects_cross_restore(self):
        game = self.root / "game"
        game.mkdir()
        (game / "run.exe").write_bytes(b"native")
        (game / "guest.bin").write_bytes(b"guest")
        workspace = self.root / "workspace"
        (workspace / "prepared/exefs").mkdir(parents=True)
        (workspace / "prepared/exefs/main").write_bytes(b"input")
        report = {"engine": AlternateBackend.id}
        key = native_key(workspace, report, "tools", "fr")
        self.assertNotEqual(key, native_key(workspace, {"engine": "longshot"}, "tools", "fr"))
        self.assertNotEqual(key, native_key(workspace, {"engine": AlternateBackend.id,
                            "build_options": {"cpu": "different"}}, "tools", "fr"))
        cache = self.root / "cache"
        cache_build(cache, key, game, engine_id=AlternateBackend.id)
        destination = self.root / "blocked"
        with self.assertRaisesRegex(ValueError, "autre moteur"):
            restore_build(cache, key, workspace, {"engine": "longshot"}, destination)
        self.assertFalse(destination.exists())

    def test_transaction_rolls_back_a_different_layout(self):
        game = self.root / "game"
        (game / "romfs").mkdir(parents=True)
        for name, value in {"run.exe": b"old-native", "guest.bin": b"old-image", "preferences.ini": b"user"}.items():
            (game / name).write_bytes(value)
        workspace = self.root / "workspace"
        workspace.mkdir()
        report = {"engine": AlternateBackend.id, "tools_path": str(self.root / "tools"),
                  "variant": "manual-shield", "source": str(self.root / "source.nup")}
        write_json(workspace / REPORT, report)
        before = inventory(game)
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with replace_installation(workspace, report, game):
                (game / "run.exe").write_bytes(b"new-native")
                (game / "guest.bin").write_bytes(b"new-image")
                raise RuntimeError("interrupted")
        self.assertEqual(inventory(game), before)

    def test_existing_preparation_metadata_migrates_without_mutating_input(self):
        report = {"longshot": "tools", "preserve_longshot_settings": True, "inventory": {"prepared": {}}}
        migrated = normalize_report(report)
        self.assertEqual(migrated["engine"], "longshot")
        self.assertEqual(migrated["tools_path"], "tools")
        self.assertTrue(migrated["preserve_runtime_settings"])
        self.assertNotIn("longshot", migrated)
        self.assertIn("longshot", report)
        self.assertEqual(migrated["inventory"], report["inventory"])

    def test_preservation_uses_backend_library_roots(self):
        game = self.root / "game"
        for folder in ("romfs", "runtime"):
            (game / folder).mkdir(parents=True)
        (game / "run.exe").write_bytes(b"native")
        (game / "guest.bin").write_bytes(b"guest")
        (game / "runtime/plugin.dll").write_bytes(b"installed-library")
        workspace = self.root / "workspace"
        workspace.mkdir()
        report = {"engine": AlternateBackend.id, "tools_path": str(self.root / "tools"),
                  "variant": "manual-shield", "preserve_runtime_settings": True}
        write_json(workspace / REPORT, report)
        with replace_installation(workspace, report, game):
            (game / "runtime").mkdir()
            (game / "runtime/plugin.dll").write_bytes(b"generated-default")
        self.assertEqual((game / "runtime/plugin.dll").read_bytes(), b"installed-library")

    def test_launch_prefers_root_launcher_over_internal_binary(self):
        game = self.root / "game"
        (game / "bin").mkdir(parents=True)
        (game / "longshot.exe").touch()
        (game / "bin/longshot.exe").touch()
        self.assertEqual(get_engine().launch_command(game), [str(game / "longshot.exe")])

    def test_core_has_no_import_of_a_concrete_backend(self):
        root = (Path(__file__).resolve().parents[2] / "src/core")
        files = [root / "manager_worker.py", *(root / "modmanager" / name for name in
                 ("pipeline.py", "models.py", "deployment.py", "reuse.py", "build_cache.py"))]
        for path in files:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn("longshot", node.module or "", str(path))

    def test_wheel_setting_does_not_affect_unrelated_mods(self):
        from modmanager.engines import ModRequest
        request = ModRequest(self.root, self.root, "manual-shield", True, 100, "python")
        self.assertEqual(get_engine().installed_mod_settings({}, self.root, request, None), (True, True))
