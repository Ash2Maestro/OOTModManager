"""Synthetic file-only checks for post-build timing changes."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str((Path(__file__).resolve().parents[2] / "src/core")))
from test_builder import make_nso
from modmanager.formats import Nso, Record
from modmanager.pipeline import inventory, load_prepared, write_json
from modmanager.engines.longshot_delay import set_delay


class ClockSettingsTests(unittest.TestCase):
    def test_missing_dump_requires_matching_verified_preparation(self):
        from modmanager.pipeline import reusable_preparation
        report = load_prepared(self.root)
        missing = self.root / 'removed.nup'
        romfs = self.root / 'romfs'
        romfs.mkdir()
        report.update(source=str(missing), romfs=str(romfs))
        write_json(self.root / 'hmb-report.json', report)
        self.assertTrue(reusable_preparation(str(self.root), str(missing)))
        self.assertFalse(reusable_preparation(str(self.root), str(self.root / 'other.nup')))
        (self.root / 'prepared/exefs/subsdk1').write_bytes(b'changed')
        self.assertFalse(reusable_preparation(str(self.root), str(missing)))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = self.root / "game"
        (self.game / "bin").mkdir(parents=True)
        (self.root / "prepared/exefs").mkdir(parents=True)
        (self.root / "addon").mkdir()
        module = Nso(make_nso(0x80000, 0x1E000))
        module.apply([Record(0x1E100, struct.pack("<I", 100))])
        (self.root / "prepared/exefs/subsdk1").write_bytes(module.encode())
        image = bytearray(0x20000)
        image[0x100:0x110] = b"SYNTHETIC-CLOCK!!"
        struct.pack_into("<I", image, 0x1E100, 100)
        (self.game / "image.bin").write_bytes(image)
        (self.game / "bin/longshot.exe").write_bytes(b"SYNTHETIC EXE")
        write_json(self.game / ".hmb-owner.json", {"workspace": str(self.root)})
        report = {"schema": 1, "status": "prepared", "workspace": str(self.root), "game_dir": str(self.game),
                  "build_status": "built-unverified-in-game", "audit": {"layout": [{"name": "subsdk1", "base": 0x80000000}]},
                  "inventory": {"prepared": inventory(self.root / "prepared"), "addon": {}},
                  "native_adapters": [{"revision": 3, "runtime_config": 0x8001E100, "cave": 0x80000100,
                                       "code_size": 16, "code_sha256": hashlib.sha256(image[0x100:0x110]).hexdigest()}]}
        write_json(self.root / "hmb-report.json", report)

    def test_change_only_setting_without_rebuilding_executable(self):
        image_before = (self.game / "image.bin").read_bytes()
        exe_before = (self.game / "bin/longshot.exe").read_bytes()
        set_delay(self.root, 100, mark_installed=True)
        set_delay(self.root, 80)
        after = (self.game / "image.bin").read_bytes()
        expected = bytearray(image_before)
        struct.pack_into("<I", expected, 0x1E100, 80)
        self.assertEqual(after, expected)
        self.assertEqual((self.game / "bin/longshot.exe").read_bytes(), exe_before)
        self.assertEqual(load_prepared(self.root)["wheel_hold_ms_installed"], 80)

    def test_refuse_unregistered_or_changed_executable(self):
        with self.assertRaisesRegex(ValueError, "premiere compilation"):
            set_delay(self.root, 80)
        set_delay(self.root, 100, mark_installed=True)
        (self.game / "bin/longshot.exe").write_bytes(b"DIFFERENT EXE")
        before = (self.game / "image.bin").read_bytes()
        with self.assertRaisesRegex(ValueError, "executable a change"):
            set_delay(self.root, 80)
        self.assertEqual((self.game / "image.bin").read_bytes(), before)

    def test_refuse_wrong_adapter_image(self):
        image = self.game / "image.bin"
        before = bytearray(image.read_bytes())
        before[0x100] ^= 1
        image.write_bytes(before)
        with self.assertRaisesRegex(ValueError, "revision"):
            set_delay(self.root, 80, mark_installed=True)
        self.assertEqual(image.read_bytes(), before)

    def test_gui_planner_reads_actual_delay_and_rejects_changed_exe(self):
        from modmanager.models import ROOT, RECEIPT, Settings
        from modmanager.engines.longshot_signatures import prepared_signature
        from modmanager.signatures import image_digest
        from modmanager.pipeline import digest
        from manager_worker import Worker
        set_delay(self.root, 100, mark_installed=True)
        report = load_prepared(self.root)
        report["manifest_sha256"] = "synthetic"
        report["native_adapters"][0].update(source_sha256=digest(ROOT / "adapters/wheel_clock.c"), hold_ms=100)
        write_json(self.root / "hmb-report.json", report)
        audit_path = self.root / "longshot-loader-audit.json"
        audit = {"image_sha256_without_clock_config": image_digest(self.game / "image.bin", 0x1E100)}
        write_json(audit_path, audit)
        write_json(self.root / RECEIPT, {"source_signature": "tools", "prepared_signature": prepared_signature(self.root, report),
                                       "exe_sha256": digest(self.game / "bin/longshot.exe")})
        worker = Worker(Settings(workspace=str(self.root), game_dir=str(self.game), clock=True, hold_ms=100))
        with patch.object(worker.engine, "preparation_signature", wraps=prepared_signature) as signatures:
            self.assertEqual(worker.plan(report, "tools").action, "ready")
        self.assertEqual(signatures.call_count, 1, "Current receipts must not hash the legacy inventory")
        receipt = json.loads((self.root / RECEIPT).read_text())
        receipt["prepared_signature"] = prepared_signature(self.root, report, legacy=True)
        write_json(self.root / RECEIPT, receipt)
        self.assertEqual(worker.plan(report, "tools").action, "ready")
        audit_path.unlink()
        self.assertEqual(worker.plan(report, "tools").action, "build")
        write_json(audit_path, audit)
        with (self.game / "image.bin").open("r+b") as stream:
            stream.seek(0x1E100)
            stream.write(struct.pack("<I", 80))
        self.assertEqual(worker.plan(report, "tools").action, "configure")
        (self.game / "bin/longshot.exe").write_bytes(b"CHANGED")
        with patch("manager_worker.resources_match", side_effect=AssertionError("unnecessary overlay hashing")):
            self.assertEqual(worker.plan(report, "tools").action, "build")
