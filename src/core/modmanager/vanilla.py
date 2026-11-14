"""Prepare the unmodified guest program, without extracting/copying its RomFS."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from . import __version__
from .formats import MODULES, Nso, module_layout
from .pipeline import (REPORT, check_tools, check_source, extract_original_nup, digest,
                       inventory, load_prepared, no_links, independent, write_json)

ORIGINAL_MAIN_SHA256 = "7db9ddfda088c22d219ef13496decd7077c68cd67d4b37f53f4ac46a082768f2"


def prepare_vanilla(source, workspace, tools, romfs, *, engine_id="longshot"):
    source, workspace, tools, romfs = map(lambda p: Path(p).resolve(), (source, workspace, tools, romfs))
    for path in (source, workspace, tools, romfs):
        no_links(path)
    independent(workspace, [source, tools, romfs])
    if (workspace / REPORT).is_file():
        report = load_prepared(workspace)
        if report["variant"] != "vanilla" or Path(report["source"]).resolve() != source or report.get("engine", "longshot") != engine_id:
            raise ValueError("La préparation vanilla appartient à une autre source")
        return report
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Préparation vanilla incomplète : choisir une nouvelle préparation")
    check_tools(tools, engine_id)
    workspace.mkdir(parents=True, exist_ok=True)
    original = source
    if source.is_file():
        original = workspace / "original"
        extract_original_nup(source, original, tools, only_exefs=True, engine_id=engine_id)
    check_source(original, romfs)
    if digest(original / "exefs/main") != ORIGINAL_MAIN_SHA256:
        raise ValueError("Le programme source n'est pas l'original attendu ; restauration vanilla refusée")
    exefs = workspace / "prepared/exefs"
    exefs.mkdir(parents=True)
    modules = {}
    for name in MODULES:
        path = original / "exefs" / name
        if path.is_file():
            module = Nso(path.read_bytes())
            (exefs / name).write_bytes(module.encode())
            modules[name] = module
    shutil.copyfile(original / "exefs/main.npdm", exefs / "main.npdm")
    (workspace / "addon/romfs").mkdir(parents=True)
    contents = inventory(exefs)
    report = {"schema": 1, "tool_version": __version__, "status": "prepared", "workspace": str(workspace),
              "created_utc": datetime.now(timezone.utc).isoformat(), "variant": "vanilla",
              "manifest": {"name": "Jeu vanilla", "version": "original", "files": []},
              "manifest_sha256": hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest(),
              "source": str(source), "romfs": str(romfs), "external_romfs": True,
              "tools_path": str(tools), "engine": engine_id, "mods_repository": "", "build_status": "not-built",
              "gameplay_validation": "not-tested", "inventory": {"prepared": inventory(workspace / "prepared"), "addon": {}},
              "audit": {"layout": module_layout(modules), "ips": [], "changed_direct_branches": [], "changed_code_ranges": {}}}
    write_json(workspace / REPORT, report)
    return report
