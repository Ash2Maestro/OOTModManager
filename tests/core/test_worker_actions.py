"""Action boundaries: cache reuse, failures and no implicit compilation."""
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from manager_worker import Worker
from modmanager.models import Plan, Settings


class WorkerActionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.worker = Worker(Settings(workspace=str(self.root / "prepared"),
                                      game_dir=str(self.root / "game"),
                                      preserve_runtime_settings=True))
        self.worker.load = Mock(return_value={})
        self.worker.apply_runtime_preferences = Mock()
        self.worker.save_receipt = Mock()
        self.events = patch("manager_worker.emit")
        self.emit = self.events.start()
        self.addCleanup(self.events.stop)

    def test_unknown_action_is_rejected_before_any_file_operation(self):
        with self.assertRaisesRegex(ValueError, "Action inconnue"):
            self.worker.apply_plan(Plan("typo", "", ""), "tools")
        self.worker.load.assert_not_called()
        self.worker.save_receipt.assert_not_called()

    def test_cache_hit_skips_compiler_and_records_once(self):
        self.worker.restore_cached_build = Mock(return_value=True)
        self.worker.compile_native = Mock()
        self.worker.apply_plan(Plan("build", "", ""), "tools")
        self.worker.compile_native.assert_not_called()
        self.worker.save_receipt.assert_called_once_with("tools")
        self.assertIn("réutilisé", self.emit.call_args.kwargs["message"])

    def test_failed_compile_never_records_success(self):
        self.worker.restore_cached_build = Mock(return_value=False)
        self.worker.compile_native = Mock(side_effect=RuntimeError("compiler failure"))
        self.worker.sync_resources = Mock()
        with self.assertRaisesRegex(RuntimeError, "compiler failure"):
            self.worker.apply_plan(Plan("build", "", ""), "tools")
        self.worker.sync_resources.assert_not_called()
        self.worker.save_receipt.assert_not_called()

    def test_configure_synchronizes_resources_without_compilation(self):
        self.worker.configure_mod = Mock()
        self.worker.sync_resources = Mock()
        self.worker.compile_native = Mock()
        self.worker.apply_plan(Plan("configure", "", ""), "tools")
        self.worker.configure_mod.assert_called_once_with()
        self.worker.sync_resources.assert_called_once_with()
        self.worker.compile_native.assert_not_called()
        self.worker.save_receipt.assert_called_once_with("tools")

    def test_forced_build_does_not_hash_cache_key(self):
        self.worker.force = True
        with patch("manager_worker.native_key", side_effect=AssertionError("unnecessary hashing")):
            self.assertFalse(self.worker.restore_cached_build({}, "tools"))

    def test_existing_target_requires_transaction_before_cache_lookup(self):
        Path(self.worker.settings.game_dir).mkdir()
        with patch("manager_worker.native_key", side_effect=AssertionError("unnecessary hashing")):
            self.assertFalse(self.worker.restore_cached_build({}, "tools"))

    def test_broken_event_stream_reaps_child_and_closes_output(self):
        processes = []
        launch = subprocess.Popen

        def capture(*args, **kwargs):
            process = launch(*args, **kwargs)
            processes.append(process)
            return process

        self.emit.side_effect = BrokenPipeError("frontend closed")
        with patch("manager_worker.subprocess.Popen", side_effect=capture):
            with self.assertRaises(BrokenPipeError):
                self.worker.run([sys.executable, "-c", "import time; time.sleep(30)"])
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].stdout.closed)
