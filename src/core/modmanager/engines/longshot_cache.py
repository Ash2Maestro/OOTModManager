"""Longshot content-keyed object cache import; never replace an existing entry."""
import os
from pathlib import Path
import re
import shutil
import tempfile
from ..storage import no_links


def seed_object_cache(source: Path, destination: Path) -> int:
    """Copy immutable content-keyed objects, without replacing existing entries.

    The engine consumes an object only if its source/flags/dependency key matches.
    Publish atomically without replacement so compilers never read a partial copy.
    """
    no_links(source)
    no_links(destination)
    if not source.is_dir():
        raise ValueError("Cache d'objets introuvable : %s" % source)
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in source.iterdir():
        if not re.fullmatch(r"[a-f0-9]{40}\.o", path.name):
            continue
        no_links(path)
        target = destination / path.name
        if target.exists():
            continue
        descriptor, temporary = tempfile.mkstemp(prefix=".hmb-cache-", dir=destination)
        os.close(descriptor)
        try:
            shutil.copyfile(path, temporary)
            try:
                if os.name == "nt":
                    # Windows rename is atomic and refuses an existing target.
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
                count += 1
            except FileExistsError:
                pass
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return count
