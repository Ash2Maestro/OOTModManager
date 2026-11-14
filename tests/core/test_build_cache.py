import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modmanager import build_cache as cache
from modmanager.pipeline import digest, write_json, workspace_lock


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cache = self.root / "cache"
        self.exe = self.root / "exe"
        self.exe.write_bytes(b"shared native program" * 10000)

    def store(self, key, value=b"guest image", limit=cache.DEFAULT_LIMIT):
        source = self.root / (key + ".image")
        source.write_bytes(value)
        return cache.store_build(self.cache, key, {"bin/longshot.exe": self.exe, "image.bin": source}, limit)

    def legacy(self, key):
        target = self.cache / key
        (target / "files/bin").mkdir(parents=True)
        (target / "files/bin/longshot.exe").write_bytes(self.exe.read_bytes())
        (target / "files/image.bin").write_bytes(b"original guest image")
        files = {n: digest(target / "files" / n) for n in ("bin/longshot.exe", "image.bin")}
        write_json(target / "build.json", {"schema": 1, "key": key, "files": files})
        return target

    def test_common_content_is_stored_once_and_compressed(self):
        self.store("a" * 64)
        self.store("b" * 64, b"other image")
        _, first = cache.read_build(self.cache, "a" * 64)
        _, second = cache.read_build(self.cache, "b" * 64)
        self.assertEqual(first["files"]["bin/longshot.exe"], second["files"]["bin/longshot.exe"])
        objects = list((self.cache / ".objects").glob("*/*.zst"))
        self.assertEqual(len(objects), 3)
        self.assertLess(sum(p.stat().st_size for p in objects), self.exe.stat().st_size // 10)
        self.assertFalse((self.cache / ("a" * 64) / "files").exists())

    def test_migration_checks_and_restores_content_before_removing_old_copy(self):
        key = "a" * 64
        target = self.legacy(key)
        result = cache.migrate_cache(self.cache)
        self.assertEqual(result["builds"], 1)
        self.assertFalse((target / "files").exists())
        target, data = cache.read_build(self.cache, key)
        output = self.root / "restored"
        cache.copy_file(self.cache, target, data, "image.bin", output)
        self.assertEqual(output.read_bytes(), b"original guest image")
        output.write_bytes(b"changed outside cache")
        cache.read_build(self.cache, key)

    def test_failed_manifest_commit_keeps_legacy_build_usable(self):
        key = "a" * 64
        target = self.legacy(key)
        with patch.object(cache, "commit_manifest", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                cache.migrate_cache(self.cache)
        self.assertTrue((target / "files/image.bin").is_file())
        self.assertEqual(cache.read_build(self.cache, key)[1]["schema"], 1)
        cache.migrate_cache(self.cache)
        self.assertEqual(cache.read_build(self.cache, key)[1]["schema"], 2)

    def test_interruption_after_commit_resumes_cleanup(self):
        key = "a" * 64
        target = self.legacy(key)
        with patch.object(cache.shutil, "rmtree", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                cache.migrate_cache(self.cache)
        self.assertTrue((target / "files").exists())
        self.assertEqual(cache.read_build(self.cache, key)[1]["schema"], 2)
        cache.migrate_cache(self.cache)
        self.assertFalse((target / "files").exists())

    def test_lru_eviction_preserves_objects_referenced_by_other_builds(self):
        self.exe.write_bytes(os.urandom(1024))
        keys = [c * 64 for c in "abc"]
        for index, key in enumerate(keys):
            self.store(key, os.urandom(2048))
            path, data = cache.metadata(self.cache, key)
            data["used_ns"] = index
            write_json(path / "build.json", data)
        refs = set()
        for key in keys[1:]:
            refs.update(cache.metadata(self.cache, key)[1]["files"].values())
        budget = sum(cache.object_path(self.cache, sha).stat().st_size for sha in refs)
        result = cache.migrate_cache(self.cache, budget)
        self.assertEqual(result["evicted"], [keys[0]])
        self.assertLessEqual(result["bytes"], budget)
        for key in keys[1:]:
            cache.read_build(self.cache, key)
        self.assertEqual(len(list((self.cache / ".objects").glob("*/*.zst"))), 3)

    def test_new_build_is_kept_even_when_it_exceeds_budget(self):
        result = self.store("a" * 64, limit=1)
        self.assertEqual(result["builds"], 1)
        self.assertGreater(result["bytes"], 1)
        cache.read_build(self.cache, "a" * 64)

    def test_corrupted_old_build_is_not_removed(self):
        key = "a" * 64
        target = self.legacy(key)
        (target / "files/image.bin").write_bytes(b"corruption")
        with self.assertRaisesRegex(ValueError, "modifié"):
            cache.migrate_cache(self.cache)
        self.assertTrue((target / "files").exists())

    def test_concurrent_cache_writer_is_refused(self):
        self.cache.mkdir()
        with workspace_lock(self.cache):
            with self.assertRaisesRegex(ValueError, "utilise déjà"):
                self.store("a" * 64)

    def test_build_manifest_cannot_reference_external_paths(self):
        target = self.legacy("a" * 64)
        path = target / "build.json"
        data = json.loads(path.read_text())
        data["files"]["../outside"] = "b" * 64
        write_json(path, data)
        with self.assertRaises(ValueError):
            cache.migrate_cache(self.cache)

    def test_failed_new_snapshot_is_not_published(self):
        with patch.object(cache, "commit_manifest", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store("a" * 64)
        self.assertFalse((self.cache / ("a" * 64)).exists())
        self.assertFalse(list(self.cache.glob(".snapshot-*")))
        self.store("a" * 64)
        cache.read_build(self.cache, "a" * 64)

    def test_legacy_snapshot_is_readable_without_migration(self):
        target = self.legacy("a" * 64)
        target, data = cache.read_build(self.cache, "a" * 64)
        output = self.root / "legacy-restored"
        cache.copy_file(self.cache, target, data, "image.bin", output)
        self.assertEqual(output.read_bytes(), b"original guest image")
        self.assertTrue((target / "files/image.bin").exists())

    def test_invalid_budget_cannot_start_migration(self):
        target = self.legacy("a" * 64)
        with self.assertRaises(ValueError):
            cache.migrate_cache(self.cache, 0)
        self.assertTrue((target / "files/image.bin").exists())

    def test_interrupted_writes_and_orphan_objects_are_collected(self):
        self.store("a" * 64)
        orphan = cache.object_path(self.cache, "f" * 64)
        orphan.parent.mkdir(exist_ok=True)
        orphan.write_bytes(b"unreferenced")
        temporary = orphan.parent / ".writing-interrupted"
        temporary.write_bytes(b"partial compression")
        (self.cache / ".snapshot-interrupted").mkdir()
        (self.cache / ".evicted-interrupted").mkdir()
        cache.migrate_cache(self.cache)
        self.assertFalse(orphan.exists())
        self.assertFalse(temporary.exists())
        self.assertFalse((self.cache / ".snapshot-interrupted").exists())
        self.assertFalse((self.cache / ".evicted-interrupted").exists())
        cache.read_build(self.cache, "a" * 64)
