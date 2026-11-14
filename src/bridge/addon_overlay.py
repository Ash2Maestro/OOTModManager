"""Install one RomFS-only Addon without recompiling or touching the base RomFS."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def install_overlay(row, game_directory, *, engine_id="longshot"):
    from modmanager.deployment import JOURNAL, ensure_game_closed, validate_target
    from modmanager.pipeline import inventory, no_links, safe_relative, tree_files, workspace_lock, write_json

    game = validate_target(game_directory, engine_id)
    ensure_game_closed(engine_id)
    slug = safe_relative(row["id"])
    if len(slug.parts) != 1:
        raise ValueError("Identifiant d'Addon invalide.")
    name = "hmb-" + str(slug)
    manifest_path = Path(row["repository"]) / "patches" / slug / "manifest.json"
    no_links(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with workspace_lock(game):
        if (game / JOURNAL).exists():
            raise ValueError("Récupérez l'installation interrompue avant d'appliquer un Addon.")
        mods = game / "mods"
        no_links(mods)
        mods.mkdir(exist_ok=True)
        target = mods / name
        backup = mods / ("." + name + "-previous")
        journal = mods / ("." + name + "-transaction.json")
        for path in (target, backup, journal):
            no_links(path)
        # Recover only this manager-owned overlay after a killed worker.
        if journal.exists():
            if backup.exists() and not target.exists():
                backup.rename(target)
            elif backup.exists():
                shutil.rmtree(backup)
            journal.unlink()
        if backup.exists():
            raise ValueError("Une sauvegarde d'Addon non reconnue existe déjà : " + str(backup))
        if target.exists():
            receipt = target / ".hmb-addon.json"
            no_links(receipt)
            if not receipt.is_file():
                raise ValueError("Un dossier de mod non géré porte déjà ce nom : " + name)
            previous = json.loads(receipt.read_text(encoding="utf-8"))
            if inventory(target / "romfs") != previous.get("inventory"):
                raise ValueError("Cet Addon a été modifié hors du gestionnaire : " + name)
        wanted = set()
        for entry in manifest["files"]:
            relative = safe_relative(entry["path"])
            if relative.parts[0] != "romfs" or entry["kind"] != "raw":
                raise ValueError("Cet Addon n'est pas un paquet RomFS seul.")
            wanted.add(relative.relative_to("romfs").as_posix().casefold())
        for other in mods.iterdir():
            if other.name.startswith(".") or other == target or not other.is_dir():
                continue
            if not (other / "romfs").is_dir():
                continue
            conflicts = wanted.intersection(path.relative_to(other / "romfs").as_posix().casefold()
                                            for path in tree_files(other / "romfs"))
            if conflicts:
                raise ValueError("Conflit avec " + other.name + " : " + sorted(conflicts)[0])
        with tempfile.TemporaryDirectory(prefix="." + name + "-", dir=mods) as temporary:
            staged = Path(temporary) / "payload"
            staged.mkdir()
            for entry in manifest["files"]:
                source = manifest_path.parent / safe_relative(entry["patch"])
                no_links(source)
                output = staged / safe_relative(entry["path"])
                output.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with source.open("rb") as stream, output.open("xb") as destination:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                        destination.write(block)
                if digest.hexdigest() != entry["target_sha256"]:
                    raise ValueError("Le contenu de l'Addon a changé : " + entry["path"])
            write_json(staged / ".hmb-addon.json", dict(schema=1, sha256=row["sha256"],
                       inventory=inventory(staged / "romfs")))
            write_json(journal, dict(schema=1, addon=name))
            try:
                if target.exists():
                    target.rename(backup)
                staged.rename(target)
            except BaseException:
                if backup.exists() and not target.exists():
                    backup.rename(target)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            journal.unlink()
