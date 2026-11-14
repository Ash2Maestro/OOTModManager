import json
from pathlib import Path
import tempfile
import unittest

from scripts.maintenance.layout_migration import LayoutMigration, rewrite_paths


class LayoutMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.migration = LayoutMigration(self.root, self.root / "journal/state.json")

    def test_move_is_journaled_and_repeatable_without_copy(self):
        source, destination = self.root / "old", self.root / "new"
        source.mkdir()
        (source / "payload").write_bytes(b"cache object")
        inode = (source / "payload").stat().st_ino
        self.migration.move(source, destination)
        self.migration.move(source, destination)
        self.assertEqual((destination / "payload").stat().st_ino, inode)
        self.assertEqual(self.migration.state["moves"][0]["status"], "moved")

    def test_existing_destination_and_external_move_are_refused(self):
        source = self.root / "old"
        source.mkdir()
        destination = self.root / "existing"
        destination.mkdir()
        with self.assertRaises(FileExistsError):
            self.migration.move(source, destination)
        with self.assertRaises(ValueError):
            self.migration.move(source, self.root.parent / "outside")
        self.assertTrue(source.exists())

    def test_metadata_is_backed_up_and_inventory_is_unchanged(self):
        path = self.root / "report.json"
        before = {"workspace": str(self.root / "old"), "inventory": {"exefs/main": "abc123"}}
        path.write_text(json.dumps(before))
        self.migration.rewrite_json(path, [(self.root / "old", self.root / "new")])
        after = json.loads(path.read_text())
        self.assertEqual(after["workspace"], str(self.root / "new"))
        self.assertEqual(after["inventory"], before["inventory"])
        backup = Path(self.migration.state["metadata"][0]["backup"])
        self.assertEqual(json.loads(backup.read_text()), before)

    def test_prefix_replacement_respects_boundaries_and_specificity(self):
        old = self.root / "old"
        mappings = [(old, self.root / "generic"), (old / "library", self.root / "library")]
        data = [str(old / "library/pkg"), str(self.root / "old-other"), "relative/file", "deadbeef"]
        changed = rewrite_paths(data, mappings)
        self.assertEqual(changed, [str(self.root / "library/pkg"), *data[1:]])
