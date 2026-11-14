import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modmanager.models import choose_action
from modmanager.engines.longshot_signatures import prepared_signature
from modmanager.pipeline import inventory, write_json, REPORT
from modmanager.reuse import (native_key, cache_build, restore_build, validate_cache,
                       apply_resources, resources_match, recover_resources)


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "project"
        (self.workspace / "prepared/exefs").mkdir(parents=True)
        (self.workspace / "prepared/exefs/main").write_bytes(b"native code")
        (self.workspace / "addon/romfs").mkdir(parents=True)
        (self.workspace / "addon/romfs/texture").write_bytes(b"new texture")
        self.base = self.root / "base/romfs"
        self.base.mkdir(parents=True)
        (self.base / "base-file").write_bytes(b"original resources")
        self.game = self.root / "game"
        (self.game / "bin").mkdir(parents=True)
        (self.game / "bin/longshot.exe").write_bytes(b"native executable")
        (self.game / "longshot.exe").write_bytes(b"launcher")
        (self.game / "image.bin").write_bytes(b"native image")
        (self.game / "user").mkdir()
        (self.game / "user/save").write_bytes(b"save")
        (self.game / "longshot_options.ini").write_bytes(b"settings")
        write_json(self.game / ".hmb-owner.json", {"workspace": str(self.workspace)})
        old = self.game / "mods/00-OOT-item-wheel/romfs"
        old.mkdir(parents=True)
        (old / "texture").write_bytes(b"old texture")
        self.report = {"variant": "item-wheel", "manifest_sha256": "version-1", "audit": {"layout": []},
                       "source": str(self.root / "source.nup"), "romfs": str(self.base),
                       "installed_overlay": inventory(old.parent)}
        write_json(self.workspace / REPORT, self.report)
        self.cache = self.root / "cache"

    def test_native_identity_ignores_manifest_and_romfs_but_not_code_or_tools(self):
        key = native_key(self.workspace, self.report, "tools1", "fr-FR")
        signature = prepared_signature(self.workspace, self.report)
        self.report["manifest_sha256"] = "version-2"
        (self.workspace / "addon/romfs/texture").write_bytes(b"changed resources")
        self.assertEqual(key, native_key(self.workspace, self.report, "tools1", "fr-FR"))
        self.assertEqual(signature, prepared_signature(self.workspace, self.report))
        self.assertNotEqual(key, native_key(self.workspace, self.report, "tools2", "fr-FR"))
        self.assertEqual(key, native_key(self.workspace, self.report, "tools1", "en-US"))
        (self.workspace / "prepared/exefs/main").write_bytes(b"different code")
        self.assertNotEqual(key, native_key(self.workspace, self.report, "tools1", "fr-FR"))

    def test_resources_only_preserve_executable_saves_settings_and_other_mods(self):
        other = self.game / "mods/another-mod"
        other.mkdir()
        (other / "keep").write_bytes(b"keep")
        before = inventory(self.game)
        self.assertFalse(resources_match(self.workspace, self.report, self.game))
        apply_resources(self.workspace, self.report, self.game)
        self.assertTrue(resources_match(self.workspace, self.report, self.game))
        after = inventory(self.game)
        for name in ("bin/longshot.exe", "image.bin", "user/save", "longshot_options.ini", "mods/another-mod/keep"):
            self.assertEqual(before[name], after[name])
        self.assertTrue(list((self.game / ".hmb-overlay-backups").glob("*/romfs/texture")))

    def test_modified_overlay_is_not_silently_replaced(self):
        (self.game / "mods/00-OOT-item-wheel/romfs/texture").write_bytes(b"manual edit")
        with self.assertRaisesRegex(ValueError, "hors du gestionnaire"):
            apply_resources(self.workspace, self.report, self.game)

    def test_interrupted_swap_recovers_before_next_application(self):
        overlay = self.game / "mods/00-OOT-item-wheel"
        backup = self.game / ".hmb-overlay-backups/interrupted"
        backup.parent.mkdir()
        overlay.rename(backup)
        (overlay / "romfs").mkdir(parents=True)
        (overlay / "romfs/texture").write_bytes(b"half published new profile")
        before = (self.workspace / REPORT).read_text(encoding="utf-8")
        write_json(self.game / ".hmb-overlay-transaction.json", {
            "overlay": "mods/00-OOT-item-wheel", "staged": "mods/.hmb-new-interrupted",
            "backup": ".hmb-overlay-backups/interrupted", "had_overlay": True,
            "workspace": str(self.workspace), "old_report": before})
        recover_resources(self.game)
        self.assertEqual((overlay / "romfs/texture").read_bytes(), b"old texture")
        apply_resources(self.workspace, self.report, self.game)
        self.assertTrue(resources_match(self.workspace, self.report, self.game))

    def test_failed_swap_rolls_back_overlay_and_report(self):
        from modmanager import reuse
        original = reuse.write_json
        before = (self.workspace / REPORT).read_bytes()
        def fail_report(path, value):
            if path == self.workspace / REPORT:
                raise OSError("disk error")
            original(path, value)
        with patch.object(reuse, "write_json", side_effect=fail_report):
            with self.assertRaises(OSError):
                apply_resources(self.workspace, self.report, self.game)
        self.assertEqual((self.game / "mods/00-OOT-item-wheel/romfs/texture").read_bytes(), b"old texture")
        self.assertEqual((self.workspace / REPORT).read_bytes(), before)
        self.assertFalse((self.game / ".hmb-overlay-transaction.json").exists())

    def test_cached_build_restores_without_compiler_and_rejects_corruption(self):
        key = native_key(self.workspace, self.report, "tools", "fr-FR")
        cache_build(self.cache, key, self.game)
        dest = self.root / "restored"
        restore_build(self.cache, key, self.workspace, self.report, dest)
        self.assertEqual((dest / "bin/longshot.exe").read_bytes(), b"native executable")
        self.assertEqual((dest / "mods/00-OOT-item-wheel/romfs/texture").read_bytes(), b"new texture")
        self.assertFalse((dest / "user").exists())
        self.assertFalse((dest / "longshot_options.ini").exists())
        from modmanager.build_cache import object_path
        _, data = validate_cache(self.cache, key)
        object_path(self.cache, data["files"]["image.bin"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "modifié"):
            restore_build(self.cache, key, self.workspace, self.report, self.root / "blocked")
        self.assertFalse((self.root / "blocked").exists())

    def test_resources_plan_skips_build_and_force_overrides(self):
        args = dict(prepared=True, code_matches=True, settings_match=True, game_exists=True, resources_match=False)
        self.assertEqual(choose_action(**args).action, "resources")
        self.assertEqual(choose_action(**args, force=True).action, "build")

    def test_cache_does_not_capture_saves_or_options(self):
        key = native_key(self.workspace, self.report, "tools", "fr-FR")
        cache_build(self.cache, key, self.game)
        _, data = validate_cache(self.cache, key)
        self.assertNotIn("user/save", data["files"])
        self.assertNotIn("longshot_options.ini", data["files"])

    def worker_case(self, resources_only, custom_cache=False):
        from manager_worker import Worker
        from modmanager.models import Settings, RECEIPT
        from modmanager.pipeline import digest
        self.report.update(schema=1, status="prepared", workspace=str(self.workspace),
                           tools_path=str(self.root / "deleted-old-builder"),
                           game_dir=str(self.game), build_status="built-unverified-in-game",
                           inventory={"prepared": inventory(self.workspace / "prepared"), "addon": inventory(self.workspace / "addon")})
        manager = self.root / "manager"
        cache = self.root / "custom-native-cache" if custom_cache else manager / "cache/native-builds/longshot"
        if resources_only:
            write_json(self.workspace / "longshot-loader-audit.json",
                       {"image_sha256": digest(self.game / "image.bin")})
            write_json(self.workspace / RECEIPT, {"prepared_signature": prepared_signature(self.workspace, self.report),
                       "source_signature": "tools", "exe_sha256": digest(self.game / "bin/longshot.exe")})
        else:
            key = native_key(self.workspace, self.report, "tools", "fr-FR")
            cache_build(cache, key, self.game)
            self.report.update(game_dir=str(self.root / "restored"), build_status="not-built")
        write_json(self.workspace / REPORT, self.report)
        worker = Worker(Settings(workspace=str(self.workspace), game_dir=self.report["game_dir"], clock=False,
                                 data_root=str(manager), native_cache=str(cache) if custom_cache else ""))
        with patch.object(worker, "validate"), patch.object(worker, "load", return_value=self.report), \
             patch.object(worker, "audit"), patch.object(worker, "adapt"), \
             patch.object(worker, "run", side_effect=AssertionError("Compiler must not run")) as compiler, \
             patch("manager_worker.ROOT", manager), patch("modmanager.engines.longshot.LongshotBackend.tools_signature", return_value="tools"), \
             patch("manager_worker.subprocess.run", return_value=SimpleNamespace(stdout="", returncode=0)):
            worker.execute()
            compiler.assert_not_called()
        saved = json.loads((self.workspace / REPORT).read_text(encoding="utf-8"))
        self.assertEqual(saved["tools_path"], str(worker.tools))
        self.assertTrue(resources_match(self.workspace, self.report, Path(worker.settings.game_dir)))

    def test_worker_resources_branch_never_invokes_compiler(self):
        self.worker_case(resources_only=True)

    def test_worker_runtime_preferences_never_invokes_compiler(self):
        (self.game / "mods/00-OOT-item-wheel/romfs/texture").write_bytes(b"new texture")
        self.worker_case(resources_only=True)
        self.assertTrue((self.game / "language.txt").is_file())

    def test_worker_build_cache_hit_never_invokes_compiler(self):
        self.worker_case(resources_only=False)

    def test_worker_custom_cache_hit_never_invokes_compiler(self):
        self.worker_case(resources_only=False, custom_cache=True)
