"""Packaging contracts: isolated inputs, checksums and rejection of user data."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from release import Release, make_zip, payload_files, publication_lock, read_version, sha256, source_files


class ReleaseTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows publication lock')
    def test_publication_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with publication_lock(root):
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    with publication_lock(root):
                        self.fail('Concurrent publication was accepted')
            with publication_lock(root):
                pass

    def test_version_is_safe_for_filenames_and_cmake(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in ('../oops', '1.2', '1.2.3\nmalicious', '01.2.3', '65536.0.0'):
                (root / 'VERSION.txt').write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    read_version(root)
            (root / 'VERSION.txt').write_text('1.2.3\n')
            self.assertEqual(read_version(root), '1.2.3')

    def test_source_archive_excludes_local_settings_and_generated_files(self):
        files = list(source_files(ROOT))
        self.assertTrue(all(path.is_file() for path in files))
        relatives = {path.relative_to(ROOT).as_posix() for path in files}
        self.assertIn('VERSION.txt', relatives)
        self.assertIn('scripts/release.py', relatives)
        self.assertIn('src/ui/cpp/main.cpp', relatives)
        self.assertNotIn('development.json', relatives)
        self.assertIn('docs/third-party.md', relatives)
        self.assertFalse(any(name.startswith(('.tools/', '.local/', 'data/', 'build/', 'dist/', 'releases/')) for name in relatives))

    def test_manifest_and_zip_preserve_nested_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / 'payload'
            (payload / 'runtime').mkdir(parents=True)
            file = payload / 'runtime/python.exe'
            file.write_bytes(b'synthetic-runtime')
            release = Release(root, '1.2.3')
            release.write_manifest(payload)
            manifest = json.loads((payload / 'release-manifest.json').read_text())
            self.assertEqual(manifest['files']['runtime/python.exe']['sha256'], sha256(file))
            archive = root / 'release.zip'
            make_zip(archive, payload_files(payload), payload, 'OOTModManager')
            with zipfile.ZipFile(archive) as contents:
                self.assertEqual(contents.read('OOTModManager/runtime/python.exe'), b'synthetic-runtime')
                self.assertIsNone(contents.testzip())

    def test_qualification_refuses_user_data_before_starting_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / 'payload'
            payload.mkdir()
            release = Release(root, '1.2.3')
            release.write_manifest(payload)
            (payload / 'data').mkdir()
            with self.assertRaisesRegex(ValueError, 'user data'):
                release.qualify(payload)
