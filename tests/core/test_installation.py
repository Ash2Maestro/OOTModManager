"""Installed renderer reuse must reject mismatched tools and modified binaries."""
from pathlib import Path
import tempfile
import unittest
from modmanager.engines.longshot_runtime import renderer, environment


class InstalledRendererTests(unittest.TestCase):
    def test_version_and_binary_identity_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game, tools = root / 'game', root / 'tools'
            (game / 'bin').mkdir(parents=True)
            tools.mkdir()
            (game / 'longshot_version.txt').write_text('version=v2.2.0-rc.1\n')
            (tools / 'version.txt').write_text('v2.2.0-rc.1')
            binary = game / 'bin/longshot_vk.dll'
            binary.write_bytes(b'installed renderer')
            name, fingerprint = renderer(game, tools)
            report = dict(prebuilt_renderer=str(game/name), build_options=dict(renderer_sha256=fingerprint))
            self.assertEqual(environment(report), {'LONGSHOT_VK_PREBUILT': str(binary)})
            binary.write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError, 'changé'):
                environment(report)
            (tools / 'version.txt').write_text('v2.1.0')
            with self.assertRaisesRegex(ValueError, 'versions différentes'):
                renderer(game, tools)
