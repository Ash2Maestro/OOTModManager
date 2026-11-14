"""Packaging contracts: isolated inputs, checksums and rejection of user data."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from release import (Release, make_zip, payload_files, publication_lock, qualification_environment,
                     read_version, sha256, source_files, write_result)


class ReleaseTests(unittest.TestCase):
    def test_qualification_compares_canonical_asset_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / 'payload'
            (payload / 'assets').mkdir(parents=True)
            release = Release(root, '1.2.3')
            release.write_manifest(payload)
            snapshot = 'HMBGUI ' + json.dumps(dict(type='snapshot',
                assets=str((payload / 'assets').resolve()), catalog=[], installed=[]))
            # Reaching the UI check proves that equivalent path spellings passed
            # the isolation check; no executable is needed for this unit test.
            with patch.object(release, 'run', side_effect=[
                    'OOTModManager 1.2.3', snapshot, RuntimeError('UI check reached')]):
                with self.assertRaisesRegex(RuntimeError, 'UI check reached'):
                    release.qualify(payload / 'assets' / '..')

    def test_headless_qualification_keeps_packaged_runtime_isolated(self):
        environment = dict(PYTHONPATH='developer-core', QT_PLUGIN_PATH='developer-qt',
                           QSG_RHI_BACKEND='vulkan', MOD_MANAGER_DATA='private-data',
                           OOT_RELEASE_HEADLESS='1')
        result = qualification_environment(environment)
        self.assertNotIn('PYTHONPATH', result)
        self.assertNotIn('QT_PLUGIN_PATH', result)
        self.assertNotIn('MOD_MANAGER_DATA', result)
        self.assertEqual(result['QT_QPA_PLATFORM'], 'offscreen')
        self.assertEqual(result['QSG_RHI_BACKEND'], 'd3d11')
        self.assertEqual(result['QSG_RHI_PREFER_SOFTWARE_RENDERER'], '1')
        self.assertNotIn('QT_QPA_PLATFORM', qualification_environment({}))

    def test_ci_result_file_identifies_the_validated_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = root / 'ci/result.json'
            output = root / 'release files'
            write_result(result, '1.2.3', output)
            self.assertEqual(json.loads(result.read_text()),
                             dict(version='1.2.3', directory=str(output.resolve())))
            self.assertFalse(result.with_name(result.name + '.tmp').exists())

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
        self.assertIn('.github/workflows/release.yml', relatives)
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
