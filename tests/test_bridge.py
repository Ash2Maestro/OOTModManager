"""Bridge contracts against temporary directories; no changes to a real game."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "src/core"
sys.path.insert(0, str(LEGACY))
sys.path.insert(0, str(ROOT / "src/bridge"))
spec = importlib.util.spec_from_file_location("native_bridge", ROOT / "src/bridge/worker.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
from modmanager.models import Settings


class BridgeTests(unittest.TestCase):
    def setUp(self):
        # These tests cover orchestration; input checks have their own real-path tests.
        for name in ("game_directory", "build_inputs", "pin_preparation"):
            patcher = patch.object(bridge, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.game.mkdir()
        self.repo = self.root / "mods"
        for slug in ("item-wheel", "manual-shield"):
            folder = self.repo / "patches" / slug
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps(dict(name=slug,version="1.0.0")))
        self.settings = Settings(game_dir=str(self.game),mods_repo=str(self.repo))
        self.settings.workspace = str(self.root / "requested-workspace")

    def test_snapshot_keeps_catalog_ids_and_does_not_import_tk(self):
        with patch.object(bridge,"event") as events:
            bridge.snapshot(self.settings,self.root / "legacy",self.root / "data")
        args = events.call_args.kwargs
        self.assertEqual(args["catalog"], [])
        self.assertEqual(args["active"],"vanilla")
        self.assertNotIn("tkinter",sys.modules)
        self.assertFalse((self.game / "language.txt").exists())

    def test_startup_catalog_never_extracts_assets(self):
        (self.game / 'romfs').mkdir()
        tools = self.root / 'tools'
        (tools / 'python').mkdir(parents=True)
        (tools / 'python/python.exe').touch()
        self.settings.tools_path = str(tools)
        with patch('subprocess.run', side_effect=AssertionError('startup extraction')), \
             patch.object(bridge, 'event') as events:
            bridge.snapshot(self.settings, self.root/'legacy', self.root/'data', with_assets=True)
        self.assertEqual(events.call_args.args, ('snapshot',))
        self.assertFalse((self.root/'data/appearance').exists())

    def test_interrupted_installation_is_reported_without_mutation(self):
        journal = self.game / ".hmb-deployment.json"
        journal.write_text("{}")
        with patch.object(bridge,"event") as events:
            bridge.snapshot(self.settings,self.root / "legacy",self.root / "data")
        self.assertTrue(events.call_args.kwargs["warning"])
        self.assertEqual(journal.read_text(),"{}")

    def test_apply_keeps_library_folder_and_item_wheel_clock(self):
        row = dict(id="item-wheel",repository=str(self.repo),kind="native")
        with patch.object(bridge,"library_rows",return_value=[row]), \
             patch("modmanager.pipeline.read_manifest",return_value=(self.repo/"patches/item-wheel/manifest.json", {})), \
             patch("manager_worker.Worker") as factory, patch.object(bridge,"snapshot") as snapshot, patch.object(bridge,"event") as events:
            bridge.run(dict(action="apply",settings=self.settings.to_dict(),variant="item-wheel",
                            repository=str(self.repo),force=True),LEGACY,self.root)
        self.assertTrue(factory.call_args.args[0].preserve_runtime_settings)
        self.assertTrue(factory.call_args.args[0].clock)
        self.assertTrue(factory.call_args.args[1])
        factory.return_value.execute.assert_called_once_with()
        snapshot.assert_called_once()
        installed = next(call.kwargs for call in events.call_args_list if call.args == ("installed",))
        self.assertEqual(installed["settings"]["mods_repo"],str(self.repo))

    def test_removal_keeps_stable_identifier(self):
        with patch("manage_mods.manage") as manage:
            bridge.run(dict(action="remove",settings=self.settings.to_dict(),identifier="native:manual-shield"),LEGACY,self.root)
        self.assertEqual(manage.call_args.args[1:],("remove","native:manual-shield"))

    def test_explicit_work_folder_is_forwarded_without_creating_a_build(self):
        row = dict(id="item-wheel",repository=str(self.repo),kind="native")
        with patch.object(bridge,"library_rows",return_value=[row]), \
             patch("modmanager.pipeline.read_manifest",return_value=(self.repo/"patches/item-wheel/manifest.json", {})), \
             patch("manager_worker.Worker") as factory, patch.object(bridge,"snapshot"), patch.object(bridge,"event"):
            bridge.run(dict(action="apply",settings=self.settings.to_dict(),variant="item-wheel",
                            repository=str(self.repo),preferWorkspace=True),LEGACY,self.root)
        self.assertEqual(factory.call_args.args[0].workspace,self.settings.workspace)
        self.assertFalse(Path(self.settings.workspace).exists())

    def test_unknown_action_fails_closed(self):
        with self.assertRaises(ValueError):
            bridge.run(dict(action="unsupported",settings=self.settings.to_dict()),LEGACY,self.root)

    def test_game_preference_action_is_no_longer_supported(self):
        with self.assertRaisesRegex(ValueError, "Action inconnue"):
            bridge.run(dict(action="preferences",settings=self.settings.to_dict()),LEGACY,self.root)

    def test_library_removal_never_runs_game_operations(self):
        with patch.object(bridge, 'remove_entry', return_value=True) as remove, \
             patch.object(bridge, 'snapshot') as snapshot, patch.object(bridge, 'event'), \
             patch('manager_worker.Worker') as worker, patch('manage_mods.manage') as manage:
            bridge.run(dict(action='library_remove',settings=self.settings.to_dict(),
                            identifier='item-wheel',repository='package'),LEGACY,self.root)
        remove.assert_called_once_with(self.settings.mods_repo, 'item-wheel', 'package')
        snapshot.assert_called_once()
        worker.assert_not_called()
        manage.assert_not_called()

    def test_changing_library_to_empty_folder_hides_all_previous_mods(self):
        self.settings.mods_repo = str(self.root / "empty")
        with patch.object(bridge,"event") as events:
            bridge.snapshot(self.settings, LEGACY, self.root / "data")
        self.assertEqual(events.call_args.kwargs["catalog"], [])
        self.assertFalse((self.root/"empty").exists())


if __name__ == "__main__":
    unittest.main()
