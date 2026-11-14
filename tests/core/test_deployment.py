import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

from modmanager.deployment import replace_installation, recover_deployment, JOURNAL, STAGE, validate_target
from modmanager.pipeline import REPORT, inventory, write_json, build_command
from modmanager.reuse import cache_build, restore_build, native_key
from modmanager.deployment import ensure_game_closed


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = self.root / "one-game"
        for name in ("romfs", "user", "bin", "prompts", "mods/00-OOT-item-wheel/romfs", "mods/user-mod"):
            (self.game / name).mkdir(parents=True, exist_ok=True)
        for name, value in (("romfs/base", b"BASE ROMFS"), ("user/save", b"SAVE"),
                            ("longshot_options.ini", b"volume=42\nbutton_prompts=4\n"),
                            ("bin/longshot.exe", b"OLD EXE"), ("image.bin", b"OLD IMAGE"),
                            ("mods/00-OOT-item-wheel/romfs/old", b"wheel"), ("mods/user-mod/keep", b"keep")):
            (self.game / name).write_bytes(value)
        self.old = self.root / "old-profile"
        self.old.mkdir()
        write_json(self.old / REPORT, {"variant": "item-wheel", "installed_overlay": inventory(self.game / "mods/00-OOT-item-wheel")})
        write_json(self.game / ".hmb-owner.json", {"workspace": str(self.old)})
        self.new = self.root / "new-profile"
        (self.new / "prepared/exefs").mkdir(parents=True)
        (self.new / "prepared/exefs/main").write_bytes(b"CODE")
        (self.new / "addon/romfs").mkdir(parents=True)
        (self.new / "addon/romfs/new").write_bytes(b"shield")
        self.report = {"variant": "manual-shield", "source": str(self.root / "original.nup"),
                       "romfs": str(self.root / "external-romfs"), "tools_path": str(self.root / "tools")}
        write_json(self.new / REPORT, self.report)

    def publish(self):
        (self.game / "bin").mkdir()
        (self.game / "bin/longshot.exe").write_bytes(b"NEW EXE")
        (self.game / "image.bin").write_bytes(b"NEW IMAGE")
        (self.game / "mods/00-OOT-manual-shield/romfs").mkdir(parents=True)
        (self.game / "mods/00-OOT-manual-shield/romfs/new").write_bytes(b"shield")

    def test_mod_build_preserves_longshot_settings_and_renderer(self):
        self.report.update(preserve_runtime_settings=True, renderer_relative='bin/longshot_vk.dll')
        (self.game / 'bin/longshot_vk.dll').write_bytes(b'installed renderer with optional features')
        (self.game / 'language.txt').write_bytes(b'# custom comments\nfr-CA\n')
        (self.game / 'prompts/custom').write_bytes(b'custom prompts')
        (self.game / 'ngx').mkdir()
        (self.game / 'ngx/nvngx_dlss.dll').write_bytes(b'installed runtime')
        (self.game / 'bin/plugins').mkdir()
        (self.game / 'bin/plugins/custom.dll').write_bytes(b'custom installation component')
        before = {name: (self.game / name).read_bytes() for name in
                  ('language.txt','longshot_options.ini','bin/longshot_vk.dll','bin/plugins/custom.dll','prompts/custom','ngx/nvngx_dlss.dll')}
        with replace_installation(self.new, self.report, self.game):
            self.assertEqual(Path(self.report['prebuilt_renderer']).read_bytes(), before['bin/longshot_vk.dll'])
            self.publish()
            (self.game / 'language.txt').write_bytes(b'en-US')
            (self.game / 'longshot_options.ini').write_bytes(b'button_prompts=1')
            (self.game / 'longshot_env.txt').write_bytes(b'generated default')
            (self.game / 'bin/longshot_vk.dll').write_bytes(b'cached or compiled renderer')
            for folder in ('prompts','ngx'):
                (self.game / folder).mkdir()
                (self.game / folder / 'generated').write_bytes(b'generated resource')
        for name, expected in before.items():
            self.assertEqual((self.game / name).read_bytes(), expected, name)
        self.assertFalse((self.game / 'longshot_env.txt').exists())
        self.assertFalse((self.game / 'prompts/generated').exists())
        self.assertFalse((self.game / 'ngx/generated').exists())
        self.assertEqual((self.game / 'bin/longshot.exe').read_bytes(), b'NEW EXE')

    def test_preserved_preferences_are_recovered_after_failure(self):
        self.report.update(preserve_runtime_settings=True, renderer_relative='bin/longshot_vk.dll')
        (self.game / 'bin/longshot_vk.dll').write_bytes(b'original renderer')
        original = (self.game / 'longshot_options.ini').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            with replace_installation(self.new, self.report, self.game):
                (self.game / 'longshot_options.ini').write_bytes(b'changed')
                raise RuntimeError('failed')
        self.assertEqual((self.game / 'longshot_options.ini').read_bytes(), original)
        self.assertEqual((self.game / 'bin/longshot_vk.dll').read_bytes(), b'original renderer')

    def test_failure_while_restoring_renderer_keeps_rollback_bin_complete(self):
        import shutil
        self.report.update(preserve_runtime_settings=True, renderer_relative='bin/longshot_vk.dll')
        (self.game / 'bin/longshot_vk.dll').write_bytes(b'original renderer')
        copy = shutil.copy2
        def copy_then_fail(source, target):
            copy(source, target)
            raise RuntimeError('preservation interrupted')
        with patch('modmanager.deployment.shutil.copy2', side_effect=copy_then_fail):
            with self.assertRaisesRegex(RuntimeError, 'preservation interrupted'):
                with replace_installation(self.new, self.report, self.game):
                    self.publish()
        self.assertEqual((self.game / 'bin/longshot_vk.dll').read_bytes(), b'original renderer')
        self.assertEqual((self.game / 'bin/longshot.exe').read_bytes(), b'OLD EXE')

    def test_root_library_is_restored_after_failed_replacement(self):
        library = self.game / "SDL3.dll"
        library.write_bytes(b"OLD LIBRARY")
        with self.assertRaisesRegex(RuntimeError, "failed"):
            with replace_installation(self.new, self.report, self.game):
                self.assertFalse(library.exists())
                library.write_bytes(b"NEW LIBRARY")
                raise RuntimeError("failed")
        self.assertEqual(library.read_bytes(), b"OLD LIBRARY")

    def test_dlss_runtime_is_staged_and_restored_with_the_graphics_backend(self):
        (self.game / "ngx").mkdir()
        (self.game / "ngx/nvngx_dlss.dll").write_bytes(b"old dlss")
        with self.assertRaises(RuntimeError):
            with replace_installation(self.new, self.report, self.game):
                self.assertFalse((self.game / "ngx").exists())
                (self.game / "ngx").mkdir()
                (self.game / "ngx/nvngx_dlss.dll").write_bytes(b"new dlss")
                raise RuntimeError("failed")
        self.assertEqual((self.game / "ngx/nvngx_dlss.dll").read_bytes(),b"old dlss")

    @unittest.skipUnless(sys.platform == "win32", "Windows process inspection")
    def test_process_check_blocks_open_game_and_failed_inspection(self):
        with patch("modmanager.engines.longshot.subprocess.run", return_value=subprocess.CompletedProcess([], 0, '"longshot.exe","123"')):
            with self.assertRaisesRegex(ValueError, "Fermez Longshot"):
                ensure_game_closed()
        with patch("modmanager.engines.longshot.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "")):
            with self.assertRaisesRegex(ValueError, "Impossible de vérifier"):
                ensure_game_closed()
        with patch("modmanager.engines.longshot.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "No tasks")):
            ensure_game_closed()

    def test_replace_one_game_without_copying_romfs_or_saves(self):
        base_stat = (self.game / "romfs/base").stat()
        with replace_installation(self.new, self.report, self.game):
            self.assertEqual(self.report["romfs"], str(self.game / "romfs"))
            self.assertFalse((self.game / STAGE / "previous/romfs").exists())
            command = build_command(self.new, self.report, 6, "fr")
            self.assertEqual(command[command.index("--romfs") + 1], str(self.game / "romfs"))
            self.assertEqual(command[command.index("--out") + 1], str(self.game))
            self.publish()
        self.assertEqual((self.game / "romfs/base").stat().st_ino, base_stat.st_ino)
        self.assertEqual((self.game / "user/save").read_bytes(), b"SAVE")
        self.assertEqual((self.game / "longshot_options.ini").read_bytes(), b"volume=42\nbutton_prompts=4\n")
        self.assertEqual((self.game / "mods/user-mod/keep").read_bytes(), b"keep")
        self.assertFalse((self.game / "mods/00-OOT-item-wheel").exists())
        self.assertFalse((self.game / STAGE).exists())
        self.assertFalse((self.game / JOURNAL).exists())
        self.assertEqual(json.loads((self.game / ".hmb-owner.json").read_text())["workspace"], str(self.new))

    def test_error_rolls_back_native_files_overlay_owner_and_report(self):
        before = (self.new / REPORT).read_bytes()
        with self.assertRaisesRegex(RuntimeError, "failed"):
            with replace_installation(self.new, self.report, self.game):
                self.publish()
                raise RuntimeError("failed build")
        self.assertEqual((self.game / "bin/longshot.exe").read_bytes(), b"OLD EXE")
        self.assertEqual((self.game / "image.bin").read_bytes(), b"OLD IMAGE")
        self.assertTrue((self.game / "mods/00-OOT-item-wheel/romfs/old").is_file())
        self.assertFalse((self.game / "mods/00-OOT-manual-shield").exists())
        self.assertEqual((self.new / REPORT).read_bytes(), before)
        self.assertEqual(json.loads((self.game / ".hmb-owner.json").read_text())["workspace"], str(self.old))

    def test_cached_native_build_replaces_same_target_without_romfs_copy(self):
        cache = self.root / "cache"
        key = native_key(self.new, self.report, "tools", "fr")
        cache_build(cache, key, self.game)
        from modmanager import reuse
        real_copytree = reuse.shutil.copytree
        def guard(source, target, *args, **kwargs):
            self.assertNotEqual(Path(source), self.game / "romfs", "RomFS must never be copied")
            return real_copytree(source, target, *args, **kwargs)
        with replace_installation(self.new, self.report, self.game), patch.object(reuse.shutil, "copytree", side_effect=guard):
            restore_build(cache, key, self.new, self.report, self.game)
        self.assertTrue((self.game / "mods/00-OOT-manual-shield/romfs/new").is_file())
        self.assertEqual((self.game / "romfs/base").read_bytes(), b"BASE ROMFS")
        self.assertEqual((self.game / "user/save").read_bytes(), b"SAVE")

    def test_reject_missing_target_instead_of_creating_another_game(self):
        missing = self.root / "new-game"
        with self.assertRaisesRegex(ValueError, "existante"):
            validate_target(missing)
        self.assertFalse(missing.exists())

    def test_modified_old_overlay_is_not_overwritten(self):
        (self.game / "mods/00-OOT-item-wheel/romfs/old").write_bytes(b"user edit")
        with self.assertRaisesRegex(ValueError, "hors du gestionnaire"):
            with replace_installation(self.new, self.report, self.game):
                self.fail("must not replace")
        self.assertEqual((self.game / "bin/longshot.exe").read_bytes(), b"OLD EXE")

    def test_killed_deployment_can_restore_previous_installation(self):
        code = "from pathlib import Path; import json,sys,time; from modmanager.deployment import replace_installation; from modmanager.pipeline import REPORT; w=Path(sys.argv[1]); g=Path(sys.argv[2]); r=json.loads((w/REPORT).read_text());\nwith replace_installation(w,r,g):\n (g/'image.bin').write_bytes(b'INCOMPLETE'); print('staged',flush=True); time.sleep(30)"
        child = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-B", "-u", "-X", "utf8", "-c", code,
                                  str(self.new), str(self.game)], stdout=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            self.assertEqual(child.stdout.readline().strip(), "staged")
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        self.assertTrue((self.game / JOURNAL).is_file())
        recover_deployment(self.game)
        self.assertEqual((self.game / "image.bin").read_bytes(), b"OLD IMAGE")
        self.assertEqual((self.game / "bin/longshot.exe").read_bytes(), b"OLD EXE")
        self.assertEqual((self.game / "romfs/base").read_bytes(), b"BASE ROMFS")
        self.assertTrue((self.game / "mods/00-OOT-item-wheel/romfs/old").is_file())

    def test_worker_switches_profile_in_same_game_using_cache_without_compiler(self):
        from types import SimpleNamespace
        from manager_worker import Worker
        from modmanager.models import Settings
        from modmanager.pipeline import load_prepared
        # The selected game may be inside an old preparation, as existing users have it.
        self.game.rename(self.new / "game")
        self.game = self.new / "game"
        self.report.update(schema=1, status="prepared", workspace=str(self.new),
                           game_dir=str(self.game), build_status="not-built", manifest_sha256="synthetic",
                           audit={"layout": []}, inventory={"prepared": inventory(self.new / "prepared"),
                                                          "addon": inventory(self.new / "addon")})
        write_json(self.new / REPORT, self.report)
        root = self.root / "manager"
        cache = root / "cache/native-builds/longshot"
        key = native_key(self.new, self.report, "tools", "fr")
        cache_build(cache, key, self.game)
        worker = Worker(Settings(workspace=str(self.new), game_dir=str(self.game), clock=False,
                                 tools_path=self.report["tools_path"], data_root=str(root)))
        inode = (self.game / "romfs/base").stat().st_ino
        with patch.object(worker, "validate"), patch.object(worker, "audit"), patch.object(worker, "adapt"), \
             patch.object(worker, "load", side_effect=lambda: load_prepared(self.new)), \
             patch.object(worker, "run", side_effect=AssertionError("No compiler expected")) as compiler, \
             patch("manager_worker.ROOT", root), patch("modmanager.engines.longshot.LongshotBackend.tools_signature", return_value="tools"), \
             patch("manager_worker.subprocess.run", return_value=SimpleNamespace(stdout="", returncode=0)):
            worker.execute()
            compiler.assert_not_called()
        self.assertTrue((self.game / "mods/00-OOT-manual-shield/romfs/new").is_file())
        self.assertFalse((self.game / "mods/00-OOT-item-wheel").exists())
        self.assertEqual((self.game / "romfs/base").stat().st_ino, inode)
        self.assertEqual(load_prepared(self.new)["game_dir"], str(self.game))
        self.assertEqual((self.game / "user/save").read_bytes(), b"SAVE")

    def test_failed_build_keeps_prepared_adapter_and_matching_inventory(self):
        from manager_worker import Worker
        from modmanager.models import Settings, Plan
        from modmanager.pipeline import load_prepared
        self.report.update(schema=1, status="prepared", workspace=str(self.new),
                           build_status="not-built", inventory={
                               "prepared": inventory(self.new / "prepared"),
                               "addon": inventory(self.new / "addon")})
        write_json(self.new / REPORT, self.report)
        worker = Worker(Settings(workspace=str(self.new), game_dir=str(self.game),
                                 variant="manual-shield", tools_path=self.report["tools_path"], data_root=str(self.root / "manager")))
        def adapt(report):
            (self.new / "prepared/exefs/main").write_bytes(b"ADAPTED")
            report["native_adapters"] = [{"name": "test-adapter"}]
            report["inventory"]["prepared"] = inventory(self.new / "prepared")
            write_json(self.new / REPORT, report)
        with patch("manager_worker.ensure_game_closed"), patch.object(worker, "validate"), \
             patch.object(worker, "audit"), patch.object(worker, "remember_active_profile"), \
             patch.object(worker, "load", side_effect=lambda: load_prepared(self.new)), \
             patch.object(worker, "plan", return_value=Plan("build", "build", "test")), \
             patch.object(worker, "adapt", side_effect=adapt) as adaptation, \
             patch("modmanager.engines.longshot.LongshotBackend.tools_signature", return_value="tools"), \
             patch.object(worker, "apply_plan", side_effect=RuntimeError("compiler failed")):
            with self.assertRaisesRegex(RuntimeError, "compiler failed"):
                worker.execute()
        adaptation.assert_called_once()
        restored = load_prepared(self.new)
        self.assertEqual(restored["native_adapters"], [{"name": "test-adapter"}])
        self.assertEqual((self.new / "prepared/exefs/main").read_bytes(), b"ADAPTED")
        self.assertEqual((self.game / "image.bin").read_bytes(), b"OLD IMAGE")
        self.assertEqual((self.game / "user/save").read_bytes(), b"SAVE")

    def test_full_vanilla_disables_all_overlays_but_keeps_archived_files_and_saves(self):
        self.report["variant"] = "vanilla"
        write_json(self.new / REPORT, self.report)
        with replace_installation(self.new, self.report, self.game, disable_all_mods=True):
            (self.game / "image.bin").write_bytes(b"VANILLA IMAGE")
            (self.game / "bin").mkdir()
            (self.game / "bin/longshot.exe").write_bytes(b"VANILLA EXE")
        self.assertFalse((self.game / "mods").exists())
        self.assertTrue(list((self.game / ".hmb-disabled-mods").glob("*/user-mod/keep")))
        self.assertTrue((self.game / "user/save").exists())
        self.assertTrue((self.game / "romfs/base").exists())

    def test_failed_full_vanilla_restores_all_overlays(self):
        self.report["variant"] = "vanilla"
        write_json(self.new / REPORT, self.report)
        with self.assertRaises(RuntimeError):
            with replace_installation(self.new, self.report, self.game, disable_all_mods=True):
                (self.game / "image.bin").write_bytes(b"INCOMPLETE")
                raise RuntimeError("failed")
        self.assertTrue((self.game / "mods/user-mod/keep").exists())
        self.assertTrue((self.game / "mods/00-OOT-item-wheel/romfs/old").exists())
        self.assertEqual((self.game / "image.bin").read_bytes(), b"OLD IMAGE")
