import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from modmanager.downloads import extract_archive, download
from modmanager.updates import UpdateSource
import install_release
from modmanager.models import Settings


class ArchiveTests(unittest.TestCase):
    def archive(self, folder, names):
        path = folder / "source.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name in names:
                if isinstance(name, zipfile.ZipInfo):
                    archive.writestr(name, "target")
                else:
                    info = zipfile.ZipInfo("placeholder")
                    info.filename = name
                    archive.writestr(info, b"data")
        return path

    def test_valid_archive_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            archive = self.archive(folder, ["repo/", "repo/patches/mod/manifest.json"])
            root = extract_archive(archive, folder / "out")
            self.assertEqual((root / "patches/mod/manifest.json").read_bytes(), b"data")
            with self.assertRaises(ValueError):
                extract_archive(archive, folder / "out")

    def test_reject_unsafe_entries_before_writing(self):
        link = zipfile.ZipInfo("repo/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entry in ("repo/../../outside", "C:/outside", "repo/a:stream", "repo/CON.txt", "repo/a.", "repo\\escape", link):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                archive = self.archive(folder, ["repo/good", entry])
                with self.assertRaises(ValueError):
                    extract_archive(archive, folder / "out")
                self.assertFalse((folder / "out").exists())

    def test_reject_case_collision_and_multiple_roots(self):
        for entries in (["repo/A", "repo/a"], ["one/file", "two/file"]):
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                with self.assertRaises(ValueError):
                    extract_archive(self.archive(folder, entries), folder / "out")

    def test_download_failure_leaves_no_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "source.zip"
            response = io.BytesIO(b"more than limit")
            response.headers = {}
            with patch("modmanager.downloads.urlopen", return_value=response), patch("modmanager.downloads.MAX_DOWNLOAD", 2):
                with self.assertRaises(ValueError):
                    download(UpdateSource("owner/repo", "v"), "a" * 40, target)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix(".part").exists())


class InstallTests(unittest.TestCase):
    def run_install(self, folder, fail=False, changed_installer=False):
        trusted = folder / "trusted"
        trusted.mkdir()
        for name in ("install.py", "nup_reader.py"):
            (trusted / name).write_text("trusted")
        old_game = folder / "old-game"
        old_game.mkdir()
        (old_game / "image.bin").write_bytes(b"previous working game")
        old_project = folder / "old-project"
        old_project.mkdir()
        settings = Settings(mods_repo=str(trusted), game_dir=str(old_game), workspace=str(old_project), variant="item-wheel")
        root = folder / "manager"
        root.mkdir()
        events = []

        def fake_download(source, commit, archive, progress):
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("repo/install.py", "changed" if changed_installer else "trusted")
                package.writestr("repo/nup_reader.py", "trusted")
                package.writestr("repo/patches/item-wheel/manifest.json", json.dumps({"version": "0.1.8"}))
                package.writestr("repo/evil.py", "never execute")
            return "b" * 64

        class FakeWorker:
            def __init__(self, new):
                self.settings = new
                self.workspace = Path(new.workspace)
            def validate(self):
                pass
            def prepare(self):
                self.workspace.mkdir(parents=True)
                (self.workspace / "hmb-report.json").write_text("{}")
            def execute(self):
                if fail:
                    raise ValueError("failed audit")
                Path(self.settings.game_dir).mkdir(exist_ok=True)
                (Path(self.settings.game_dir) / "image.bin").write_bytes(b"new game")

        with patch.dict("os.environ", MOD_MANAGER_DATA=str(root)), patch.object(install_release, "fetch_releases", return_value=[{"tag_name": "item-wheel-v0.1.8"}]), \
             patch.object(install_release, "resolve_commit", return_value="a" * 40), patch.object(install_release, "download", side_effect=fake_download), \
             patch.object(install_release, "read_manifest", return_value=(None, {"version": "0.1.8"})), patch.object(install_release, "Worker", FakeWorker), \
             patch.object(install_release, "emit", side_effect=lambda kind, **kw: events.append((kind, kw))):
            if fail:
                with self.assertRaises(ValueError):
                    install_release.install(settings, "item-wheel-v0.1.8")
            else:
                install_release.install(settings, "item-wheel-v0.1.8")
        self.assertEqual((old_game / "image.bin").read_bytes(), b"previous working game" if fail else b"new game")
        if fail:
            self.assertFalse(any(kind == "installed" for kind, _ in events))
        else:
            installed = next(data for kind, data in events if kind == "installed")
            self.assertEqual(installed["settings"]["game_dir"], str(old_game))
            self.assertFalse((Path(installed["settings"]["mods_repo"]) / "evil.py").exists())
            self.assertEqual((Path(installed["settings"]["mods_repo"]) / "install.py").read_text(), "trusted")
            self.assertEqual(installed["previous"], settings.to_dict())

    def test_release_reuses_selected_game_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_install(Path(tmp))

    def test_failed_audit_does_not_select_new_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_install(Path(tmp), fail=True)

    def test_downloaded_installer_is_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_install(Path(tmp), changed_installer=True)
