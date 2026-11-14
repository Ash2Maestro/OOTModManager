"""Runtime paths never depend on source layout and never create data on lookup."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modmanager.paths import AppPaths


class AppPathsTests(unittest.TestCase):
    def test_explicit_root_overrides_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, MOD_MANAGER_DATA='ignored'):
            root = Path(folder) / 'runtime'
            paths = AppPaths.current(str(root))
            self.assertEqual(paths.library, root / 'library')
            self.assertEqual(paths.native_cache('longshot'), root / 'cache/native-builds/longshot')
            self.assertEqual(paths.workspaces('longshot'), root / 'workspaces/longshot')
            self.assertFalse(root.exists())

    def test_environment_override(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, MOD_MANAGER_DATA=folder):
            self.assertEqual(AppPaths.current().root, Path(folder).resolve())

    def test_engine_name_cannot_escape_root(self):
        paths = AppPaths(Path('data'))
        for name in ('../other', 'a/b', '', 'A', 'c:\\other'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                paths.native_cache(name)

    def test_compilation_directories_are_stable_and_do_not_collide(self):
        paths = AppPaths(Path('data'))
        first = paths.compilation(Path('one/mod'), 'longshot')
        self.assertEqual(first, paths.compilation(Path('one/mod'), 'longshot'))
        self.assertNotEqual(first, paths.compilation(Path('two/mod'), 'longshot'))
        self.assertEqual(first.parent, Path('data/cache/compilation/longshot'))
