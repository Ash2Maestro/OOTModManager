"""Launch real entry points without PYTHONPATH or the repository as working directory."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProcessEntrypointsTests(unittest.TestCase):
    def test_source_lookup_uses_launcher_metadata_without_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            launcher = root / 'LongshotLauncher'
            launcher.mkdir()
            game = root / 'selected-game'
            game.mkdir()
            nup = root / 'original.nup'
            nup.write_bytes(b'unchanged-original')
            (launcher / 'builds.json').write_text(json.dumps(dict(builds=[
                dict(folder=str(game), nup=str(nup))])))
            env = dict(os.environ, LOCALAPPDATA=str(root))
            env.pop('PYTHONPATH', None)
            request = dict(action='resolve_source', settings=dict(
                engine='longshot', game_dir=str(game), source='previous.nup'))
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'src/bridge/worker.py'),
                                     '--core', str(ROOT / 'src/core'), '--data', str(root / 'data')],
                                    input=json.dumps(request), cwd=root, env=env, text=True,
                                    encoding='utf-8', capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            event = json.loads(result.stdout.strip()[7:])
            self.assertEqual(event['type'], 'source_detected')
            self.assertEqual(Path(event['source']), nup)
            self.assertEqual(event['previous_source'], 'previous.nup')
            self.assertEqual(nup.read_bytes(), b'unchanged-original')
            self.assertFalse((root / 'data').exists())

    def test_bridge_snapshot_starts_from_an_arbitrary_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            result = subprocess.run(
                [sys.executable, '-B', str(ROOT / 'src/bridge/worker.py'),
                 '--core', str(ROOT / 'src/core'), '--data', folder],
                input=json.dumps({'action': 'snapshot', 'settings': {'mods_repo': folder}}),
                cwd=folder, env=env, text=True, encoding='utf-8', capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            events = [json.loads(line[7:]) for line in result.stdout.splitlines() if line.startswith('HMBGUI ')]
            snapshot = next(event for event in events if event['type'] == 'snapshot')
            self.assertEqual(snapshot['catalog'], [])

    def test_core_cli_is_executable_after_source_relocation(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'src/core/cli.py'), '--help'],
                                    cwd=folder, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
