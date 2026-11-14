"""Source discovery is scoped to the selected installation, not launcher defaults."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modmanager.engines.longshot import LongshotBackend
from modmanager.engines import longshot_launcher


class InstallationSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.game = self.root / 'game'
        self.game.mkdir()
        self.source = self.root / 'original.nup'
        self.source.touch()
        patcher = patch.object(longshot_launcher, 'launcher_root', return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def metadata(self, entries):
        (self.root / 'builds.json').write_text(json.dumps(dict(builds=entries)))

    def test_exact_installation_wins_over_unrelated_default(self):
        self.metadata([dict(folder=str(self.root / 'other'), nup=str(self.root / 'wrong.nup'), default=True),
                       dict(folder=str(self.game), nup=str(self.source))])
        before = (self.root / 'builds.json').read_bytes()
        self.assertEqual(LongshotBackend().installation_source(self.game / '.'), str(self.source))
        self.assertEqual((self.root / 'builds.json').read_bytes(), before)

    def test_missing_or_invalid_metadata_does_not_block_manual_selection(self):
        for content in (None, '{invalid', '{}', '{"builds":{}}', '{"builds":[null]}'):
            with self.subTest(content=content):
                if content is not None:
                    (self.root / 'builds.json').write_text(content)
                self.assertEqual(LongshotBackend().installation_source(self.game), '')

    def test_missing_relative_and_non_nup_sources_are_not_suggested(self):
        for source in ('relative.nup', str(self.root / 'missing.nup'), str(self.game), None):
            with self.subTest(source=source):
                self.metadata([dict(folder=str(self.game), nup=source)])
                self.assertEqual(LongshotBackend().installation_source(self.game), '')

    def test_conflicting_records_are_not_chosen_arbitrarily(self):
        other = self.root / 'other.nup'
        other.touch()
        self.metadata([dict(folder=str(self.game), nup=str(source)) for source in (self.source, other)])
        self.assertEqual(LongshotBackend().installation_source(self.game), '')

    def test_duplicate_identical_records_are_unambiguous(self):
        self.metadata([dict(folder=str(self.game), nup=str(self.source))] * 2)
        self.assertEqual(LongshotBackend().installation_source(self.game), str(self.source))
