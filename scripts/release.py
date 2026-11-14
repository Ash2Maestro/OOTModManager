"""Build and qualify a self-contained Windows release without changing user data.

Only a fully validated release is promoted from build/ to releases/. Each run has
its own directory and log; previous releases are never overwritten. Publication
to a hosting service is deliberately separate from local artifact creation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

from portable import assemble

ROOT = Path(__file__).resolve().parents[1]
APP = 'OOTModManager'
SDK = ROOT / '.tools/qt/6.8.3/msvc2022_64'
THEME_REQUIRED = ('chronicle.json', 'chronicle-header.png', 'chronicle-tapestry.jpg',
                  'button.png', 'body.otf', 'mission.otf')
SOURCE_DIRECTORIES = ('src', 'tests', 'scripts', 'i18n', 'licenses', 'assets')
SOURCE_FILES = ('VERSION.txt', 'LICENSE', 'README.md', 'CMakeLists.txt', '.gitignore', '.gitattributes', '.editorconfig',
                '.clang-format', 'Build.cmd', 'Format.cmd', 'Launch.cmd', 'Release.cmd')


def read_version(root: Path) -> str:
    value = (root / 'VERSION.txt').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('VERSION.txt must contain a version such as 0.1.0')
    if any(int(part) > 65535 for part in value.split('.')):
        raise ValueError('Version components must fit Windows version fields')
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def payload_files(root: Path):
    """Reject links so packaging cannot accidentally follow an external tree."""
    for path in sorted(root.rglob('*')):
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
        if path.is_symlink() or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise ValueError('Linked release input is not allowed: ' + str(path))
        if path.is_file():
            yield path


@contextmanager
def publication_lock(root: Path):
    """The OS releases this lock even when the packaging process is interrupted."""
    import msvcrt
    (root / 'build').mkdir(exist_ok=True)
    with (root / 'build/release.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('Une creation de release est deja en cours / A release is already running') from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def source_files(root: Path):
    for name in SOURCE_FILES:
        yield root / name
    for name in SOURCE_DIRECTORIES:
        for path in payload_files(root / name):
            if '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                yield path
    # Current documentation only; historical diagnostics can contain local paths.
    for path in sorted((root / 'docs').glob('*.md')):
        yield path


def make_zip(destination: Path, files, root: Path, prefix: str):
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, prefix + '/' + path.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive integrity check failed: ' + str(destination))


class Release:
    def __init__(self, root: Path, version: str):
        self.root, self.version = root, version
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        self.run_id = version + '-' + stamp + '-' + uuid.uuid4().hex[:6]
        self.logs = root / 'build/release-logs' / self.run_id
        self.logs.mkdir(parents=True)
        self.log = self.logs / 'release.log'
        self.environment = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        self.environment.pop('PYTHONPATH', None)
        # Allow explicitly configured integration tools; otherwise tests can skip
        # optional loader checks, while the delivered runtime is always tested.

    def note(self, text: str):
        print(text, flush=True)
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write(text + '\n')

    def run(self, command, *, cwd=None, env=None, input=None, timeout=900):
        command = [str(value) for value in command]
        result = subprocess.run(command, cwd=cwd or self.root, env=env or self.environment,
                                input=input, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding='utf-8', errors='replace', timeout=timeout)
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write('\n> ' + subprocess.list2cmdline(command) + '\n' + result.stdout + '\n')
        if result.returncode:
            raise RuntimeError(f'Command failed ({result.returncode}): {command[0]}\n{result.stdout[-4000:]}')
        return result.stdout

    def stage(self, destination: Path):
        shutil.copy2(self.root / 'build/Release/OOTModManager.exe', destination / (APP + '.exe'))
        self.run([SDK / 'bin/windeployqt.exe', '--release', '--qmldir', self.root / 'src/ui/qml',
                  '--no-translations', '--no-compiler-runtime', destination / (APP + '.exe')])
        self.copy_compiler_runtime(destination)
        assemble(self.root, destination, Path(sys.executable))
        for folder in ('src/bridge', 'assets', 'i18n', 'licenses'):
            shutil.copytree(self.root / folder, destination / folder,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('LICENSE', 'VERSION.txt'):
            shutil.copy2(self.root / name, destination / name)
        shutil.copy2(self.root / 'docs/third-party.md', destination / 'THIRD_PARTY.md')
        (destination / 'README.txt').write_text(
            'OOTModManager ' + self.version + '\n\n'
            'Extract the entire ZIP into a writable folder, then open OOTModManager.exe.\n'
            'No system Python or Qt installation is required.\n'
            'Select your game, compatible source dump and Longshot tools in Settings.\n'
            'Game files, compiler tools and mods are not included.\n'
            'Your settings, library and caches stay in the data folder.\n'
            'To update: close the manager, extract the new version over its program files,\n'
            'and keep your data folder. Do not run from inside the ZIP.\n\n'
            'This build is not digitally signed. SHA256SUMS.txt verifies download integrity.\n', encoding='utf-8')
        for name in THEME_REQUIRED:
            if not (destination / 'assets' / name).is_file():
                raise FileNotFoundError('Missing visual resource: ' + name)
        self.write_manifest(destination)

    def copy_compiler_runtime(self, destination: Path):
        """App-local VC runtime: no administrator/redistributable installer needed."""
        locator = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        installation = Path(self.run([locator, '-latest', '-products', '*', '-property', 'installationPath']).strip())
        candidates = sorted((installation / 'VC/Redist/MSVC').glob('*/x64/Microsoft.VC*.CRT'))
        if not candidates:
            raise FileNotFoundError('Visual C++ redistributable DLLs were not found in Visual Studio')
        for path in candidates[-1].glob('*.dll'):
            shutil.copy2(path, destination / path.name)
        for name in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
            if not (destination / name).is_file():
                raise FileNotFoundError('Missing app-local runtime: ' + name)

    def write_manifest(self, destination: Path):
        files = {path.relative_to(destination).as_posix():
                 dict(bytes=path.stat().st_size, sha256=sha256(path)) for path in payload_files(destination)}
        manifest = dict(schema=1, application=APP, version=self.version, platform='windows-x64',
                        createdUtc=datetime.now(timezone.utc).isoformat(), files=files)
        (destination / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    def qualify(self, folder: Path):
        """Use only the relocated runtime, with isolated empty user data."""
        env = dict(self.environment)
        for key in tuple(env):
            if key.startswith(('QT_', 'QML', 'PYTHON')) or key == 'MOD_MANAGER_DATA':
                env.pop(key, None)
        env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
        env['QT_QUICK_CONTROLS_STYLE'] = 'Basic'
        manifest = json.loads((folder / 'release-manifest.json').read_text(encoding='utf-8'))
        for relative, entry in manifest['files'].items():
            path = folder / relative
            if path.stat().st_size != entry['bytes'] or sha256(path) != entry['sha256']:
                raise ValueError('Payload mismatch: ' + relative)
        if (folder / 'development.json').exists() or (folder / 'data').exists():
            raise ValueError('Development/user data found in release')
        reported_version = self.run([folder / (APP + '.exe'), '--version'], cwd=folder, env=env).strip()
        if reported_version != APP + ' ' + self.version:
            raise ValueError('Executable and archive versions differ: ' + reported_version)
        with tempfile.TemporaryDirectory(prefix='recomp-release-data-') as temporary:
            data = Path(temporary)
            text = self.run([folder / 'runtime/python.exe', '-I', '-B', folder / 'src/bridge/worker.py',
                             '--core', folder / 'src/core', '--data', data], cwd=folder, env=env,
                            input=json.dumps(dict(action='snapshot', settings=dict(mods_repo=str(data / 'library')))))
            events = [json.loads(line[7:]) for line in text.splitlines() if line.startswith('HMBGUI ')]
            snapshot = next(event for event in events if event['type'] == 'snapshot')
            if Path(snapshot['assets']) != folder / 'assets' or snapshot['catalog'] or snapshot['installed']:
                raise ValueError('Release startup was not isolated')
            for language in ('fr', 'en'):
                self.run([folder / (APP + '.exe'), '--data', data, '--smoke', '--smoke-language', language],
                         cwd=folder, env=env, timeout=90)
                smoke = (data / 'logs/runtime.log').read_text(encoding='utf-8')
                if 'Smoke bundled theme: true' not in smoke or 'QML warnings: 0' not in smoke:
                    raise ValueError('Packaged UI smoke check incomplete')
                shutil.copy2(data / 'logs/runtime.log', self.logs / ('smoke-' + language + '.log'))

    def execute(self) -> Path:
        self.note('[1/6] Tests Python / Python tests')
        self.run([sys.executable, '-B', 'scripts/test.py'])
        self.note('[2/6] Compilation et tests C++ / Build and C++ tests')
        self.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts/Build.ps1'])
        self.note('[3/6] Assemblage du programme autonome / Assemble standalone runtime')
        with tempfile.TemporaryDirectory(prefix='release-', dir=self.root / 'build') as temporary:
            staging = Path(temporary)
            payload = staging / APP
            payload.mkdir()
            self.stage(payload)
            self.note('[4/6] Creation et controle des archives / Create and verify archives')
            artifacts = staging / 'artifacts'
            artifacts.mkdir()
            portable = artifacts / f'{APP}-{self.version}-windows-x64.zip'
            make_zip(portable, payload_files(payload), payload, APP)
            make_zip(artifacts / f'{APP}-{self.version}-sources.zip', source_files(self.root), self.root, APP)
            self.note('[5/6] Test du ZIP extrait et deplace / Test relocated extracted ZIP')
            with tempfile.TemporaryDirectory(prefix='Recomp release relocated ') as relocated:
                with zipfile.ZipFile(portable) as archive:
                    archive.extractall(relocated)
                self.qualify(Path(relocated) / APP)
            checksums = ''.join(f'{sha256(path)}  {path.name}\n' for path in sorted(artifacts.glob('*.zip')))
            (artifacts / 'SHA256SUMS.txt').write_text(checksums, encoding='ascii')
            (artifacts / 'RELEASE-NOTES.txt').write_text(
                f'OOTModManager {self.version}\nWindows x64, portable, unsigned.\n'
                'Publish the Windows ZIP, matching source ZIP and SHA256SUMS.txt together.\n'
                'All packaging checks passed; game/toolchain files are not included.\n'
                'Review the theme asset redistribution rights described in THIRD_PARTY.md.\n', encoding='utf-8')
            self.note('[6/6] Validation terminee / Release validated')
            output = self.root / 'releases' / self.run_id
            output.parent.mkdir(exist_ok=True)
            artifacts.rename(output)
        self.note('Livrable / Release: ' + str(output))
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-open', action='store_true', help='Do not open the output folder')
    args = parser.parse_args()
    release = Release(ROOT, read_version(ROOT))
    print('Journal / Log: ' + str(release.log), flush=True)
    try:
        with publication_lock(ROOT):
            destination = release.execute()
    except Exception as error:
        release.note('ECHEC / FAILED: ' + str(error))
        return 1
    if not args.no_open:
        os.startfile(destination)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
