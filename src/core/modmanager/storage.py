"""Filesystem primitives shared by orchestration and trusted engine modules."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import sys


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def no_links(path: Path):
    for part in [path, *path.parents]:
        if is_link(part):
            raise ValueError("Lien/jonction refuse : %s" % part)


def safe_relative(value: str) -> Path:
    if "\\" in value or ":" in value or "\0" in value:
        raise ValueError("Chemin non portable : %r" % value)
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or not parsed.parts or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("Chemin relatif invalide : %r" % value)
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved |= {p + str(n) for p in ("COM", "LPT") for n in range(1, 10)}
    for part in parsed.parts:
        if part.endswith((".", " ")) or any(c in part for c in '<>"|?*') or any(ord(c) < 32 for c in part):
            raise ValueError("Composant de chemin invalide : %r" % part)
        if part.split(".")[0].upper() in reserved:
            raise ValueError("Nom reserve Windows : %r" % part)
    return Path(*parsed.parts)


def tree_files(root: Path) -> list[Path]:
    no_links(root)
    result = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if is_link(path):
                raise ValueError("Lien/jonction refuse dans les donnees : %s" % path)
        result.extend(Path(directory) / name for name in sorted(files))
    return sorted(result)


def independent(root: Path, protected: list[Path]):
    """Refuse outputs overlapping inputs, including ancestor paths before any write."""
    no_links(root)
    root = root.resolve()
    for path in protected:
        path = path.resolve()
        if root == path or root.is_relative_to(path) or path.is_relative_to(root):
            raise ValueError("Le dossier de travail doit etre separe de la source/des depots : %s" % path)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("Module Python introuvable : %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def inventory(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): digest(p) for p in tree_files(root)}
