"""Download immutable release sources and validate archives before preparing a mod."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile
from urllib.parse import quote
from urllib.request import Request, urlopen

MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_EXTRACTED = 512 * 1024 * 1024


def request(url):
    return Request(url, headers={"User-Agent": "OOTModManager-release-install",
                                 "Accept": "application/vnd.github+json"})


def resolve_commit(source, tag):
    if not tag.startswith(source.tag_prefix):
        raise ValueError("La release ne correspond pas au mod sélectionné")
    url = "https://api.github.com/repos/%s/commits/%s" % (source.repository, quote(tag, safe=""))
    with urlopen(request(url), timeout=20) as response:
        data = json.loads(response.read(1024 * 1024))
    commit = data.get("sha", "")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("GitHub n'a pas renvoyé un commit valide")
    return commit


def download(source, commit, destination, progress=lambda done, total: None):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Commit invalide")
    url = "https://codeload.github.com/%s/zip/%s" % (source.repository, commit)
    destination = Path(destination)
    temporary = destination.with_suffix(".part")
    h, done = hashlib.sha256(), 0
    try:
        with urlopen(request(url), timeout=30) as response, temporary.open("xb") as output:
            total = int(response.headers.get("Content-Length", 0)) or None
            if total and total > MAX_DOWNLOAD:
                raise ValueError("Archive trop volumineuse")
            while block := response.read(256 * 1024):
                done += len(block)
                if done > MAX_DOWNLOAD:
                    raise ValueError("Archive trop volumineuse")
                h.update(block)
                output.write(block)
                progress(done, total)
        if destination.exists():
            raise ValueError("L'archive de destination existe déjà")
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return h.hexdigest()


def extract_archive(archive, destination):
    """Validate the entire central directory before creating any extracted file."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Le dossier d'extraction doit être nouveau")
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if not entries or len(entries) > 10000 or sum(i.file_size for i in entries) > MAX_EXTRACTED:
            raise ValueError("Taille ou nombre de fichiers d'archive non pris en charge")
        seen, roots = set(), set()
        for info in entries:
            name = info.filename
            parts = PurePosixPath(name).parts
            mode = info.external_attr >> 16
            if (not parts or name.startswith("/") or "\\" in info.orig_filename or "\x00" in info.orig_filename or
                    any(p in (".", "..") or ":" in p or p.endswith((".", " ")) or
                        re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts) or
                    (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise ValueError("Chemin ou type de fichier dangereux dans l'archive : " + name)
            key = "/".join(parts).casefold()
            if key in seen:
                raise ValueError("Chemin dupliqué dans l'archive : " + name)
            seen.add(key)
            roots.add(parts[0])
        if len(roots) != 1:
            raise ValueError("Une archive de sources GitHub à racine unique est attendue")
        destination.mkdir(parents=True)
        for info in entries:
            path = destination.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as input_file, path.open("xb") as output:
                    while block := input_file.read(256 * 1024):
                        output.write(block)
    return destination / next(iter(roots))
