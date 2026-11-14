"""Locations owned by the Longshot Launcher, read without modifying its state."""
import json
import os
from pathlib import Path


def launcher_root():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LongshotLauncher"


def tools_candidates():
    override = os.environ.get("LONGSHOT_TOOLS")
    candidates = [Path(override)] if override else []
    toolchains = launcher_root() / "toolchains"
    if toolchains.is_dir():
        candidates.extend(version / "LongshotBuilder/tools" for version in
                          sorted(toolchains.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)
                          if version.is_dir())
    return [path for path in candidates if (path / "nx2/make_game.py").is_file()
            and (path / "python/python.exe").is_file()]


def _builds():
    """Launcher metadata is optional and read-only; malformed data is ignored."""
    try:
        builds = json.loads((launcher_root() / "builds.json").read_text(encoding="utf-8-sig"))["builds"]
        if not isinstance(builds, list) or any(not isinstance(build, dict) for build in builds):
            return []
        return builds
    except (OSError, ValueError, KeyError, TypeError):
        return []


def default_build():
    """Return the launcher's chosen build; missing/corrupt metadata is optional."""
    builds = _builds()
    return next((build for build in builds if build.get("default")), builds[0] if builds else {})


def installation_source(game: Path) -> str:
    """Resolve a unique existing NUP for the selected folder, never the default build.

    Do not scan disks or infer a source from a filename-only RomFS marker. Missing,
    moved or ambiguous sources leave manual selection available to the user.
    """
    candidates = set()
    for build in _builds():
        folder, source = build.get('folder'), build.get('nup')
        if not isinstance(folder, str) or not isinstance(source, str) or not folder or not source:
            continue
        try:
            if not Path(folder).is_absolute() or Path(folder).resolve() != game.resolve():
                continue
            path = Path(source)
            if path.is_absolute() and path.suffix.lower() == '.nup' and path.is_file():
                candidates.add(path.resolve())
        except (OSError, ValueError):
            continue
    return str(next(iter(candidates))) if len(candidates) == 1 else ''
