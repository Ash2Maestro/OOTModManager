"""Verified native build reuse and transactional, manager-owned RomFS overlays."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from .engines import get_engine, engine_for_report

from .build_cache import store_build, read_build, copy_file, touch, DEFAULT_LIMIT

from .pipeline import (REPORT, digest, inventory, no_links, safe_relative, tree_files,
                       write_json, independent, workspace_lock)


def native_key(workspace, report, tools_signature, language):
    # Full guest bytes (including data) and compiler sources/options.
    # Language and controller icons are runtime preferences, not native inputs.
    # Version/name/manifest and RomFS changes do not change compiled native code.
    backend = engine_for_report(report)
    payload = {"schema": 3, "engine": backend.id, "exefs": inventory(Path(workspace) / "prepared/exefs"),
               "tools": tools_signature}
    options = backend.native_cache_options(report)
    if options:
        # Keep the historical key spelling so existing Longshot snapshots remain reusable.
        payload.update(schema=4, graphics=options)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def native_files(game, engine_id="longshot"):
    game = Path(game)
    layout = get_engine(engine_id).layout
    result = {}
    for name in (*layout.executables, layout.image, layout.version, *layout.extra_files):
        path = game / name
        no_links(path)
        if path.is_file():
            result[name] = path
    for folder in (name for name in layout.native_roots if name != layout.stored_exefs):
        for path in tree_files(game / folder):
            result[path.relative_to(game).as_posix()] = path
    # Development builds put shared libraries beside the executable.
    for path in game.glob("*.dll"):
        no_links(path)
        result[path.name] = path
    if layout.image not in result or not any(name in result for name in layout.executables):
        raise ValueError("Build natif incomplet")
    return result


def cache_build(cache, key, game, limit=DEFAULT_LIMIT, *, engine_id="longshot"):
    return store_build(cache, key, native_files(game, engine_id), limit, engine_id=engine_id)


def validate_cache(cache, key):
    with workspace_lock(Path(cache)):
        return read_build(cache, key)


def overlay_path(game, report):
    variant = report["variant"]
    if not variant or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in variant):
        raise ValueError("Variante invalide")
    return Path(game) / "mods" / ("00-OOT-" + variant)


def resources_match(workspace, report, game):
    if report["variant"] == "vanilla":
        return not overlay_path(game, report).exists()
    wanted = inventory(Path(workspace) / "addon/romfs")
    current = overlay_path(game, report) / "romfs"
    return current.is_dir() and inventory(current) == wanted


def apply_resources(workspace, report, game):
    """Swap only the owned mod overlay; keep a recoverable previous tree."""
    if report["variant"] == "vanilla":
        return
    with workspace_lock(Path(workspace)):
        return _apply_resources(workspace, report, game)


def _apply_resources(workspace, report, game):
    workspace, game = Path(workspace), Path(game)
    no_links(game)
    owner = json.loads((game / ".hmb-owner.json").read_text(encoding="utf-8"))
    if owner != {"workspace": str(workspace.resolve())}:
        raise ValueError("Cette installation n'appartient pas au projet sélectionné")
    overlay = overlay_path(game, report)
    no_links(overlay)
    recovery = game / ".hmb-overlay-transaction.json"
    if recovery.exists():
        recover_resources(game)
    expected = report.get("installed_overlay", {})
    if overlay.exists() and inventory(overlay) != expected:
        raise ValueError("Les ressources installées ont été modifiées hors du gestionnaire")
    transaction = uuid.uuid4().hex
    staged = game / "mods" / (".hmb-new-" + transaction)
    backup = game / ".hmb-overlay-backups" / transaction
    backup.parent.mkdir(parents=True, exist_ok=True)
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(workspace / "addon/romfs", staged / "romfs")
    had_overlay = overlay.exists()
    record = {"overlay": overlay.relative_to(game).as_posix(), "staged": staged.relative_to(game).as_posix(),
              "backup": backup.relative_to(game).as_posix(), "had_overlay": had_overlay,
              "workspace": str(workspace.resolve()), "old_report": (workspace / REPORT).read_text(encoding="utf-8")}
    write_json(recovery, record)
    try:
        if had_overlay:
            overlay.rename(backup)
        staged.rename(overlay)
        report["installed_overlay"] = inventory(overlay)
        write_json(workspace / REPORT, report)
        recovery.unlink()
    except BaseException:
        recover_resources(game)
        raise


def recover_resources(game):
    """Roll back an interrupted overlay swap before the game can be launched."""
    game = Path(game)
    path = game / ".hmb-overlay-transaction.json"
    if not path.exists():
        return
    no_links(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    overlay, staged, backup = [game / safe_relative(data[k]) for k in ("overlay", "staged", "backup")]
    # The journal may name only our reserved overlay/temporary/backup locations.
    if (overlay.parent != game / "mods" or not overlay.name.startswith("00-OOT-") or
            staged.parent != game / "mods" or not staged.name.startswith(".hmb-new-") or
            backup.parent != game / ".hmb-overlay-backups"):
        raise ValueError("Journal de ressources invalide")
    for item in (overlay, staged, backup):
        no_links(item)
    owner = json.loads((game / ".hmb-owner.json").read_text(encoding="utf-8"))
    if owner != {"workspace": data["workspace"]}:
        raise ValueError("Propriétaire du journal incorrect")
    workspace = Path(data["workspace"])
    no_links(workspace)
    if backup.exists():
        if overlay.exists():
            if staged.exists():
                raise ValueError("Transaction ambiguë ; récupération manuelle nécessaire")
            overlay.rename(staged)
        backup.rename(overlay)
    elif not data["had_overlay"] and overlay.exists():
        overlay.rename(staged)
    (workspace / REPORT).write_text(data["old_report"], encoding="utf-8")
    path.unlink()


def restore_build(cache, key, workspace, report, game):
    with workspace_lock(Path(cache)):
        result = _restore_build(cache, key, workspace, report, game)
        touch(cache, key, result)
        return result


def _restore_build(cache, key, workspace, report, game):
    """Restore native files; an existing target requires an active replacement transaction."""
    target, data = read_build(cache, key)
    if data.get("engine", "longshot") != engine_for_report(report).id:
        raise ValueError("Le cache appartient à un autre moteur.")
    workspace, game = Path(workspace).resolve(), Path(game).resolve()
    no_links(game)
    in_place = game.exists() and (game / ".hmb-deployment.json").is_file()
    protected_project = [workspace / "prepared", workspace / "addon", Path(report.get("build_work", workspace / "build-work"))] if in_place else [workspace]
    independent(game, [*protected_project, *([] if in_place else [Path(report["romfs"])]), Path(report["source"]), Path(cache)])
    if game.exists() and not in_place:
        raise ValueError("La restauration attend une destination nouvelle")
    game.mkdir(parents=True, exist_ok=True)
    write_json(game / ".hmb-owner.json", {"workspace": str(workspace)})
    for name in data["files"]:
        dest = game / safe_relative(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_file(cache, target, data, name, dest)

    def link_or_copy(source, destination):
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
        return destination

    if not in_place:
        no_links(Path(report["romfs"]))
        tree_files(Path(report["romfs"]))
        shutil.copytree(report["romfs"], game / "romfs", copy_function=link_or_copy)
    # Keep the input modules for upstream tools, without recompiling anything.
    shutil.copytree(workspace / "prepared/exefs", game / engine_for_report(report).layout.stored_exefs)
    report["game_dir"] = str(game)
    report["build_status"] = "built-reused-unverified-in-game"
    write_json(workspace / REPORT, report)
    apply_resources(workspace, report, game)
    return data
