"""Run isolated engine and bridge suites without touching development data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='recomp-manager-tests-') as data:
        env = dict(os.environ, MOD_MANAGER_DATA=data, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ('src/core', 'src/bridge')))
        for suite in ('tests/core', 'tests'):
            subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', suite,
                            '-p', 'test_*.py'], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
