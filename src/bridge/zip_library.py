"""Import Addon ZIPs only, without executing code supplied by an archive.

Packages are immutable and addressed by archive SHA256. Only validated patches and
the bundled installer are retained. An atomic index selects the library version;
import never changes the selected game's installation or build settings.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_MANIFEST = 1024 * 1024
INDEX = "catalog.json"
SLUG = re.compile(r"[a-z0-9-]{1,100}")
RESERVED = re.compile(r"(?i)(con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?")


def _write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _entries(package):
    """Validate all paths and advertised sizes before extracting a single file."""
    entries = package.infolist()
    if not entries or len(entries) > MAX_ENTRIES:
        raise ValueError("Archive vide ou contenant trop de fichiers.")
    if sum(entry.file_size for entry in entries) > MAX_EXPANDED:
        raise ValueError("Archive décompressée trop volumineuse (limite : 512 Mio).")
    seen = {}
    for entry in entries:
        name = entry.orig_filename
        parts = name.rstrip("/").split("/")
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if (not name or "\\" in name or "\0" in name or len(name) > 240
                or len(parts) > 20 or any(
                    not part or part in (".", "..") or part.endswith((".", " "))
                    or any(ord(char) < 32 or char in ':<>"|?*' for char in part)
                    or RESERVED.fullmatch(part) for part in parts)
                or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                or entry.flag_bits & 1):
            raise ValueError("Chemin, lien ou fichier chiffré interdit dans le ZIP : " + name)
        key = "/".join(parts).casefold()
        if key in seen:
            raise ValueError("Chemin dupliqué dans le ZIP : " + name)
        seen[key] = entry.is_dir()
    for key in seen:
        parents = PurePosixPath(key).parents
        if any(str(parent) in seen and not seen[str(parent)] for parent in parents):
            raise ValueError("Un fichier masque un dossier dans le ZIP : " + key)
    return entries


def _extract(package, entries, destination):
    total = 0
    for entry in entries:
        target = destination.joinpath(*PurePosixPath(entry.filename).parts)
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with package.open(entry) as source, target.open("xb") as output:
            while block := source.read(256 * 1024):
                total += len(block)
                written += len(block)
                if total > MAX_EXPANDED or written > entry.file_size:
                    raise ValueError("Le ZIP dépasse la taille déclarée.")
                output.write(block)
        if written != entry.file_size:
            raise ValueError("Fichier incomplet dans le ZIP : " + entry.filename)


def library_root(folder):
    if not str(folder).strip():
        raise ValueError("Choisissez le dossier de la bibliothèque dans les paramètres.")
    return Path(folder).resolve()


def library_rows(folder):
    """Only the selected library is visible; never scan a cloned repository."""
    root = library_root(folder)
    path = root / INDEX
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != 2 or not isinstance(document.get("mods"), dict):
        raise ValueError("Index de bibliothèque Addon invalide.")
    rows = []
    for slug, record in document["mods"].items():
        checksum = record.get("sha256", "")
        if not SLUG.fullmatch(slug) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Identifiant invalide dans la bibliothèque.")
        repo = root / "packages" / checksum
        if not (repo / "patches" / slug / "manifest.json").is_file():
            raise ValueError("Addon importé manquant pour " + slug)
        rows.append(dict(record, id=slug, repository=str(repo)))
    return rows


def _addon_root(extraction):
    roots = {path.parent for path in extraction.rglob("*")
             if path.is_dir() and path.name in ("exefs", "romfs")}
    if len(roots) != 1:
        raise ValueError("Un ZIP Addon contenant exefs et/ou romfs est attendu. "
                         "Les ZIP de sources et Optional Builder ne sont pas acceptés.")
    return roots.pop()


def _presentation(metadata):
    """Author-provided text is optional; filenames never imply gameplay features."""
    def text(key, limit):
        value = metadata.get(key)
        return value.strip()[:limit] if isinstance(value, str) else ""
    return dict(name=text("name", 200), version=text("version", 100),
                description=text("description", 8192), author=text("author", 200),
                metadataProvided=any(text(key, 8192) for key in ("name", "version", "description", "author")))


def _recognized_profile(hashes):
    """Technical compatibility profiles only; never a source of presentation text."""
    signatures = json.loads(Path(__file__).with_name("addon_signatures.json").read_text(encoding="utf-8"))
    return next((known for known in signatures
                 if all(hashes.get(name) == digest for name, digest in known["modules"].items())), None)


def _metadata(addon, archive, hashes):
    from modmanager.pipeline import BUILD_ID, TITLE_ID
    information = addon / "mod-info.json"
    metadata = {}
    if information.is_file():
        if information.stat().st_size > MAX_MANIFEST:
            raise ValueError("Métadonnées Addon trop volumineuses.")
        metadata = json.loads(information.read_text(encoding="utf-8-sig"))
        if not isinstance(metadata, dict):
            raise ValueError("Métadonnées Addon invalides.")
        for key, expected in (("title_id", TITLE_ID), ("build_id", BUILD_ID)):
            if key in metadata and str(metadata[key]).lower() != expected.lower():
                raise ValueError("L'Addon ne cible pas la version du jeu prise en charge.")
    presentation = _presentation(metadata)
    known = _recognized_profile(hashes)
    if known:
        return known["id"], known["name"], known["version"], presentation
    name = presentation["name"] or (addon.name if addon.name != "extracted" else archive.stem)[:200]
    name = re.sub(r"^(?:\d+-)?OOT[-_ ]", "", name, flags=re.I)
    version = presentation["version"]
    match = re.search(r"(?:^|[-_ ])v?(\d+\.\d+(?:\.\d+)?(?:[-.][a-zA-Z0-9]+)*)", name)
    if match and not version:
        version = match.group(1)
        name = name[:match.start()].strip("-_ ") or name
    slug = "addon-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]
    if slug == "addon-":
        raise ValueError("L'Addon doit avoir un nom identifiable.")
    return slug, name, version or "non renseignée", presentation


def import_archive(archive, folder):
    from modmanager.formats import MODULES, Nso
    from modmanager.pipeline import BUILD_ID, TITLE_ID, UPDATE, no_links, read_manifest, workspace_lock

    archive = Path(archive)
    if archive.suffix.lower() != ".zip" or not archive.is_file():
        raise ValueError("Choisissez un fichier ZIP Addon local existant.")
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError("ZIP trop volumineux (limite : 256 Mio).")
    root = library_root(folder)
    no_links(root)
    root.mkdir(parents=True, exist_ok=True)
    with workspace_lock(root), tempfile.TemporaryDirectory(prefix=".import-", dir=root) as temporary:
        temporary = Path(temporary)
        extraction = temporary / "extracted"
        extraction.mkdir()
        with archive.open("rb") as stream:
            checksum = _digest(stream)
            stream.seek(0)
            with zipfile.ZipFile(stream) as package:
                _extract(package, _entries(package), extraction)
        addon = _addon_root(extraction)
        payloads = []
        hashes = {}
        for kind in ("exefs", "romfs"):
            for path in sorted((addon / kind).rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(addon).as_posix()
                if kind == "exefs":
                    if path.parent != addon / "exefs" or path.name not in MODULES:
                        raise ValueError("Fichier ExeFS non pris en charge : " + relative)
                    module = Nso(path.read_bytes())
                    if path.name == "main" and module.build_id != BUILD_ID:
                        raise ValueError("Le module main ne cible pas le build du jeu pris en charge.")
                with path.open("rb") as stream:
                    hashes[relative] = _digest(stream, MAX_EXPANDED)
                payloads.append((relative, path))
        kind = "native" if (addon / "exefs").is_dir() else "romfs"
        if not payloads:
            raise ValueError("Addon vide.")
        if kind == "native" and not {"exefs/main", "exefs/subsdk1"}.issubset(hashes):
            raise ValueError("Cet Addon de code doit fournir main et subsdk1 ; les IPS isolés ne sont pas encore pris en charge.")
        slug, name, version, presentation = _metadata(addon, archive, hashes)
        prepared = temporary / "package"
        patches = prepared / "patches" / slug
        patches.mkdir(parents=True)
        files = []
        for index, (relative, path) in enumerate(payloads):
            patch = f"{index:05d}.payload"
            shutil.move(str(path), str(patches / patch))
            files.append(dict(path=relative, kind="raw", patch=patch, target_sha256=hashes[relative]))
        manifest = dict(name=name, version=version, title_id=TITLE_ID, update_version=UPDATE,
                        build_id=BUILD_ID, files=files, addon_kind=kind)
        (patches / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if kind == "native":
            read_manifest(prepared, slug)
        for filename in ("install.py", "nup_reader.py"):
            shutil.copyfile(Path(__file__).with_name("trusted") / filename, prepared / filename)
        destination = root / "packages" / checksum
        no_links(destination)
        destination.parent.mkdir(exist_ok=True)
        new_package = not destination.exists()
        if new_package:
            prepared.replace(destination)
        index = root / INDEX
        document = json.loads(index.read_text(encoding="utf-8")) if index.exists() else dict(schema=2, mods={})
        if document.get("schema") != 2 or not isinstance(document.get("mods"), dict):
            raise ValueError("Index de bibliothèque Addon invalide.")
        previous = document['mods'].get(slug, {})
        unprepared = previous.get('unprepared', False) if previous.get('sha256') == checksum else new_package
        document["mods"][slug] = dict(sha256=checksum, archiveName=archive.name, name=name,
                                      version=version, kind=kind, presentation=presentation, unprepared=unprepared)
        _write_json(index, document)
        return [slug]


def pin_preparation(folder, row):
    """Pin before a native preparation starts, including interrupted attempts."""
    from modmanager.pipeline import no_links, workspace_lock
    root = library_root(folder)
    no_links(root)
    with workspace_lock(root):
        current = next((entry for entry in library_rows(folder)
                        if entry['id'] == row['id'] and entry['repository'] == row['repository']), None)
        if current is None:
            raise ValueError("Cet Addon a été retiré ou remplacé dans la bibliothèque.")
        marker = Path(current['repository']) / '.hmb-prepared'
        no_links(marker)
        marker.write_text('Referenced by a native preparation; retain on library removal.\n', encoding='utf-8')


def remove_entry(folder, identifier, repository):
    """Remove a library entry, never uninstall from the game.

    Only a package known never to have been prepared can be deleted. Legacy
    native packages without provenance are retained rather than breaking an
    externally located workspace. Pins survive cancellation and reimport.
    """
    from modmanager.pipeline import no_links, tree_files, workspace_lock
    root = library_root(folder)
    no_links(root)
    with workspace_lock(root):
        row = next((entry for entry in library_rows(folder)
                    if entry['id'] == identifier and entry['repository'] == repository), None)
        if row is None:
            raise ValueError("Ce mod n'est plus dans la bibliothèque sélectionnée.")
        package = root / 'packages' / row['sha256']
        no_links(package)
        if package.resolve().parent != (root / 'packages').resolve():
            raise ValueError("Dossier de paquet hors de la bibliothèque.")
        marker = package / '.hmb-prepared'
        no_links(marker)
        index = root / INDEX
        document = json.loads(index.read_text(encoding='utf-8'))
        del document['mods'][identifier]
        shared = any(entry.get('sha256') == row['sha256'] for entry in document['mods'].values())
        retained = shared or marker.exists() or (row['kind'] == 'native' and row.get('unprepared') is not True)
        if not retained:
            tree_files(package)  # Reject links before any recursive deletion.
        _write_json(index, document)
        if not retained:
            try:
                shutil.rmtree(package)
            except OSError:
                retained = True  # Entry removal succeeded; a locked package can remain safely.
        return retained


def _digest(stream, limit=MAX_ARCHIVE):
    checksum = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        size += len(block)
        if size > limit:
            raise ValueError("ZIP trop volumineux (limite : 256 Mio).")
        checksum.update(block)
    return checksum.hexdigest()
