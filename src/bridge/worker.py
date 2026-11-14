"""One JSON request per process; reuse the trusted engine without importing Tk.

stdout: newline-delimited ``HMBGUI {json}`` events, stderr: diagnostics.
The native UI owns cancellation of this process and all its descendants.
Importing this module performs no filesystem or game operation.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import traceback
import zipfile

from zip_library import import_archive, library_rows, pin_preparation, remove_entry
from configuration import build_inputs, game_directory


INTERNAL_SETTINGS = {"language", "button_prompts", "dlss", "dlss_license", "ngx_sdk", "preserve_runtime_settings", "data_root"}


def manager_settings(settings):
    return {key: value for key, value in settings.to_dict().items() if key not in INTERNAL_SETTINGS}


def event(kind, **values):
    payload = dict(type=kind, **values)
    try:
        from modmanager.i18n import event as localized_event
    except ImportError:
        pass  # Still report a missing engine before its imports are available.
    else:
        payload = localized_event(payload)
    print("HMBGUI " + json.dumps(payload, ensure_ascii=False), flush=True)


def snapshot(settings, core, data, with_assets=False):
    from dataclasses import asdict
    from modmanager.engines import get_engine
    backend = get_engine(settings.engine)
    from modmanager.deployment import active_profile
    from modmanager.removal import installed_mods
    from modmanager.updates import SOURCES
    catalog = {}
    warning = ""
    try:
        rows = library_rows(settings.mods_repo)
    except (OSError, ValueError) as error:
        rows, warning = [], str(error)
    for row in rows:
        manifest = json.loads((Path(row["repository"]) / "patches" / row["id"] / "manifest.json").read_text(encoding="utf-8"))
        presentation = row.get("presentation", {})
        name = presentation.get("name") or Path(row["archiveName"]).stem
        counts = {kind: sum(entry["path"].startswith(kind + "/") for entry in manifest["files"])
                  for kind in ("exefs", "romfs")}
        catalog[row["id"]] = dict(
            row, name=name, title=name,
            displayVersion=presentation.get("version") or "Version non renseignée",
            description=presentation.get("description", ""), author=presentation.get("author", ""),
            subtitle="Addon de code et de ressources" if counts["exefs"] and counts["romfs"]
                     else "Addon de code" if counts["exefs"] else "Addon de ressources",
            contentSummary="%d fichier(s) ExeFS · %d fichier(s) RomFS" % (counts["exefs"], counts["romfs"]),
            presentationSource="Informations fournies par l’Addon" if presentation.get("metadataProvided")
                               else "Nom issu de l’archive ; contenu détecté localement",
            canUpdate=False, origin="addon")
    ordered = sorted(catalog, key=lambda key: (catalog[key]["name"].casefold(), key))
    mods, active = [], None
    try:
        if settings.game_dir and Path(settings.game_dir).is_dir():
            mods = installed_mods(settings.game_dir)
            active = active_profile(settings.game_dir)
    except (OSError, ValueError, KeyError) as error:
        warning = str(error)
    kinds = {"native": "Pack de gameplay", "native-component": "Composant du pack", "overlay": "Ressources"}
    mods = [dict(mod, detail=" · ".join(filter(None, (kinds.get(mod["kind"], mod["kind"]), mod["version"])))) for mod in mods]
    for row in catalog.values():
        row["removalId"] = "overlay:hmb-" + row["id"] if row["kind"] == "romfs" else "native:" + row["id"]
        row["installed"] = row["kind"] == "romfs" and any(mod["id"] == row["removalId"] for mod in mods)
    result = dict(settings=manager_settings(settings), catalog=[catalog[key] for key in ordered], installed=mods,
                  active=active.get("variant", "vanilla") if active else "vanilla",
                  activeName=active.get("manifest", {}).get("name", "Jeu original") if active else "Jeu original",
                  activeVersion=active.get("manifest", {}).get("version", "") if active else "",
                  warning=warning,
                  engine=dict(id=backend.id, name=backend.name, capabilities=asdict(backend.capabilities)),
                  launchCommand=backend.launch_command(Path(settings.game_dir)) if settings.game_dir else [],
                  launchDirectory=settings.game_dir)
    if with_assets:
        # Catalog loading must never start extraction or compilation. The theme
        # belongs to the project/package and does not depend on the game paths.
        assets = Path(__file__).resolve().parents[2] / "assets"
        result["assets"] = str(assets) if (assets / "chronicle.json").is_file() else ""
    event("snapshot", **result)


def run(request, core, data):
    from modmanager.paths import AppPaths
    from modmanager.i18n import configure
    configure(request.get('settings', {}).get('ui_language', 'fr'), Path(__file__).resolve().parents[2] / 'i18n')
    from modmanager.models import Settings
    if request['action'] == 'resolve_source':
        from modmanager.engines import get_engine
        values = request['settings']
        engine = values.get('engine', 'longshot')
        game = values.get('game_dir', '')
        source = get_engine(engine).installation_source(Path(game)) if game.strip() else ''
        event('source_detected', game_dir=game, engine=engine, source=source,
              previous_source=values.get('source', ''))
        return
    from manager_worker import Worker
    from manage_mods import manage
    from modmanager.updates import SOURCES, select_release, fetch_releases
    settings = replace(Settings(**request["settings"]), preserve_runtime_settings=True, data_root=str(data),
                       dlss=False, dlss_license=False, ngx_sdk="")
    action = request["action"]
    if action == "import_zip":
        if not settings.mods_repo or not settings.mods_repo.strip():
            raise ValueError("Dossier de la bibliothèque non renseigné. Configurez-le dans Paramètres techniques.")
        archives = request.get("archives", [])
        if not isinstance(archives, list) or not 1 <= len(archives) <= 32 or not all(isinstance(path, str) for path in archives):
            raise ValueError("Importez entre 1 et 32 archives ZIP locales.")
        imported, errors = [], []
        for index, archive in enumerate(archives):
            event("progress", label="Import dans la bibliothèque", percent=index * 100 / len(archives), detail=Path(archive).name)
            try:
                from modmanager.pipeline import independent
                from zip_library import library_root
                independent(library_root(settings.mods_repo), [Path(value) for value in (settings.game_dir, settings.source) if value])
                imported.extend(import_archive(archive, settings.mods_repo))
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as error:
                errors.append(Path(archive).name + " : " + str(error))
        snapshot(settings, core, data)
        event("import_result", imported=list(dict.fromkeys(imported)), errors=errors)
        return
    if action == "snapshot":
        snapshot(settings, core, data, with_assets=True)
        return
    if action == "updates":
        slug = request["variant"]
        snapshot_version = request["version"]
        result = select_release(SOURCES[slug], snapshot_version, fetch_releases(SOURCES[slug]),
                                bool(request.get("includeBeta")))
        event("updates_result", variant=slug, result=result)
        return
    if action == 'library_remove':
        retained = remove_entry(settings.mods_repo, request['identifier'], request['repository'])
        snapshot(settings, core, data)
        message = "Mod supprimé de la bibliothèque. L'installation du jeu est conservée."
        if retained:
            message += " Le paquet interne reste conservé pour les préparations existantes ou par précaution."
        event('complete', message=message)
        return
    if action == "apply":
        from modmanager.engines import get_engine
        backend = get_engine(settings.engine)
        game_directory(settings)
        row = next((row for row in library_rows(settings.mods_repo)
                    if row["id"] == request["variant"] and row["repository"] == request.get("repository")), None)
        if row is None:
            raise ValueError("Cet Addon n'est pas dans la bibliothèque sélectionnée. Importez son ZIP.")
        if row["kind"] == "romfs":
            if not backend.capabilities.resource_overlays:
                raise ValueError("Ce moteur ne prend pas en charge les Addons de ressources.")
            from addon_overlay import install_overlay
            install_overlay(row, settings.game_dir, engine_id=settings.engine)
            event("complete", message="Addon de ressources installé sans compilation.")
        else:
            if not backend.capabilities.native_addons:
                raise ValueError("Ce moteur ne prend pas en charge les Addons de code.")
            from modmanager.pipeline import digest, read_manifest
            repository = Path(row["repository"])
            manifest_path, _ = read_manifest(repository, row["id"])
            identity = hashlib.sha256((settings.source + digest(manifest_path)).encode()).hexdigest()[:20]
            chosen = replace(settings, mods_repo=str(repository), variant=row["id"],
                             workspace=str(AppPaths(data).workspaces(backend.id) / (row["id"] + "-" + identity)))
            if request.get("preferWorkspace"):
                chosen = replace(chosen, workspace=settings.workspace)
            chosen = replace(chosen, clock=settings.clock if row["id"] == "item-wheel" else False)
            build_inputs(chosen)
            pin_preparation(settings.mods_repo, row)
            Worker(chosen, bool(request.get("force"))).execute()
            settings = replace(chosen, mods_repo=settings.mods_repo)
            event("installed", settings=manager_settings(settings))
    elif action in ("remove", "vanilla"):
        game_directory(settings)
        manage(settings, action, request.get("identifier"))
        # manage emits installed settings, which the UI commits only after exit 0.
        return
    elif action == "update_install":
        from install_release import install
        chosen = replace(settings, variant=request["variant"], mods_repo=request.get("repository", settings.mods_repo))
        install(chosen, request["tag"])
        return
    else:
        raise ValueError("Action inconnue : " + action)
    snapshot(settings, core, data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    args = parser.parse_args()
    core = args.core.resolve()
    if not (core / "manager_worker.py").is_file():
        raise ValueError("Moteur Longshot Mod Builder introuvable")
    sys.path.insert(0, str(core))
    request = json.loads(sys.stdin.read(1024 * 1024))
    if request.get("protocol", 1) != 1:
        raise ValueError("Version du protocole moteur non prise en charge")
    run(request, core, args.data.resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        event("log", text=traceback.format_exc())
        event("error", message=str(error))
        raise SystemExit(1)
