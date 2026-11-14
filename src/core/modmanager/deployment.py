"""Replace managed files in ONE existing game. Never copy its RomFS or saves."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil

from .pipeline import REPORT, inventory, no_links, safe_relative, tree_files, write_json
from .engines import get_engine, engine_for_report

JOURNAL = ".hmb-deployment.json"
STAGE = ".hmb-deployment"
MANAGER_FILES = (".hmb-owner.json", ".hmb-active.json")


def ensure_game_closed(engine_id="longshot"):
    """Shared precondition for installation and removal operations."""
    get_engine(engine_id).ensure_game_closed()


def active_profile(game):
    game = Path(game)
    owner_path = game / ".hmb-owner.json"
    if not owner_path.is_file():
        return None
    no_links(owner_path)
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    project = Path(owner["workspace"])
    no_links(project)
    report = project / REPORT
    if report.is_file():
        return json.loads(report.read_text(encoding="utf-8"))
    stored = game / ".hmb-active.json"
    no_links(stored)
    data = json.loads(stored.read_text(encoding="utf-8"))
    if data.get("workspace") != owner["workspace"]:
        raise ValueError("État du profil actif incohérent")
    return data


def validate_target(game, engine_id="longshot"):
    backend = get_engine(engine_id)
    game = Path(game).resolve()
    no_links(game)
    if not game.is_dir() or not (game / "romfs").is_dir():
        raise ValueError("Choisissez une installation du jeu existante (avec son dossier romfs). Aucune nouvelle copie du jeu ne sera créée.")
    no_links(game / "romfs")
    if not (game / JOURNAL).exists() and not (game / backend.layout.image).is_file():
        raise ValueError("Cette installation ne contient pas l'image native attendue.")
    return game


def _managed_files(layout):
    return (*MANAGER_FILES, *layout.extra_files, layout.image, layout.version,
            *(name for name in layout.executables if "/" not in name))


def _allowed(name, engine_id="longshot"):
    layout = get_engine(engine_id).layout
    p = safe_relative(name)
    return (name == "mods" or name in _managed_files(layout) or name in layout.native_roots or name in layout.preferences or (len(p.parts) == 1 and name.endswith(".dll")) or
            (len(p.parts) == 2 and p.parts[0] == "mods" and p.parts[1].startswith("00-OOT-")))


def recover_deployment(game):
    game = Path(game).resolve()
    journal = game / JOURNAL
    if not journal.exists():
        return
    no_links(journal)
    data = json.loads(journal.read_text(encoding="utf-8"))
    stage = game / STAGE
    no_links(stage)
    if data.get("schema") != 1 or any(not _allowed(n, data.get("engine", "longshot")) for n in data["items"]):
        raise ValueError("Journal de remplacement invalide")
    for name in data["items"]:
        source, target = stage / "previous" / safe_relative(name), game / safe_relative(name)
        if name == "mods" and not source.exists() and data.get("disabled_archive"):
            archive = game / safe_relative(data["disabled_archive"])
            if archive.parent != game / ".hmb-disabled-mods":
                raise ValueError("Archive de mods invalide")
            no_links(archive)
            if archive.exists():
                source = archive
        no_links(source)
        no_links(target)
        if source.exists():
            if target.exists():
                displaced = stage / "failed" / safe_relative(name)
                if displaced.exists():
                    raise ValueError("Récupération ambiguë : fichiers temporaires déjà présents")
                displaced.parent.mkdir(parents=True, exist_ok=True)
                target.rename(displaced)
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        elif name not in data["existed"] and target.exists():
            displaced = stage / "failed" / safe_relative(name)
            displaced.parent.mkdir(parents=True, exist_ok=True)
            target.rename(displaced)
    project = Path(data["workspace"])
    no_links(project)
    (project / REPORT).write_text(data["report_before"], encoding="utf-8")
    journal.unlink()
    _discard_stage(game)


def _discard_stage(game):
    stage = Path(game) / STAGE
    no_links(stage)
    if stage.exists():
        # Fixed, verified child directory. It contains only files staged by this transaction.
        tree_files(stage)
        shutil.rmtree(stage)


@contextmanager
def replace_installation(workspace, report, game, disable_all_mods=False):
    backend = engine_for_report(report)
    layout = backend.layout
    workspace, game = Path(workspace).resolve(), validate_target(game, backend.id)
    recover_deployment(game)
    _discard_stage(game)
    owner_path = game / ".hmb-owner.json"
    try:
        old = active_profile(game)
    except (OSError, ValueError, KeyError):
        if not disable_all_mods:
            raise
        old = None
    overlay = None
    if old is not None:
        overlay = "mods/00-OOT-" + old["variant"]
        if not _allowed(overlay, backend.id):
            raise ValueError("Ancien overlay invalide")
        if not disable_all_mods and (game / overlay).exists() and inventory(game / overlay) != old.get("installed_overlay", {}):
            raise ValueError("L'ancien overlay a été modifié hors du gestionnaire")
    wanted_overlay = "mods/00-OOT-" + report["variant"]
    if not _allowed(wanted_overlay, backend.id):
        raise ValueError("Nouvel overlay invalide")
    if not disable_all_mods and (game / wanted_overlay).exists() and wanted_overlay != overlay:
        raise ValueError("Un overlay non géré occupe le nom du mod sélectionné")
    overlay_items = ["mods"] if disable_all_mods else [*([overlay] if overlay else []), wanted_overlay]
    # Source builds keep libraries beside the executable. Stage both old and
    # incoming names so rollback also removes a newly introduced library.
    dlls = [p.name for p in game.glob("*.dll")]
    dlls.extend(p.name for p in Path(report["tools_path"]).glob("*.dll"))
    preserved = (*layout.preferences, *dlls) if report.get("preserve_runtime_settings") else ()
    if preserved:
        preserved += tuple(path.relative_to(game).as_posix() for folder in layout.library_roots
                           for path in tree_files(game / folder)
                           if path.relative_to(game).as_posix() not in layout.executables)
    preserved = tuple(dict.fromkeys(preserved))
    additions = [name for name in preserved if '/' not in name]
    items = list(dict.fromkeys([*layout.native_roots, *_managed_files(layout), *dlls, *overlay_items, *additions]))
    for name in items:
        no_links(game / safe_relative(name))
    stage = game / STAGE
    stage.mkdir()
    record = {"schema": 1, "engine": backend.id, "workspace": str(workspace), "items": items,
              "existed": [n for n in items if (game / n).exists()],
              "report_before": (workspace / REPORT).read_text(encoding="utf-8")}
    write_json(game / JOURNAL, record)
    try:
        for name in record["existed"]:
            dest = stage / "previous" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            (game / name).rename(dest)
        write_json(owner_path, {"workspace": str(workspace)})
        report["game_dir"] = str(game)
        report["romfs"] = str(game / "romfs")
        report["installed_overlay"] = {}
        report.update(backend.staged_runtime(report, stage / "previous"))
        write_json(workspace / REPORT, report)
        yield
        # Compiler/cache outputs may contain defaults or another machine's
        # optional runtime. Restore the selected installation byte-for-byte.
        for name in preserved:
            current, previous = game / name, stage / "previous" / name
            if current.exists():
                generated = stage / "generated" / name
                generated.parent.mkdir(parents=True, exist_ok=True)
                current.rename(generated)
            if previous.exists():
                current.parent.mkdir(parents=True, exist_ok=True)
                if any(name.startswith(folder + "/") for folder in layout.native_roots):
                    # Keep the staged bin tree complete until commit: rollback
                    # restores that whole tree after a crash during preservation.
                    if previous.is_dir():
                        shutil.copytree(previous, current)
                    else:
                        shutil.copy2(previous, current)
                else:
                    previous.rename(current)
        if disable_all_mods and (stage / "previous/mods").exists():
            import uuid
            archive = game / ".hmb-disabled-mods" / uuid.uuid4().hex
            archive.parent.mkdir(exist_ok=True)
            record["disabled_archive"] = archive.relative_to(game).as_posix()
            write_json(game / JOURNAL, record)
            (stage / "previous/mods").rename(archive)
        (game / JOURNAL).unlink()
        _discard_stage(game)
    except BaseException:
        recover_deployment(game)
        raise
