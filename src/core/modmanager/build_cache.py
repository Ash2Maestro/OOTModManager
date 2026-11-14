"""Compressed content-addressed build snapshots, with atomic migration and LRU eviction.

All operations use the cache lock. Restored game files are independent copies:
editing the game can never mutate a shared cache object.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid

import zstandard

from .pipeline import digest, inventory, no_links, safe_relative, tree_files, workspace_lock

DEFAULT_LIMIT = 2 * 1024**3


def check_limit(limit):
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("La limite du cache doit être positive")


def commit_manifest(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def entry_path(cache, key):
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("Clé de cache invalide")
    path = Path(cache) / key
    no_links(path)
    return path


def object_path(cache, sha):
    entry_path(cache, sha)  # Validate the digest before deriving a path.
    path = Path(cache) / ".objects" / sha[:2] / (sha + ".zst")
    no_links(path)
    return path


def metadata(cache, key):
    target = entry_path(cache, key)
    no_links(target / "build.json")
    data = json.loads((target / "build.json").read_text(encoding="utf-8"))
    if data.get("schema") not in (1, 2) or data.get("key") != key or not isinstance(data.get("files"), dict):
        raise ValueError("Cache de build non reconnu")
    for name, sha in data["files"].items():
        safe_relative(name)
        entry_path(cache, sha)
        if data["schema"] == 2:
            size = data.get("sizes", {}).get(sha)
            if not isinstance(size, int) or size < 0:
                raise ValueError("Taille d'objet de cache invalide")
    from .engines import get_engine
    layout = get_engine(data.get("engine", "longshot")).layout
    if layout.image not in data["files"] or not any(name in data["files"] for name in layout.executables):
        raise ValueError("Build natif incomplet")
    return target, data


def decode_object(cache, sha, size, output=None):
    h, count = hashlib.sha256(), 0
    try:
        with object_path(cache, sha).open("rb") as source, zstandard.ZstdDecompressor().stream_reader(source) as reader:
            while block := reader.read(4 << 20):
                count += len(block)
                if count > size:
                    raise ValueError("Objet de cache modifié : taille dépassée")
                h.update(block)
                if output is not None:
                    output.write(block)
    except zstandard.ZstdError as error:
        raise ValueError("Objet de cache modifié : compression invalide") from error
    if count != size or h.hexdigest() != sha:
        raise ValueError("Objet de cache modifié : empreinte incorrecte")


def read_build(cache, key):
    """Validate every byte before a caller starts changing its destination."""
    target, data = metadata(cache, key)
    if data["schema"] == 1:
        if inventory(target / "files") != data["files"]:
            raise ValueError("Le cache de build a été modifié ; aucune restauration effectuée")
    else:
        for sha in set(data["files"].values()):
            decode_object(cache, sha, data["sizes"][sha])
    return target, data


def put_object(cache, source, sha):
    target = object_path(cache, sha)
    size = source.stat().st_size
    if target.exists():
        decode_object(cache, sha, size)
        return size
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".writing-", dir=target.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as stream:
            compressor = zstandard.ZstdCompressor(level=3, write_checksum=True)
            compressor.copy_stream(stream, output)
            output.flush()
            os.fsync(output.fileno())
        # Verify the compressed temporary object before publishing it.
        h, count = hashlib.sha256(), 0
        with temporary.open("rb") as stream, zstandard.ZstdDecompressor().stream_reader(stream) as reader:
            while block := reader.read(4 << 20):
                h.update(block)
                count += len(block)
        if count != size or h.hexdigest() != sha:
            raise ValueError("Le fichier a changé pendant sa mise en cache")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return size


def touch(cache, key, data):
    data["used_ns"] = time.time_ns()
    commit_manifest(entry_path(cache, key) / "build.json", data)


def migrate_entry(cache, key):
    target, data = read_build(cache, key)
    if data["schema"] == 1:
        sizes = {}
        for name, sha in data["files"].items():
            sizes[sha] = put_object(cache, target / "files" / name, sha)
        data = dict(data, schema=2, sizes=sizes,
                    used_ns=data.get("used_ns", (target / "build.json").stat().st_mtime_ns))
        # The old copy remains intact until the new manifest is committed.
        commit_manifest(target / "build.json", data)
        read_build(cache, key)
    old = target / "files"
    if old.exists():
        # Also completes cleanup after interruption following manifest commit.
        tree_files(old)
        shutil.rmtree(old)
    return data


def keys(cache):
    return sorted(p.name for p in Path(cache).iterdir() if re.fullmatch(r"[0-9a-f]{64}", p.name) and p.is_dir())


def collect(cache, limit, keep=()):
    """Lock held: remove unreferenced objects, then least recently used entries.

    A protected entry can exceed the budget on its own; never evict the build
    just stored/restored or touch compilation objects outside this cache.
    """
    check_limit(limit)
    entries = {key: metadata(cache, key)[1] for key in keys(cache)}
    # Hidden directories are never visible snapshots. Finish interrupted
    # publication/eviction cleanup while the exclusive cache lock is held.
    for path in Path(cache).iterdir():
        if path.name.startswith((".snapshot-", ".evicted-")) and path.is_dir():
            no_links(path)
            if path.resolve().parent != Path(cache).resolve():
                raise ValueError("Dossier temporaire de cache invalide")
            tree_files(path)
            shutil.rmtree(path)
    def used_bytes():
        refs = {sha for data in entries.values() if data["schema"] == 2 for sha in data["files"].values()}
        total = sum(object_path(cache, sha).stat().st_size for sha in refs)
        total += sum(p.stat().st_size for key, data in entries.items() if data["schema"] == 1
                     for p in tree_files(entry_path(cache, key) / "files"))
        return total, refs
    total, refs = used_bytes()
    evicted = []
    for key in sorted(entries, key=lambda k: entries[k].get("used_ns", 0)):
        if total <= limit:
            break
        if key in keep:
            continue
        target = entry_path(cache, key)
        tree_files(target)
        retired = Path(cache) / (".evicted-" + uuid.uuid4().hex)
        target.rename(retired)
        shutil.rmtree(retired)
        del entries[key]
        evicted.append(key)
        total, refs = used_bytes()
    objects = Path(cache) / ".objects"
    no_links(objects)
    if objects.exists():
        for path in objects.glob("*/.writing-*"):
            no_links(path)
            if path.is_file() and re.fullmatch(r"[0-9a-f]{2}", path.parent.name):
                path.unlink()
        for path in objects.glob("*/*.zst"):
            if re.fullmatch(r"[0-9a-f]{64}", path.stem) and path.stem not in refs:
                no_links(path)
                path.unlink()
    for key in entries:
        for path in entry_path(cache, key).glob(".manifest-*"):
            no_links(path)
            if path.is_file():
                path.unlink()
    return {"bytes": total, "builds": len(entries), "objects": len(refs), "evicted": evicted}


def migrate_cache(cache, limit=DEFAULT_LIMIT, progress=lambda key: None):
    check_limit(limit)
    cache = Path(cache).resolve()
    no_links(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with workspace_lock(cache):
        for key in keys(cache):
            migrate_entry(cache, key)
            progress(key)
        return collect(cache, limit)


def store_build(cache, key, files, limit=DEFAULT_LIMIT, *, engine_id="longshot"):
    check_limit(limit)
    cache = Path(cache).resolve()
    no_links(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with workspace_lock(cache):
        target = entry_path(cache, key)
        if target.exists():
            data = migrate_entry(cache, key)
            if data.get("engine", "longshot") != engine_id:
                raise ValueError("Le cache appartient à un autre moteur.")
        else:
            hashes, sizes = {}, {}
            for name, source in files.items():
                safe_relative(name)
                sha = digest(source)
                sizes[sha] = put_object(cache, source, sha)
                hashes[name] = sha
            data = {"schema": 2, "engine": engine_id, "key": key, "files": hashes, "sizes": sizes}
            temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=cache))
            try:
                data["used_ns"] = time.time_ns()
                commit_manifest(temporary / "build.json", data)
                temporary.rename(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        touch(cache, key, data)
        return collect(cache, limit, keep=(key,))


def copy_file(cache, target, data, name, destination):
    if data["schema"] == 1:
        shutil.copy2(target / "files" / name, destination)
    else:
        sha = data["files"][name]
        with destination.open("wb") as output:
            decode_object(cache, sha, data["sizes"][sha], output)
