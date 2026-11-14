import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from modmanager.pipeline import workspace_lock, process_alive


class WorkspaceLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / ".hmb-build.lock"

    def test_normal_release_and_exception_allow_retry(self):
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with workspace_lock(self.root):
                raise RuntimeError("interrupted")
        with workspace_lock(self.root):
            pass
        self.assertEqual(self.path.read_bytes(), b"")

    def test_actual_live_process_is_detected(self):
        self.assertTrue(process_alive(os.getpid()))
        self.path.write_text("pid=%d\n" % os.getpid())
        with self.assertRaisesRegex(ValueError, "PID"):
            with workspace_lock(self.root):
                self.fail("live legacy lock acquired")

    def test_legacy_dead_lock_is_recovered_without_touching_cache(self):
        self.path.write_text("pid=123\n")
        valuable = self.root / "compiled.o"
        valuable.write_bytes(b"keep")
        with patch("modmanager.pipeline.process_alive", return_value=False):
            with workspace_lock(self.root):
                self.assertEqual(valuable.read_bytes(), b"keep")

    def test_unknown_process_status_is_not_reclaimed(self):
        self.path.write_text("pid=123\n")
        with patch("modmanager.pipeline.process_alive", return_value=None):
            with self.assertRaisesRegex(ValueError, "PID"):
                with workspace_lock(self.root):
                    self.fail("uncertain legacy lock acquired")
        self.assertEqual(self.path.read_text(), "pid=123\n")

    def test_active_kernel_lock_rejects_another_process(self):
        code = "from pathlib import Path; from modmanager.pipeline import workspace_lock;\nwith workspace_lock(Path(__import__('sys').argv[1])): print('acquired')"
        with workspace_lock(self.root):
            child = subprocess.run([getattr(sys, "_base_executable", sys.executable), "-B", "-X", "utf8", "-c", code, str(self.root)], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(child.returncode, 0)
            self.assertNotIn("acquired", child.stdout)

    def test_killed_process_releases_kernel_lock(self):
        code = "from pathlib import Path; from modmanager.pipeline import workspace_lock; import time;\nwith workspace_lock(Path(__import__('sys').argv[1])): print('locked',flush=True); time.sleep(30)"
        child = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-B", "-u", "-X", "utf8", "-c", code, str(self.root)], stdout=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        with workspace_lock(self.root):
            pass
