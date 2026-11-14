"""Exercise untrusted ZIPs only in temporary folders; never touch a real game."""

import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/bridge"))
sys.path.insert(0, str(ROOT / "src/core"))
from zip_library import import_archive, library_rows, pin_preparation, remove_entry
from modmanager.pipeline import BUILD_ID, TITLE_ID, UPDATE
import worker as bridge
from modmanager.models import Settings


class ZipLibraryTests(unittest.TestCase):
    def test_remove_unused_package_frees_only_its_imported_copy(self):
        archive = self.archive()
        import_archive(archive, self.data)
        row = library_rows(self.data)[0]
        self.assertFalse(remove_entry(self.data, row['id'], row['repository']))
        self.assertEqual(library_rows(self.data), [])
        self.assertFalse(Path(row['repository']).exists())
        self.assertTrue(archive.is_file())

    def test_remove_prepared_package_keeps_workspace_dependencies_even_after_reimport(self):
        archive = self.archive()
        import_archive(archive, self.data)
        row = library_rows(self.data)[0]
        pin_preparation(self.data, row)
        import_archive(archive, self.data)
        self.assertTrue(remove_entry(self.data, row['id'], row['repository']))
        self.assertEqual(library_rows(self.data), [])
        self.assertTrue((Path(row['repository'])/'patches'/row['id']/'manifest.json').is_file())

    def test_stale_removal_cannot_delete_another_library_or_version(self):
        import_archive(self.archive(), self.data)
        row = library_rows(self.data)[0]
        with self.assertRaisesRegex(ValueError, 'plus dans la bibliothèque'):
            remove_entry(self.data, row['id'], str(self.root/'other-package'))
        self.assertEqual(len(library_rows(self.data)), 1)
        self.assertTrue(Path(row['repository']).exists())

    def test_legacy_package_without_preparation_history_is_retained(self):
        import_archive(self.archive(), self.data)
        row = library_rows(self.data)[0]
        index = self.data / 'catalog.json'
        document = json.loads(index.read_text())
        del document['mods'][row['id']]['unprepared']
        index.write_text(json.dumps(document))
        self.assertTrue(remove_entry(self.data, row['id'], row['repository']))
        self.assertTrue(Path(row['repository']).is_dir())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"

    def archive(self, name="mod.zip", prefix="Test-Mod-v9.0.0", version="9.0.0", extra=None, metadata=None):
        import struct
        def nso(build_id):
            data = bytearray(0x10c)
            data[:4] = b"NSO0"
            data[0x40:0x60] = bytes.fromhex(build_id).ljust(32, b"\0")
            for i in range(3):
                struct.pack_into("<III", data, 0x10 + 16*i, 0x100 + 4*i, i*0x1000, 4)
                struct.pack_into("<I", data, 0x60 + 4*i, 4)
            return bytes(data)
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(prefix + "/exefs/main", nso(BUILD_ID))
            archive.writestr(prefix + "/exefs/subsdk1", nso("11"*20))
            archive.writestr(prefix + "/romfs/test.bin", b"resource")
            archive.writestr(prefix + "/mod-info.json", json.dumps(metadata if metadata is not None else dict(name="Test Mod",version=version)))
            archive.writestr(prefix + "/evil.py", "raise RuntimeError('untrusted script executed')")
            if extra:
                extra(archive)
        return path

    def test_import_is_staged_deduplicated_and_never_executes_archive_code(self):
        archive = self.archive()
        original = archive.read_bytes()
        self.assertEqual(import_archive(archive, self.data), ["addon-test-mod"])
        import_archive(archive, self.data)
        rows = library_rows(self.data)
        self.assertEqual(len(rows), 1)
        repository = Path(rows[0]["repository"])
        self.assertEqual(len(list((self.data / "packages").iterdir())), 1)
        self.assertFalse((repository / "patches/addon-test-mod/evil.py").exists())
        self.assertEqual((repository / "install.py").read_bytes(), (ROOT / "src/bridge/trusted/install.py").read_bytes())
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse(list((self.data ).glob(".import-*")))

    def test_next_version_changes_library_only_and_keeps_old_package_available(self):
        import_archive(self.archive(), self.data)
        previous = Path(library_rows(self.data)[0]["repository"])
        import_archive(self.archive(name="new.zip", version="9.1.0"), self.data)
        self.assertEqual(library_rows(self.data)[0]["version"], "9.1.0")
        self.assertTrue(previous.is_dir())
        self.assertFalse((self.root / "game").exists())

    def test_unsafe_paths_and_windows_collisions_do_not_change_index(self):
        import_archive(self.archive(), self.data)
        index = self.data / "catalog.json"
        previous = index.read_bytes()
        for name in ("../escaped", "/absolute", "C:/outside", "dir\\file", "aux.txt", "trailing./x"):
            with self.subTest(name=name):
                # ZipInfo normalizes Windows separators during construction.
                # Restore the literal unsafe name to exercise the actual reader.
                entry = zipfile.ZipInfo("placeholder")
                entry.filename = entry.orig_filename = name
                archive = self.archive(name="bad.zip", extra=lambda package: package.writestr(entry, b"x"))
                with self.assertRaises(ValueError):
                    import_archive(archive, self.data)
                self.assertEqual(index.read_bytes(), previous)
        archive = self.archive(name="case.zip", extra=lambda package: package.writestr("TEST-MOD-V9.0.0/ROMFS/TEST.BIN", b"x"))
        with self.assertRaises(ValueError):
            import_archive(archive, self.data)
        self.assertFalse((self.root / "escaped").exists())

    def test_symlink_entry_is_rejected(self):
        link = zipfile.ZipInfo("release/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.archive(extra=lambda package: package.writestr(link, "outside"))
        with self.assertRaises(ValueError):
            import_archive(archive, self.data)
        self.assertEqual(library_rows(self.data), [])

    def test_source_packages_and_oversized_archives_are_not_published(self):
        archive = self.root / "source.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("patches/item-wheel/manifest.json", "{}")
        with self.assertRaisesRegex(ValueError, "Optional Builder"):
            import_archive(archive, self.data)
        with patch("zip_library.MAX_EXPANDED", 1), self.assertRaises(ValueError):
            import_archive(self.archive(), self.data)
        self.assertEqual(library_rows(self.data), [])

    def test_flat_single_mod_folder_is_supported(self):
        import_archive(self.archive(prefix="Test-Mod"), self.data)
        self.assertEqual(library_rows(self.data)[0]["id"], "addon-test-mod")

    def test_incomplete_code_addon_or_wrong_build_is_refused(self):
        for missing in (True, False):
            archive = self.archive(name="invalid.zip")
            with zipfile.ZipFile(archive) as source:
                files = {entry.filename: source.read(entry) for entry in source.infolist()}
            if missing:
                del files["Test-Mod-v9.0.0/exefs/subsdk1"]
            else:
                key = "Test-Mod-v9.0.0/exefs/main"
                data = bytearray(files[key]); data[0x40:0x60] = b"x"*32; files[key] = bytes(data)
            with zipfile.ZipFile(archive, "w") as output:
                for name, payload in files.items():
                    output.writestr(name, payload)
            with self.assertRaises(ValueError):
                import_archive(archive, self.data)
            self.assertEqual(library_rows(self.data), [])

    def test_catalog_prefers_import_and_does_not_claim_github_update_source(self):
        import_archive(self.archive(), self.data)
        settings = Settings(game_dir=str(self.root / "game"), mods_repo=str(self.data))
        with patch.object(bridge, "event") as events:
            bridge.snapshot(settings, self.root / "legacy", self.data)
        row = events.call_args.kwargs["catalog"][0]
        self.assertEqual(row["version"], "9.0.0")
        self.assertEqual(row["origin"], "addon")
        self.assertFalse(row["canUpdate"])

    def catalog(self):
        settings = Settings(game_dir=str(self.root / "game"), mods_repo=str(self.data))
        with patch.object(bridge, "event") as events:
            bridge.snapshot(settings, self.root / "legacy", self.data)
        return events.call_args.kwargs["catalog"]

    def test_presentation_uses_archive_metadata_even_for_a_known_technical_profile(self):
        known = dict(id="item-wheel",name="Technical engine name",version="0.1.7")
        with patch("zip_library._recognized_profile", return_value=known):
            import_archive(self.archive(metadata=dict(name="Mon titre",version="2.0",
                           description="Description du créateur",author="Créateur")), self.data)
        row = self.catalog()[0]
        self.assertEqual(row["id"], "item-wheel")
        self.assertEqual(row["version"], "0.1.7")
        self.assertEqual(row["displayVersion"], "2.0")
        self.assertEqual(row["title"], "Mon titre")
        self.assertEqual(row["description"], "Description du créateur")
        self.assertEqual(row["author"], "Créateur")
        self.assertEqual(row["contentSummary"], "2 fichier(s) ExeFS · 1 fichier(s) RomFS")

    def test_missing_metadata_does_not_invent_a_description(self):
        import_archive(self.archive(name="Mon-addon.zip", metadata={}), self.data)
        row = self.catalog()[0]
        self.assertEqual(row["title"], "Mon-addon")
        self.assertEqual(row["description"], "")
        self.assertEqual(row["author"], "")
        self.assertEqual(row["displayVersion"], "Version non renseignée")

    def test_old_imports_use_factual_fallback_without_changing_prepared_data(self):
        import_archive(self.archive(), self.data)
        index = self.data / "catalog.json"
        document = json.loads(index.read_text(encoding="utf-8"))
        record = document["mods"]["addon-test-mod"]
        record.pop("presentation")
        index.write_text(json.dumps(document), encoding="utf-8")
        repo = Path(library_rows(self.data)[0]["repository"])
        manifest = repo / "patches/addon-test-mod/manifest.json"
        before = manifest.read_bytes()
        row = self.catalog()[0]
        self.assertEqual(row["title"], "mod")
        self.assertEqual(row["description"], "")
        self.assertEqual(manifest.read_bytes(), before)

    def test_partial_batch_reports_errors_without_install_or_compile(self):
        settings = Settings(game_dir=str(self.root / "game"), mods_repo=str(self.data))
        with patch("manager_worker.Worker") as worker, patch.object(bridge, "event") as events:
            bridge.run(dict(action="import_zip", settings=settings.to_dict(),
                            archives=[str(self.archive()), str(self.root / "missing.zip")]),
                       self.root / "legacy", self.data)
        worker.assert_not_called()
        result = next(call.kwargs for call in events.call_args_list if call.args == ("import_result",))
        self.assertEqual(result["imported"], ["addon-test-mod"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertFalse((self.root / "game").exists())

    def test_apply_does_not_substitute_a_cloned_repository(self):
        import_archive(self.archive(), self.data)
        repository = library_rows(self.data)[0]["repository"]
        settings = Settings(source="original.nup", mods_repo=str(self.data))
        with patch("manager_worker.Worker") as worker, \
             patch.object(bridge, "snapshot"), patch.object(bridge, "event"), \
             patch.object(bridge, "game_directory"), patch.object(bridge, "build_inputs"):
            bridge.run(dict(action="apply", settings=settings.to_dict(),
                            variant="addon-test-mod", repository=repository),
                       self.root / "legacy", self.data)
        self.assertEqual(worker.call_args.args[0].mods_repo, repository)
        self.assertTrue(Path(worker.call_args.args[0].workspace).is_relative_to(self.data / "workspaces/longshot"))

    def test_library_directory_switch_does_not_merge_previous_imports(self):
        import_archive(self.archive(), self.data)
        self.assertEqual(len(library_rows(self.data)), 1)
        self.assertEqual(library_rows(self.root / "empty-library"), [])
        settings = Settings(mods_repo=str(self.root / "empty-library"))
        with patch.object(bridge, "event") as events:
            bridge.snapshot(settings, ROOT / "src/core", self.data)
        self.assertEqual(events.call_args.kwargs["catalog"], [])

    def romfs_addon(self, payload=b"texture", version="1.0.0"):
        archive = self.root / "Textures.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("Textures/romfs/texture.bin", payload)
            package.writestr("Textures/mod-info.json", json.dumps(dict(name="Textures", version=version)))
        import_archive(archive, self.data)
        return library_rows(self.data)[0]

    def test_romfs_addon_installs_without_worker_and_can_be_removed(self):
        row = self.romfs_addon()
        game = self.root / "game"
        (game / "romfs").mkdir(parents=True)
        (game / "image.bin").write_bytes(b"original program")
        (game / "longshot.exe").touch()
        settings = Settings(game_dir=str(game), mods_repo=str(self.data))
        with patch("modmanager.deployment.ensure_game_closed"), patch("manager_worker.Worker") as worker, patch.object(bridge, "event") as events:
            bridge.run(dict(action="apply",settings=settings.to_dict(),variant=row["id"],repository=row["repository"]), ROOT / "src/core", self.data)
        worker.assert_not_called()
        self.assertEqual((game / "image.bin").read_bytes(), b"original program")
        self.assertEqual((game / "mods/hmb-addon-textures/romfs/texture.bin").read_bytes(), b"texture")
        catalog = next(call.kwargs["catalog"] for call in events.call_args_list if call.args == ("snapshot",))
        self.assertTrue(catalog[0]["installed"])
        self.assertFalse(remove_entry(self.data, row['id'], row['repository']))
        self.assertEqual(library_rows(self.data), [])
        self.assertEqual((game / 'mods/hmb-addon-textures/romfs/texture.bin').read_bytes(), b'texture')
        from modmanager.removal import uninstall_overlay
        uninstall_overlay(game, "overlay:hmb-addon-textures")
        self.assertFalse((game / "mods/hmb-addon-textures").exists())

    def test_romfs_conflict_and_external_changes_are_refused(self):
        from addon_overlay import install_overlay
        row = self.romfs_addon()
        game = self.root / "game"
        (game / "romfs").mkdir(parents=True)
        (game / "image.bin").write_bytes(b"original")
        other = game / "mods/another/romfs/texture.bin"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"other")
        with patch("modmanager.deployment.ensure_game_closed"):
            with self.assertRaisesRegex(ValueError, "Conflit"):
                install_overlay(row, game)
            other.unlink()
            install_overlay(row, game)
            (game / "mods/hmb-addon-textures/romfs/texture.bin").write_bytes(b"external change")
            with self.assertRaisesRegex(ValueError, "hors du gestionnaire"):
                install_overlay(row, game)

    def test_failed_romfs_replacement_restores_previous_overlay(self):
        from addon_overlay import install_overlay
        row = self.romfs_addon()
        game = self.root / "game"
        (game / "romfs").mkdir(parents=True)
        (game / "image.bin").write_bytes(b"original")
        with patch("modmanager.deployment.ensure_game_closed"):
            install_overlay(row, game)
            row = self.romfs_addon(payload=b"updated",version="1.1.0")
            original = Path.rename
            def interrupted(path, target):
                if path.name == "payload":
                    raise OSError("interrupted")
                return original(path, target)
            with patch.object(Path, "rename", interrupted), self.assertRaises(OSError):
                install_overlay(row, game)
            self.assertEqual((game / "mods/hmb-addon-textures/romfs/texture.bin").read_bytes(), b"texture")
            install_overlay(row, game)
            self.assertEqual((game / "mods/hmb-addon-textures/romfs/texture.bin").read_bytes(), b"updated")


if __name__ == "__main__":
    unittest.main()
