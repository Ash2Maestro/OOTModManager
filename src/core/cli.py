#!/usr/bin/env python3
"""Prepare les mods rexcraft88 avant recompilation par Longshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from modmanager import __version__
from modmanager.formats import Nso, parse_ips
from modmanager.pipeline import (PREPARE_DEPS, DEFAULT_TOOLS, DEFAULT_MODS, build,
                          check_tools, load_prepared, missing_dependencies, prepare, read_manifest,
                          require_build_python)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version="Longshot Mod Builder " + __version__)
    commands = p.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Lister et inspecter les variantes sans fichiers du jeu")
    listing.add_argument("--mods-repo", type=Path, default=DEFAULT_MODS)
    listing.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="Verifier Python, les depots et les dependances")
    doctor.add_argument("--tools", dest="tools_path", type=Path, default=DEFAULT_TOOLS)
    doctor.add_argument("--engine", default="longshot")
    doctor.add_argument("--mods-repo", type=Path, default=DEFAULT_MODS)
    doctor.add_argument("--python", "--build-python", dest="build_python", type=Path,
                        help="Python du Builder a verifier pour la compilation")
    preparation = commands.add_parser("prepare", help="Reconstruire et preparer une variante dans un dossier vide")
    preparation.add_argument("--source", type=Path, required=True, help="NUP original ou dossier exefs/romfs original")
    preparation.add_argument("--variant", required=True, help="Une seule variante, voir list")
    preparation.add_argument("--workspace", type=Path, required=True, help="Dossier de travail vide separe du jeu et des depots")
    preparation.add_argument("--tools", dest="tools_path", type=Path, default=DEFAULT_TOOLS)
    preparation.add_argument("--engine", default="longshot")
    preparation.add_argument("--mods-repo", type=Path, default=DEFAULT_MODS)
    preparation.add_argument("--romfs", dest="romfs_override", type=Path,
                             help="Avec un NUP : reutiliser un RomFS deja extrait, en lecture seule")
    compilation = commands.add_parser("build", help="Recompiler une preparation avec Longshot")
    compilation.add_argument("--workspace", type=Path, required=True)
    compilation.add_argument("--jobs", type=int, default=2)
    compilation.add_argument("--language", help="Code de langue Longshot, par exemple fr-FR")
    compilation.add_argument("--python", "--build-python", dest="build_python", type=Path,
                             help="Python de compilation, par exemple celui du Builder installe")
    compilation.add_argument("--game-dir", type=Path, help="Nouvelle installation du jeu ; defaut workspace/game")
    compilation.add_argument("--object-cache", type=Path, help="Cache objcache Longshot existant a reutiliser")
    compilation.add_argument("--plan", action="store_true", help="Afficher la commande sans lancer la compilation")
    verify = commands.add_parser("verify", help="Verifier les empreintes d'une preparation")
    verify.add_argument("--workspace", type=Path, required=True)
    return p


def list_variants(repo: Path) -> list[dict]:
    found = []
    for path in sorted((repo / "patches").glob("*/manifest.json")):
        _, manifest = read_manifest(repo, path.parent.name)
        native, ips, resources = [], [], 0
        for entry in manifest["files"]:
            if entry["path"].startswith("romfs/"):
                resources += 1
            else:
                native.append(entry["path"])
            if entry["path"].endswith(".ips"):
                records = parse_ips((path.parent / entry["patch"]).read_bytes())
                ips.extend({"offset": r.offset, "size": len(r.data)} for r in records)
            if entry["path"] == "exefs/subsdk1" and entry["kind"] == "raw":
                module = Nso((path.parent / entry["patch"]).read_bytes())
                if module.mapped_size != 0x80000:
                    raise ValueError("La taille de subsdk1 a change ; profil a reexaminer")
        found.append({"variant": path.parent.name, "name": manifest["name"], "version": manifest["version"],
                      "native_files": native, "romfs_files": resources, "ips_records": ips,
                      "status": "experimental-unverified-in-game"})
    if not found:
        raise ValueError("Aucun manifest trouve dans %s" % repo)
    return found


def doctor(longshot: Path, repo: Path, build_python: Path | None = None, engine_id="longshot") -> int:
    print("Python : %s (%s)" % (sys.version.split()[0], sys.executable))
    okay = True
    try:
        check_tools(longshot.resolve(), engine_id)
        print("Longshot : structure et layout reconnus")
    except (ValueError, OSError) as error:
        print("Longshot : %s" % error)
        okay = False
    try:
        variants = list_variants(repo.resolve())
        print("Mods : %d manifests et payloads inspectes" % len(variants))
    except (ValueError, OSError) as error:
        print("Mods : %s" % error)
        okay = False
    missing = missing_dependencies(PREPARE_DEPS)
    print("Preparation, dependances absentes : " + (", ".join(missing) if missing else "aucune"))
    if missing:
        okay = False
        print(subprocess.list2cmdline([sys.executable, "-m", "pip", "install", "-r", str(repo.resolve() / "requirements.txt")]))
    executable = str((build_python or Path(sys.executable)).resolve())
    print("Python de compilation : " + executable)
    try:
        require_build_python(executable)
        print("Compilation, dependances Python controlees : OK")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        okay = False
        print("Compilation : %s" % error)
        print(subprocess.list2cmdline([executable, "-m", "pip", "install", "-r", str(longshot.resolve() / "requirements.txt")]))
    print("Le compilateur, les bibliotheques natives et le GPU seront controles par Longshot au build.")
    print("Statut gameplay : aucune variante encore qualifiee dans Longshot par cet outil.")
    return 0 if okay else 1


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "list":
            variants = list_variants(args.mods_repo.resolve())
            if args.json:
                print(json.dumps(variants, indent=2, ensure_ascii=False))
            else:
                for item in variants:
                    print("%s  %s  (%d ressources RomFS, %d records IPS)" %
                          (item["variant"], item["version"], item["romfs_files"], len(item["ips_records"])))
                print("Toutes les variantes sont experimentales pour Longshot. Choisissez-en une seule.")
        elif args.command == "doctor":
            return doctor(args.tools_path, args.mods_repo, args.build_python, args.engine)
        elif args.command == "prepare":
            prepare(args.source, args.workspace, args.tools_path, args.mods_repo, args.variant, args.romfs_override, engine_id=args.engine)
        elif args.command == "build":
            build(args.workspace, jobs=args.jobs, language=args.language, plan=args.plan,
                  build_python=args.build_python, game_dir=args.game_dir, object_cache=args.object_cache)
        elif args.command == "verify":
            report = load_prepared(args.workspace.resolve())
            print("Empreintes verifiees : %s %s ; compilation : %s ; gameplay : %s" %
                  (report["manifest"]["name"], report["manifest"]["version"], report["build_status"], report["gameplay_validation"]))
        return 0
    except KeyboardInterrupt:
        print("\nOperation interrompue. Les fichiers partiels sont conserves pour diagnostic.", file=sys.stderr)
        return 130
    except (ValueError, TypeError, OSError, ImportError, subprocess.CalledProcessError) as error:
        print("Erreur : %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
