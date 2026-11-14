"""Prepare a release separately and apply it to the single selected installation."""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import shutil
from pathlib import Path
import uuid

from manager_worker import Worker, emit
from modmanager.downloads import resolve_commit, download, extract_archive
from modmanager.models import Settings
from modmanager.paths import AppPaths
from modmanager.pipeline import read_manifest, write_json
from modmanager.updates import SOURCES, fetch_releases, version_key


def install(settings, tag, staging_only=False):
    source = SOURCES.get(settings.variant)
    if source is None or not tag.startswith(source.tag_prefix):
        raise ValueError("Aucune source de mise à jour correspondante")
    version = tag[len(source.tag_prefix):]
    if version_key(version) is None:
        raise ValueError("Version de release non reconnue")
    # Re-query the published release. Never trust a URL supplied by the UI/job file.
    matches = [r for r in fetch_releases(source) if r.get("tag_name") == tag and not r.get("draft")]
    if len(matches) != 1:
        raise ValueError("La release n'est plus disponible ou n'est pas unique")
    job = settings.variant + "-" + version + "-" + uuid.uuid4().hex[:8]
    store = AppPaths.current(settings.data_root).root / "cache/downloads" / job
    store.mkdir(parents=True)
    emit("progress", stage="download", label="Téléchargement des sources", percent=None, eta=None, detail=tag)
    commit = resolve_commit(source, tag)

    def progress(done, total):
        emit("progress", stage="download", label="Téléchargement des sources",
             percent=done * 100 / total if total else None, eta=None,
             detail="%.1f Mo reçus" % (done / 1048576))

    archive = store / "source.zip"
    checksum = download(source, commit, archive, progress)
    emit("progress", stage="audit", label="Validation de l’archive", percent=None, eta=None, detail=version)
    repo = extract_archive(archive, store / "sources")
    _, manifest = read_manifest(repo, settings.variant)
    if manifest["version"] != version:
        raise ValueError("La version du manifest ne correspond pas à la release")
    # Execute only the existing, trusted patch installer, in a minimal directory.
    # New installer scripts are never imported or executed; unsupported patch formats fail in the adapter.
    trusted = Path(settings.mods_repo)
    adapter_repo = store / "adapter"
    (adapter_repo / "patches").mkdir(parents=True)
    shutil.copytree(repo / "patches" / settings.variant, adapter_repo / "patches" / settings.variant)
    for name in ("install.py", "nup_reader.py"):
        shutil.copyfile(trusted / name, adapter_repo / name)
    repo = adapter_repo
    workspace = AppPaths.current(settings.data_root).workspaces(settings.engine) / ("release-" + job)
    game = Path(settings.game_dir)
    if not game.is_dir() or workspace.exists():
        raise ValueError("Choisissez votre installation existante ; seule la préparation doit être nouvelle")
    new = replace(settings, mods_repo=str(repo), workspace=str(workspace), game_dir=str(game))
    record = {"repository": source.repository, "tag": tag, "commit": commit, "archive_sha256": checksum,
              "version": version, "previous_settings": settings.to_dict(), "settings": new.to_dict(),
              "created_at": datetime.now(timezone.utc).isoformat(), "status": "downloaded"}
    write_json(store / "release.json", record)
    emit("log", text="Sources figées au commit %s ; SHA256 %s" % (commit, checksum))
    if staging_only:
        emit("complete", message="Archive téléchargée et validée. Aucune compilation ni modification du jeu.")
        return new
    worker = Worker(new)
    worker.validate()
    worker.prepare()
    report_path = workspace / "hmb-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["game_dir"] = str(game)
    write_json(report_path, report)
    write_json(workspace / "release-install.json", record)
    emit("release_project", settings=new.to_dict())
    # Worker handles active-profile snapshots under the installation lock.
    worker.execute()
    record["status"] = "installed"
    write_json(workspace / "release-install.json", record)
    write_json(store / "release.json", record)
    emit("installed", settings=worker.settings.to_dict(), previous=record["previous_settings"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--staging-only", action="store_true")
    args = parser.parse_args()
    try:
        install(Settings(**json.loads(args.settings.read_text(encoding="utf-8"))), args.tag, args.staging_only)
    except BaseException as error:
        import traceback
        emit("log", text=traceback.format_exc())
        emit("error", message=str(error) + " — l’installation précédente est conservée.")
        raise SystemExit(1)
