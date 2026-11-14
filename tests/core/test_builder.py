"""Synthetic binaries only: no game dump, generated game code, or saves."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

ROOT = (Path(__file__).resolve().parents[2] / "src/core")
sys.path.insert(0, str(ROOT))
DEFAULT_MODS = Path(__file__).resolve().parents[2] / "src/bridge/trusted"

from modmanager.formats import (FormatError, Nso, Record, audit_changed_branches, branch_target,
                         changed_ranges, module_layout, parse_ips)
from modmanager.pipeline import (BUILD_ID, DEFAULT_TOOLS, REPORT, build,
                          check_source, digest, independent, inventory, load_module,
                          load_prepared, missing_dependencies, prepare, safe_relative)
from modmanager.engines.longshot_cache import seed_object_cache


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_nso(span=0x5000, data_memory=0x2000, build_id=None):
    """Small stored segments, optional large virtual gap/BSS; valid MOD0/dynamic table."""
    text = bytearray(0x200)
    struct.pack_into("<II", text, 0, 0xD65F03C0, 0x20)
    text[0x20:0x24] = b"MOD0"
    struct.pack_into("<6i", text, 0x24, data_memory - 0x20,
                     data_memory + 0x60 - 0x20, span - 0x20, 0, 0, data_memory + 0x60 - 0x20)
    ro = bytes(0x40)
    dynamic = b"".join(struct.pack("<QQ", tag, value) for tag, value in
                       [(5, 0x1000), (10, 1), (6, 0x1008), (11, 24), (4, 0x1028), (0, 0)])
    header = bytearray(0x100)
    header[:4] = b"NSO0"
    struct.pack_into("<I", header, 0xC, 0x38)
    struct.pack_into("<I", header, 0x3C, span - data_memory - len(dynamic))
    identity = bytes.fromhex(build_id) if build_id else hashlib.sha256(str(span).encode()).digest()
    header[0x40:0x40 + len(identity)] = identity
    body = bytearray()
    for i, (memory, data) in enumerate([(0, text), (0x1000, ro), (data_memory, dynamic)]):
        struct.pack_into("<III", header, 0x10 + i * 16, 0x100 + len(body), memory, len(data))
        struct.pack_into("<I", header, 0x60 + i * 4, len(data))
        header[0xA0 + 32 * i:0xC0 + 32 * i] = hashlib.sha256(data).digest()
        body.extend(data)
    return bytes(header + body)


def ips32(offset, data):
    return b"IPS32" + (offset + 0x100).to_bytes(4, "big") + len(data).to_bytes(2, "big") + data + b"EEOF"


def pack_nup(source: Path, destination: Path):
    """Minimal valid NUP containing the synthetic original's exefs and romfs."""
    files = [p for part in ("exefs", "romfs") for p in sorted((source / part).iterdir())]
    ne = sum(p.parent.name == "exefs" for p in files)
    strings = bytearray()

    def name(value):
        offset = len(strings)
        raw = value.encode()
        strings.extend(raw)
        return offset, len(raw)

    directories = [(*name(""), 0, 2), (*name("exefs"), 2, ne), (*name("romfs"), 2 + ne, len(files) - ne)]
    names = [name(p.name) for p in files]
    children = [1, 2] + [3 + i for i in range(len(files))]
    string_offset = 48 + 64 + 3 * 24 + len(files) * 80 + len(children) * 4
    toc_size = string_offset + len(strings)
    blob_offset = (128 + toc_size + 15) & ~15
    blob = bytearray()
    records = bytearray()
    for path, (off, length) in zip(files, names):
        raw = path.read_bytes()
        blob.extend(bytes((-len(blob)) % 16))
        record = bytearray(80)
        struct.pack_into("<IIQQQ", record, 0, off, length, len(raw), blob_offset + len(blob), len(raw))
        record[32:64] = hashlib.sha256(raw).digest()
        records.extend(record)
        blob.extend(raw)
    title = bytearray(64)
    struct.pack_into("<QIIII", title, 0, int("0400486024DEC800", 16), 0, 1, 2, 131072)
    title[24] = 1
    toc = bytearray(struct.pack("<IIQQQQQ", 0x01434F54, 1, 3, len(files), string_offset, len(strings), 0))
    toc.extend(title)
    for directory in directories:
        toc.extend(struct.pack("<4IQ", *directory, 0))
    toc.extend(records)
    toc.extend(struct.pack("<%dI" % len(children), *children))
    toc.extend(strings)
    header = bytearray(128)
    header[:4] = b"NUP\x01"
    struct.pack_into("<QQ", header, 8, 128, len(toc))
    header[24:56] = hashlib.sha256(toc).digest()
    struct.pack_into("<QQ", header, 56, blob_offset, blob_offset + len(blob))
    destination.write_bytes(header + toc + bytes(blob_offset - 128 - len(toc)) + blob)


class FormatTests(unittest.TestCase):
    def test_ips32_virtual_header_bias(self):
        self.assertEqual(parse_ips(ips32(0x3456, b"abc")), [Record(0x3456, b"abc")])

    def test_classic_ips_and_rle(self):
        raw = b"PATCH" + (0x200).to_bytes(3, "big") + b"\0\0\0\x04ZEOF"
        self.assertEqual(parse_ips(raw), [Record(0x100, b"ZZZZ")])

    def test_ips_invalid_forms(self):
        valid = ips32(0x100, b"abc")
        invalid = [b"other", valid[:-1], valid + b"\0", b"IPS32\0\0\0\0\0\x01XEEOF",
                   valid[:-4] + valid[5:]]
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(FormatError):
                    parse_ips(raw)

    def test_nso_roundtrip_and_hash_failure(self):
        raw = make_nso()
        original = Nso(raw)
        loaded = Nso(original.encode())
        self.assertEqual(original.segments, loaded.segments)
        self.assertEqual(original.end, loaded.end)
        corrupt = bytearray(raw)
        corrupt[0x100] ^= 1
        with self.assertRaises(FormatError):
            Nso(bytes(corrupt))

    def test_real_lz4_segment_normalization(self):
        if missing_dependencies(("lz4.block",)):
            self.skipTest("lz4 absent")
        import lz4.block
        raw = make_nso()
        module = Nso(raw)
        header, body = bytearray(raw[:0x100]), bytearray()
        struct.pack_into("<I", header, 0xC, 0x3F)
        for i, segment in enumerate(module.segments):
            packed = lz4.block.compress(segment.data, store_size=False)
            struct.pack_into("<I", header, 0x10 + 16 * i, 0x100 + len(body))
            struct.pack_into("<I", header, 0x60 + 4 * i, len(packed))
            body.extend(packed)
        loaded = Nso(bytes(header + body))
        self.assertEqual(loaded.segments, module.segments)
        self.assertEqual(Nso(loaded.encode()).segments, module.segments)

    def test_real_zbic_segment_normalization(self):
        if missing_dependencies(("zbic",)):
            self.skipTest("zbic absent")
        import zbic
        raw = make_nso()
        module = Nso(raw)
        header, body = bytearray(raw[:0x100]), bytearray()
        struct.pack_into("<I", header, 0xC, 0xBF)
        for i, segment in enumerate(module.segments):
            packed = zbic.compress(segment.data)
            struct.pack_into("<I", header, 0x10 + 16 * i, 0x100 + len(body))
            struct.pack_into("<I", header, 0x60 + 4 * i, len(packed))
            body.extend(packed)
        loaded = Nso(bytes(header + body))
        self.assertEqual(loaded.segments, module.segments)
        self.assertEqual(Nso(loaded.encode()).segments, module.segments)

    def test_bss_ips_initialization_preserves_module_placement(self):
        module = Nso(make_nso())
        old_size, old_end, old_bss = module.mapped_size, module.end, module.bss
        changes = module.apply(parse_ips(ips32(0x4000, b"CONFIG")))
        self.assertEqual(changes[0]["kind"], "bss-initialization")
        loaded = Nso(module.encode())
        self.assertEqual((loaded.mapped_size, loaded.end), (old_size, old_end))
        self.assertLess(loaded.bss, old_bss)
        self.assertEqual(loaded.segments[2].data[0x2000:0x2006], b"CONFIG")

    def test_text_padding_is_executable_after_materialization(self):
        module = Nso(make_nso())
        module.apply([Record(0x300, b"\xc0\x03\x5f\xd6")])
        loaded = Nso(module.encode())
        self.assertEqual(len(loaded.segments[0].data), 0x304)
        self.assertEqual(loaded.segments[1].memory, 0x1000)
        self.assertEqual(loaded.mapped_size, 0x5000)

    def test_invalid_ips_is_atomic(self):
        module = Nso(make_nso())
        original = module.encode()
        with self.assertRaises(FormatError):
            module.apply([Record(0x100, b"valid"), Record(0x5000, b"invalid")])
        self.assertEqual(module.encode(), original)

    def test_branches_forward_backward_and_conditional(self):
        self.assertEqual(branch_target(0x14000004, 0x100), 0x110)
        self.assertEqual(branch_target(0x97FFFFFF, 0x100), 0xFC)
        self.assertEqual(branch_target(0x54000040, 0x100), 0x108)
        self.assertEqual(branch_target(0xB4000040, 0x100), 0x108)
        self.assertEqual(branch_target(0x36000040, 0x100), 0x108)
        self.assertIsNone(branch_target(0xD65F03C0, 0x100))
        layout = [{"name": "main", "base": 0x100, "text_start": 0x100, "text_end": 0x200}]
        before = bytes(8)
        after = struct.pack("<II", 0x14000004, 0)
        self.assertEqual(audit_changed_branches("main", before, after, layout)[0]["target"], 0x110)
        with self.assertRaises(FormatError):
            audit_changed_branches("main", before, struct.pack("<II", 0x14000100, 0), layout)
        self.assertEqual(changed_ranges(before, after), [[0, 4]])

    def test_reject_truncated_and_overlapping_nso(self):
        raw = bytearray(make_nso())
        struct.pack_into("<I", raw, 0x20, 0x100)
        with self.assertRaises(FormatError):
            Nso(bytes(raw))
        with self.assertRaises(FormatError):
            Nso(make_nso()[:-1])


class PathTests(unittest.TestCase):
    def test_paths_are_contained_and_portable(self):
        for name in ("../x", "exefs/../../x", "/etc/x", "C:/x", "romfs\\x", "romfs/NUL.txt",
                     "romfs/a.", "romfs/a//x", "romfs/./x", "romfs/a:stream"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_relative(name)
        self.assertEqual(safe_relative("romfs/UI/a.zs"), Path("romfs/UI/a.zs"))

    def test_output_cannot_overlap_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            for output in (source, source / "work", source.parent):
                with self.assertRaises(ValueError):
                    independent(output, [source])

    def test_relative_output_cannot_overlap_absolute_source(self):
        source = Path.cwd() / 'source'
        for output in (Path('source'), Path('source/work'), Path('.')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                independent(output, [source])

    def test_seed_cache_is_atomic_and_does_not_replace_existing_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "cache", Path(directory) / "target"
            source.mkdir()
            target.mkdir()
            first, second = "a" * 40 + ".o", "b" * 40 + ".o"
            (source / first).write_bytes(b"existing-source")
            (source / second).write_bytes(b"new-object")
            (source / "ignore.txt").write_bytes(b"ignored")
            (target / first).write_bytes(b"preserve-target")
            self.assertEqual(seed_object_cache(source, target), 1)
            self.assertEqual((target / first).read_bytes(), b"preserve-target")
            self.assertEqual((target / second).read_bytes(), b"new-object")
            self.assertEqual(len(list(target.iterdir())), 2)


@unittest.skipIf(bool(missing_dependencies()), "Installer dependencies not installed")
@unittest.skipUnless((DEFAULT_TOOLS / "nx2/make_game.py").is_file(), "Set LONGSHOT_TOOLS for loader integration tests")
class PipelineTests(unittest.TestCase):
    def setUp(self):
        isolated_caches = mock.patch("modmanager.pipeline.shared_cache_sources", return_value=[])
        isolated_caches.start()
        self.addCleanup(isolated_caches.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="hmb-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.repo, self.workspace = (self.root / name for name in ("original", "mods", "prepared"))
        (self.source / "exefs").mkdir(parents=True)
        (self.source / "romfs").mkdir()
        (self.source / "romfs/base.bin").write_bytes(b"ORIGINAL ROMFS")
        (self.source / "exefs/main.npdm").write_bytes(b"META" + bytes(124))
        for name, span, memory in [("rtld", 0x20000, 0x2000), ("main", 0x4EA0000, 0x4E80000),
                                   ("subsdk0", 0xE0000, 0x2000), ("sdk", 0x900000, 0x2000)]:
            (self.source / "exefs" / name).write_bytes(make_nso(span, memory, BUILD_ID if name == "main" else None))
        self.repo.mkdir()
        shutil.copyfile(DEFAULT_MODS / "install.py", self.repo / "install.py")
        shutil.copyfile(DEFAULT_MODS / "nup_reader.py", self.repo / "nup_reader.py")
        patch_dir = self.repo / "patches/hero-unified"
        patch_dir.mkdir(parents=True)
        old = (self.source / "exefs/main").read_bytes()
        module = Nso(old)
        text = bytearray(module.segments[0].data)
        struct.pack_into("<I", text, 0x100, 0x14000000 | ((0x4F85100 - 0x100) // 4))
        installer = load_module(DEFAULT_MODS / "install.py", "hmb_test_installer")
        target = installer.emit_nso(old, text, module.bss + 0x5000)
        payload = {"length": len(text), "bss": module.bss + 0x5000,
                   "blocks": [[0x100, base64.b64encode(text[0x100:0x104]).decode()]]}
        helper = make_nso(0x80000)
        ips = ips32(0x4EA4000, b"HERO-CONFIG" + bytes(85))
        patches = [("exefs/main", "nso", zlib.compress(json.dumps(payload).encode()), sha(old), sha(target)),
                   ("exefs/subsdk1", "raw", helper, None, sha(helper)),
                   ("exefs/" + BUILD_ID.upper() + ".ips", "raw", ips, None, sha(ips)),
                   ("romfs/UI/example.bin", "raw", b"MOD RESOURCE", None, sha(b"MOD RESOURCE"))]
        entries = []
        for i, (path, kind, raw, source_hash, target_hash) in enumerate(patches):
            filename = "%03d.patch" % i
            (patch_dir / filename).write_bytes(raw)
            entry = {"path": path, "kind": kind, "patch": filename, "target_sha256": target_hash}
            if source_hash:
                entry["source_sha256"] = source_hash
            entries.append(entry)
        manifest = {"name": "Synthetic Hero", "version": "test", "title_id": "0400486024DEC000",
                    "update_version": 131072, "build_id": BUILD_ID, "files": entries}
        (patch_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.original_hashes = inventory(self.source)

    def do_prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return prepare(self.source, self.workspace, DEFAULT_TOOLS, self.repo, "hero-unified")

    def test_real_installer_to_longshot_loader(self):
        report = self.do_prepare()
        self.assertEqual(inventory(self.source), self.original_hashes)
        self.assertEqual(report["status"], "prepared")
        main = Nso((self.workspace / "prepared/exefs/main").read_bytes())
        self.assertEqual(main.mapped_size, 0x4EA5000)
        config = main.segments[2].data[0x24000:0x24060]
        self.assertEqual(config[:11], b"HERO-CONFIG")
        self.assertFalse(list((self.workspace / "prepared/exefs").glob("*.ips")))
        self.assertEqual(load_prepared(self.workspace)["variant"], "hero-unified")
        outcome = subprocess.run([sys.executable, str(ROOT / "audit_engine.py"), "--workspace", str(self.workspace)],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        audit = json.loads((self.workspace / "longshot-loader-audit.json").read_text())
        self.assertTrue(audit["module_bases_match"])
        self.assertEqual(audit["ips_records_preserved"], 1)
        self.assertEqual(audit["hle_overlaps"], [])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            build(self.workspace, jobs=2, language="fr-FR", plan=True)
        self.assertIn("make_game.py", output.getvalue())
        self.assertIn("--no-prepare-shaders", output.getvalue())
        self.assertFalse((self.workspace / "game").exists())

    def test_tamper_detection_and_no_overwrite(self):
        self.do_prepare()
        with self.assertRaises(ValueError):
            self.do_prepare()
        (self.workspace / "prepared/exefs/subsdk1").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "change"):
            load_prepared(self.workspace)
        self.assertEqual(inventory(self.source), self.original_hashes)

    def test_wrong_original_records_failed_state_without_mutation(self):
        path = self.source / "exefs/main"
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        snapshot = inventory(self.source)
        with self.assertRaises(subprocess.CalledProcessError):
            self.do_prepare()
        self.assertEqual(inventory(self.source), snapshot)
        self.assertEqual(json.loads((self.workspace / REPORT).read_text())["status"], "failed")

    def test_layout_mismatch_is_rejected(self):
        (self.source / "exefs/rtld").write_bytes(make_nso(0x21000))
        with self.assertRaisesRegex(ValueError, "Layout incompatible"):
            self.do_prepare()

    def test_nup_preserves_original_module_hashes(self):
        nup = self.root / "original.nup"
        pack_nup(self.source, nup)
        original_digest = digest(nup)
        with contextlib.redirect_stdout(io.StringIO()):
            report = prepare(nup, self.workspace, DEFAULT_TOOLS, self.repo, "hero-unified")
        self.assertEqual(report["status"], "prepared")
        self.assertEqual(digest(nup), original_digest)
        self.assertEqual(inventory(self.workspace / "original"), self.original_hashes)

    def test_nup_can_reuse_existing_romfs_without_copying_it(self):
        nup = self.root / "original.nup"
        pack_nup(self.source, nup)
        with contextlib.redirect_stdout(io.StringIO()):
            report = prepare(nup, self.workspace, DEFAULT_TOOLS, self.repo, "hero-unified",
                             self.source / "romfs")
        self.assertTrue(report["external_romfs"])
        self.assertFalse((self.workspace / "original/romfs").exists())
        self.assertEqual(Path(report["romfs"]).resolve(), (self.source / "romfs").resolve())
        self.assertEqual(inventory(self.source), self.original_hashes)

    def test_build_failure_preserves_matching_overlay_and_can_retry(self):
        self.do_prepare()

        def fail_compile(command, cwd, **kwargs):
            if "make_game.py" in " ".join(command):
                overlay = self.workspace / "game/mods/00-OOT-hero-unified/romfs/UI/example.bin"
                self.assertEqual(overlay.read_bytes(), b"MOD RESOURCE")
                raise subprocess.CalledProcessError(2, command)

        with mock.patch("modmanager.pipeline.require_dependencies"), mock.patch("modmanager.pipeline.run", side_effect=fail_compile):
            for _ in range(2):
                with self.assertRaises(subprocess.CalledProcessError):
                    build(self.workspace)
        self.assertEqual(load_prepared(self.workspace)["build_status"], "failed")
        self.assertEqual(inventory(self.source), self.original_hashes)

    def test_shared_objects_survive_upstream_environment_invalidation(self):
        self.do_prepare()
        donor = self.root / "donor-cache"
        donor.mkdir()
        name = "a" * 40 + ".o"
        (donor / name).write_bytes(b"verified content-keyed object")
        (donor.parent / "system_headers.txt").write_text("matching-system")
        def stop_before_compile(*args, **kwargs):
            if "audit_engine.py" in " ".join(args[0]):
                return
            if "-c" in args[0]:
                # The real upstream check deletes caches on a fresh workspace.
                cache = self.workspace / "build-work/objcache"
                if cache.exists():
                    shutil.rmtree(cache)
                (self.workspace / "build-work/system_headers.txt").write_text("matching-system")
                return
            self.assertEqual((self.workspace / "build-work/objcache" / name).read_bytes(),
                             b"verified content-keyed object")
            raise RuntimeError("stop before compilation")
        with mock.patch("modmanager.pipeline.shared_cache_sources", return_value=[donor]), \
             mock.patch("modmanager.pipeline.require_dependencies"), \
             mock.patch("modmanager.pipeline.run", side_effect=stop_before_compile):
            with self.assertRaisesRegex(RuntimeError, "stop before compilation"):
                build(self.workspace)
        report = load_prepared(self.workspace)
        self.assertEqual(report["shared_object_caches"][0]["objects_copied"], 1)

    def test_build_refuses_foreign_output(self):
        self.do_prepare()
        (self.workspace / "game").mkdir()
        precious = self.workspace / "game/keep.txt"
        precious.write_text("keep")
        with mock.patch("modmanager.pipeline.require_dependencies"):
            with self.assertRaisesRegex(ValueError, "non cree"):
                build(self.workspace)
        self.assertEqual(precious.read_text(), "keep")

    def test_build_refuses_modified_overlay(self):
        self.do_prepare()
        with mock.patch("modmanager.pipeline.require_dependencies"), mock.patch("modmanager.pipeline.run", side_effect=ValueError("stop")):
            with self.assertRaisesRegex(ValueError, "stop"):
                build(self.workspace)
        overlay = self.workspace / "game/mods/00-OOT-hero-unified/romfs/UI/example.bin"
        overlay.write_bytes(b"USER EDIT")
        with mock.patch("modmanager.pipeline.require_dependencies"), mock.patch("modmanager.pipeline.run") as runner:
            with self.assertRaisesRegex(ValueError, "overlay installe"):
                build(self.workspace)
            runner.assert_not_called()
        self.assertEqual(overlay.read_bytes(), b"USER EDIT")

    def test_build_output_cannot_replace_original(self):
        self.do_prepare()
        with self.assertRaisesRegex(ValueError, "separe"):
            build(self.workspace, game_dir=self.source, plan=True)
        self.assertEqual(inventory(self.source), self.original_hashes)


if __name__ == "__main__":
    unittest.main()
