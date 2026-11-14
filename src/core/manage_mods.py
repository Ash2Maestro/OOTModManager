"""Explicit uninstall/vanilla actions. Never create another game installation."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import uuid

from manager_worker import Worker, emit
from modmanager.models import Settings, projects
from modmanager.paths import AppPaths
from modmanager.pipeline import REPORT, load_prepared, workspace_lock
from modmanager.deployment import validate_target, ensure_game_closed, JOURNAL
from modmanager.removal import installed_mods, remaining_native, uninstall_overlay


def settings_for_variant(settings, variant):
    base = AppPaths.current(settings.data_root).workspaces(settings.engine)
    if variant == "vanilla":
        for path, report in reversed(projects(base)):
            if report["variant"] == "vanilla" and report.get("engine", "longshot") == settings.engine and Path(report["source"]).resolve() == Path(settings.source).resolve():
                load_prepared(path)
                return replace(settings, variant="vanilla", workspace=str(path), clock=False)
        identity = hashlib.sha256(str(Path(settings.source).resolve()).encode()).hexdigest()[:12]
        workspace = base / ("vanilla-" + identity)
        if workspace.exists() and any(workspace.iterdir()) and not (workspace / REPORT).is_file():
            workspace = workspace.with_name(workspace.name + "-" + uuid.uuid4().hex[:8])
        return replace(settings, variant="vanilla", workspace=str(workspace), clock=False)
    for path, report in reversed(projects(base)):
        if report["variant"] == variant and report.get("engine", "longshot") == settings.engine and Path(report["source"]).resolve() == Path(settings.source).resolve():
            load_prepared(path)
            return replace(settings, variant=variant, workspace=str(path), mods_repo=report["mods_repository"],
                           clock=bool(report.get("native_adapters")))
    workspace = base / (variant + "-" + uuid.uuid4().hex[:8])
    return replace(settings, variant=variant, workspace=str(workspace), clock=variant == "item-wheel")


def manage(settings, action, identifier=None):
    game = validate_target(settings.game_dir, settings.engine)
    ensure_game_closed(settings.engine)
    if action == "remove" and identifier and identifier.startswith("overlay:"):
        with workspace_lock(game):
            if (game / JOURNAL).exists():
                raise ValueError("Terminez la récupération de l'application avant de désinstaller")
            uninstall_overlay(game, identifier)
        emit("mods_changed")
        emit("complete", message="Mod de ressources désinstallé. Les autres mods et le programme sont conservés ; aucune compilation.")
        return
    if action == "vanilla":
        variant = "vanilla"
    elif action == "remove" and identifier and identifier.startswith("native:"):
        active = next((m for m in installed_mods(game) if m["kind"] == "native"), None)
        if active is None:
            raise ValueError("Aucun mod natif n'est installé dans ce jeu")
        variant = remaining_native(active["variant"], identifier[len("native:"):])
    else:
        raise ValueError("Action de désinstallation inconnue")
    new = settings_for_variant(settings, variant)
    emit("release_project", settings=new.to_dict())
    Worker(new, restore_all=action == "vanilla").execute()
    emit("installed", settings=new.to_dict(), previous=settings.to_dict())
    emit("mods_changed")
    emit("complete", message=("Jeu vanilla restauré. Tous les overlays ont été désactivés et archivés ; sauvegardes conservées." if action == "vanilla"
                              else "Mod natif désinstallé. Les autres overlays restent actifs."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--action", choices=("vanilla", "remove"), required=True)
    parser.add_argument("--mod")
    args = parser.parse_args()
    try:
        manage(Settings(**json.loads(args.settings.read_text(encoding="utf-8"))), args.action, args.mod)
    except BaseException as error:
        import traceback
        emit("log", text=traceback.format_exc())
        emit("error", message=str(error))
        raise SystemExit(1)
