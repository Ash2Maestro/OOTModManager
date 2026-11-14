from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from modmanager.pipeline import REPORT, BUILD_ID, inventory, digest, write_json, load_prepared
from modmanager.removal import installed_mods, remaining_native, uninstall_overlay
from modmanager.vanilla import prepare_vanilla
from test_builder import make_nso


class RemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = self.root / "game"
        self.project = self.root / "project"
        self.project.mkdir()
        for name in ("mods/00-OOT-manual-shield/romfs", "mods/textures", "mods/sounds", "user"):
            (self.game / name).mkdir(parents=True)
            (self.game / name / "keep").write_bytes(name.encode())
        (self.game / "image.bin").write_bytes(b"NATIVE CODE")
        write_json(self.game / ".hmb-owner.json", {"workspace": str(self.project)})
        write_json(self.project / REPORT, {"variant": "manual-shield", "manifest": {"name": "Manual Shield", "version": "0.1.7"}})

    def test_installed_list_distinguishes_native_code_from_overlay(self):
        mods = installed_mods(self.game)
        self.assertEqual({m["id"] for m in mods}, {"native:manual-shield", "overlay:textures", "overlay:sounds"})

    def test_remove_one_overlay_keeps_native_other_mod_and_saves(self):
        uninstall_overlay(self.game, "overlay:textures")
        self.assertFalse((self.game / "mods/textures").exists())
        self.assertTrue((self.game / "mods/sounds/keep").exists())
        self.assertTrue((self.game / "mods/00-OOT-manual-shield/romfs/keep").exists())
        self.assertTrue((self.game / "user/keep").exists())
        self.assertEqual((self.game / "image.bin").read_bytes(), b"NATIVE CODE")

    def test_native_overlay_cannot_be_deleted_as_resource_mod(self):
        with self.assertRaises(ValueError):
            uninstall_overlay(self.game, "overlay:00-OOT-manual-shield")
        self.assertTrue((self.game / "mods/00-OOT-manual-shield").is_dir())

    def test_known_combination_removes_only_requested_component(self):
        self.assertEqual(remaining_native("manual-shield", "manual-shield"), "vanilla")
        self.assertEqual(remaining_native("wheel-and-shield", "manual-shield"), "item-wheel")
        self.assertEqual(remaining_native("wheel-and-shield", "item-wheel"), "manual-shield")
        self.assertEqual(remaining_native("wheel-and-shield", "wheel-and-shield"), "vanilla")
        with self.assertRaises(ValueError):
            remaining_native("hero-unified", "manual-shield")

    def test_known_combination_exposes_individual_removal_choices(self):
        write_json(self.project / REPORT, {"variant": "wheel-and-shield", "manifest": {"name": "Wheel + Shield", "version": "test"}})
        (self.game / "mods/00-OOT-manual-shield").rename(self.game / "mods/00-OOT-wheel-and-shield")
        mods = installed_mods(self.game)
        self.assertEqual({m["id"] for m in mods if m["kind"] == "native-component"}, {"native:item-wheel", "native:manual-shield"})

    def test_active_state_survives_removal_of_preparation_report(self):
        state = json.loads((self.project / REPORT).read_text())
        state["workspace"] = str(self.project)
        write_json(self.game / ".hmb-active.json", state)
        (self.project / REPORT).unlink()
        self.assertEqual(installed_mods(self.game)[0]["id"], "native:manual-shield")


class VanillaPreparationTests(unittest.TestCase):
    def test_preparation_contains_original_modules_only_and_no_copied_romfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, target, work = root / "source", root / "game", root / "vanilla"
            (source / "exefs").mkdir(parents=True)
            (target / "romfs").mkdir(parents=True)
            (target / "romfs/large-base").write_bytes(b"BASE")
            for name in ("rtld", "main", "subsdk0", "sdk"):
                (source / "exefs" / name).write_bytes(make_nso(0x20000, 0x2000, BUILD_ID if name == "main" else None))
            (source / "exefs/main.npdm").write_bytes(b"NPDM")
            with patch("modmanager.vanilla.check_tools"), patch("modmanager.vanilla.ORIGINAL_MAIN_SHA256", digest(source / "exefs/main")):
                report = prepare_vanilla(source, work, root / "tools", target / "romfs")
            self.assertEqual(report["variant"], "vanilla")
            self.assertFalse((work / "prepared/exefs/subsdk1").exists())
            self.assertFalse((work / "romfs").exists())
            self.assertEqual(inventory(work / "addon"), {})
            self.assertEqual(load_prepared(work)["audit"]["changed_code_ranges"], {})
