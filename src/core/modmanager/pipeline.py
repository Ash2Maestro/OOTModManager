"""Isolated preparation/build orchestration; upstream checkouts remain unchanged."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from . import __version__
from .storage import digest, write_json, is_link, no_links, safe_relative, tree_files, independent, load_module, inventory
from .state import REPORT, normalize_report, load_prepared
from .formats import MODULES, FormatError, Nso, audit_changed_branches, changed_ranges, module_layout, parse_ips
from .engines import BuildRequest, get_engine, engine_for_report
from .game import BUILD_ID, TITLE_ID, UPDATE
from .paths import AppPaths

tools_candidates = get_engine().discover_tools


DEFAULT_TOOLS = next(iter(tools_candidates()), AppPaths.current().root / "tools-unconfigured")
DEFAULT_MODS = AppPaths.current().library
PREPARE_DEPS = ("bsdiff4", "zstandard", "lz4.block", "zbic")
BUILD_DEPS = get_engine().build_dependencies


def log(message: str):
    print(message, flush=True)




def process_alive(pid: int) -> bool | None:
    """False only when absence is certain; access denied never means stale."""
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            code = wintypes.DWORD()
            return code.value == 259 if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) else None
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return None


def _file_lock(descriptor, release=False):
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt
        # Windows permits byte locks beyond EOF, including a newly created file.
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(descriptor, fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def workspace_lock(workspace: Path):
    """Kernel-owned lock: automatically released even when the worker is killed.

    The inode/file is kept to avoid an unlock/unlink race with another build.
    Old PID-only locks are migrated only after proving their owner has exited.
    """
    path = workspace / ".hmb-build.lock"
    no_links(path)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
    acquired, claimed = False, False
    try:
        try:
            _file_lock(descriptor)
            acquired = True
        except OSError as error:
            raise ValueError("Une compilation utilise déjà ce dossier : %s" % workspace) from error
        previous = os.read(descriptor, 256).decode("ascii", errors="replace").strip()
        if previous.startswith("pid="):
            try:
                pid = int(previous[4:])
            except ValueError:
                raise ValueError("Ancien verrou illisible, propriétaire à vérifier : %s" % path)
            if process_alive(pid) is not False:
                raise ValueError("Une compilation précédente utilise peut-être ce dossier (PID %d) : %s" % (pid, workspace))
            log("Ancien verrou libéré : le processus %d n'existe plus. Cache conservé." % pid)
        elif previous and not previous.startswith("hmb-lock-v2\n"):
            raise ValueError("Format de verrou inconnu : %s" % path)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, ("hmb-lock-v2\npid=%d\n" % os.getpid()).encode())
        claimed = True
        yield
    finally:
        if acquired:
            try:
                if claimed:
                    os.ftruncate(descriptor, 0)
                _file_lock(descriptor, release=True)
            finally:
                os.close(descriptor)
        else:
            os.close(descriptor)








def missing_dependencies(names=PREPARE_DEPS) -> list[str]:
    missing = []
    for name in names:
        try:
            found = importlib.util.find_spec(name)
        except (ModuleNotFoundError, ValueError):
            found = None
        if found is None:
            missing.append(name)
    return missing


def require_dependencies(names=PREPARE_DEPS):
    missing = missing_dependencies(names)
    if missing:
        raise ValueError("Dependances Python absentes : %s. Voir la commande doctor et le README." % ", ".join(missing))


def require_build_python(executable: str, dependencies=BUILD_DEPS):
    if Path(executable).resolve() == Path(sys.executable).resolve():
        require_dependencies(dependencies)
        return
    probe = "import importlib.util,json\nnames = " + repr(list(dependencies)) + "\n" + """
missing = []
for name in names:
    try:
        found = importlib.util.find_spec(name)
    except (ModuleNotFoundError, ValueError):
        found = None
    if found is None:
        missing.append(name)
print(json.dumps(missing))
"""
    result = subprocess.run([executable, "-B", "-c", probe], capture_output=True, text=True, check=True)
    missing = json.loads(result.stdout)
    if missing:
        raise ValueError("Dependances absentes dans le Python de compilation : " + ", ".join(missing))


def check_tools(root: Path, engine_id="longshot"):
    get_engine(engine_id).validate_tools(root)


def reusable_preparation(workspace, source):
    """A verified preparation can rebuild without reopening a removed dump."""
    if not workspace or not source:
        return False
    try:
        report = load_prepared(Path(workspace))
        return (Path(report["source"]).resolve() == Path(source).resolve()
                and Path(report["romfs"]).is_dir())
    except (OSError, ValueError, KeyError):
        return False


def read_manifest(repo: Path, variant: str) -> tuple[Path, dict]:
    if not re.fullmatch(r"[a-z0-9-]+", variant):
        raise ValueError("Nom de variante invalide")
    path = repo / "patches" / variant / "manifest.json"
    no_links(path)
    m = json.loads(path.read_text(encoding="utf-8"))
    if (m.get("title_id", "").lower() != TITLE_ID.lower() or m.get("update_version") != UPDATE
            or m.get("build_id", "").lower() != BUILD_ID):
        raise ValueError("Le manifest ne cible pas le build pris en charge")
    seen = set()
    for entry in m["files"]:
        relative = safe_relative(entry["path"])
        key = relative.as_posix().casefold()
        if key in seen or relative.parts[0] not in ("exefs", "romfs"):
            raise ValueError("Chemin duplique ou hors exefs/romfs : %s" % relative)
        seen.add(key)
        if entry["kind"] not in ("raw", "nso", "binary", "zstd", "zstd-blocks"):
            raise ValueError("Type de patch inconnu : %s" % entry["kind"])
        patch = path.parent / safe_relative(entry["patch"])
        no_links(patch)
        if not patch.is_file():
            raise ValueError("Patch absent : %s" % patch)
        for field in ("source_sha256", "target_sha256"):
            if field in entry and not re.fullmatch(r"[a-fA-F0-9]{64}", entry[field]):
                raise ValueError("Empreinte invalide dans le manifest")
    if "exefs/main" not in seen or "exefs/subsdk1" not in seen:
        raise ValueError("Cette premiere version attend main + subsdk1")
    return path, m


def run(command: list[str], cwd: Path, *, logfile: Path | None = None, environment=None, engine_id="longshot"):
    log("Execution : " + subprocess.list2cmdline(command))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    for name in get_engine(engine_id).isolated_build_variables:
        env.pop(name, None)
    env.update(environment or {})
    if logfile is None:
        subprocess.run(command, cwd=cwd, env=env, check=True)
        return
    with logfile.open("a", encoding="utf-8") as output:
        with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as process:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    print(line, end="", flush=True)
                    output.write(line)
                    output.flush()
                code = process.wait()
            except BaseException:
                process.terminate()
                process.wait()
                raise
            if code:
                raise subprocess.CalledProcessError(code, command)


def extract_original_nup(source: Path, destination: Path, tools: Path, *, only_exefs=False, engine_id="longshot"):
    get_engine(engine_id).extract_source(source, destination, tools, only_exefs=only_exefs)


def check_source(source: Path, romfs_override: Path | None = None):
    no_links(source)
    romfs = romfs_override or source / "romfs"
    if not (source / "exefs").is_dir() or not romfs.is_dir():
        raise ValueError("Dossier exefs/romfs absent de la source")
    with (source / "exefs/main").open("rb") as stream:
        header = stream.read(0x100)
    if header[:4] != b"NSO0" or header[0x40:0x60].rstrip(b"\0").hex() != BUILD_ID:
        raise ValueError("Version du jeu incorrecte")
    if (source / "exefs/subsdk1").exists() or list((source / "exefs").glob("*.ips")):
        raise ValueError("La source semble deja modifiee ; utilisez le jeu original")
    if not (source / "exefs/main.npdm").is_file():
        raise ValueError("main.npdm absent")
    tree_files(source / "exefs")
    tree_files(romfs)


def normalize_exefs(original: Path, addon: Path, destination: Path) -> dict:
    destination.mkdir(parents=True)
    originals, modules = {}, {}
    for name in MODULES:
        base = original / name
        override = addon / name
        if base.exists():
            originals[name] = Nso(base.read_bytes())
        chosen = override if override.exists() else base
        if chosen.exists():
            modules[name] = Nso(chosen.read_bytes())
    if not {"rtld", "main", "subsdk0", "subsdk1", "sdk"}.issubset(modules):
        raise ValueError("Modules attendus absents : rtld/main/subsdk0/subsdk1/sdk")
    ips_report = []
    for patch in sorted(addon.glob("*.ips")):
        matches = [name for name, module in modules.items() if module.build_id == patch.stem.lower()]
        if len(matches) != 1:
            raise ValueError("IPS sans module cible unique : %s" % patch.name)
        module = modules[matches[0]]
        changes = module.apply(parse_ips(patch.read_bytes()))
        ips_report.append({"file": patch.name, "module": matches[0], "changes": changes})
    allowed = set(MODULES) | {p.name for p in addon.glob("*.ips")}
    if any(p.name not in allowed for p in addon.iterdir()):
        raise ValueError("Fichier ExeFS addon non pris en charge")
    layout = module_layout(modules)
    main = next(m["base"] for m in layout if m["name"] == "main")
    relative = {m["name"]: m["base"] - main for m in layout}
    # Current native helpers are linked at these module-relative addresses.
    expected = {"rtld": -0x20000, "main": 0, "subsdk0": 0x4EA5000,
                "subsdk1": 0x4F85000, "sdk": 0x5005000}
    for name, offset in expected.items():
        if relative.get(name) != offset:
            raise ValueError("Layout incompatible pour %s : %s au lieu de %#x" %
                             (name, hex(relative[name]) if name in relative else "absent", offset))
    branches, code_ranges = [], {}
    for name in originals:
        branches.extend(audit_changed_branches(name, originals[name].segments[0].data,
                                               modules[name].segments[0].data, layout))
        code_ranges[name] = changed_ranges(originals[name].segments[0].data, modules[name].segments[0].data)
    for name, module in modules.items():
        target = destination / name
        target.write_bytes(module.encode())
        reloaded = Nso(target.read_bytes())
        if reloaded.mapped_size != module.mapped_size or reloaded.end != module.end:
            raise FormatError("La normalisation a change la taille virtuelle : %s" % name)
        if any(a.memory != b.memory or a.data != b.data for a, b in zip(module.segments, reloaded.segments)):
            raise FormatError("Echec de verification apres normalisation : %s" % name)
    shutil.copyfile(original / "main.npdm", destination / "main.npdm")
    return {"layout": layout, "ips": ips_report, "changed_direct_branches": branches,
            "changed_code_ranges": code_ranges,
            "limitations": ["Appels indirects et interactions HLE non qualifies en jeu",
                            "Aucune garantie de compatibilite gameplay sur la seule base de cet audit"]}



def shared_cache_sources(tools: Path, workspace: Path, projects_root: Path | None = None, *, engine_id="longshot") -> list[Path]:
    """Discover caches by recorded paths, including when LOCALAPPDATA is redirected.

    Sharing is safe across tools/mods: the engine checks source/flags/dependency keys
    before using any object. We never replace an existing destination entry.
    """
    candidates = get_engine(engine_id).object_cache_candidates(tools)
    roots = (projects_root,) if projects_root is not None else (AppPaths.current().workspaces(engine_id), workspace.parent)
    reports = sorted({path for root in roots for path in root.glob("*/" + REPORT)})
    for report_path in reports:
        try:
            data = normalize_report(json.loads(report_path.read_text(encoding="utf-8")))
            if not data.get("tools_path") or data.get("engine", "longshot") != engine_id:
                continue
            project = report_path.parent.resolve()
            if Path(data["workspace"]).resolve() != project:
                continue
            work = work_directory(project, data)
            cache = work / get_engine(engine_id).object_cache_relative
            marker = work / ".hmb-owner.json"
            if marker.is_file() and json.loads(marker.read_text()) == {"workspace": str(project)}:
                candidates.append(cache)
        except (OSError, ValueError, KeyError):
            continue
    current_report = workspace / REPORT
    data = normalize_report(json.loads(current_report.read_text(encoding="utf-8"))) if current_report.is_file() else {}
    destination = (work_directory(workspace, data) / get_engine(engine_id).object_cache_relative).resolve()
    seen, result = {destination}, []
    for path in candidates:
        if path.is_dir() and path.resolve() not in seen:
            no_links(path)
            seen.add(path.resolve())
            result.append(path)
    return result



def prepare(source: Path, workspace: Path, tools: Path, repo: Path, variant: str,
            romfs_override: Path | None = None, *, engine_id="longshot") -> dict:
    source, workspace, tools, repo = (p.absolute() for p in (source, workspace, tools, repo))
    for path in (source, workspace, tools, repo):
        no_links(path)
    source, workspace, tools, repo = (p.resolve() for p in (source, workspace, tools, repo))
    independent(workspace, [source, tools, repo, Path(__file__).parent])
    if romfs_override:
        romfs_override = romfs_override.absolute()
        no_links(romfs_override)
        romfs_override = romfs_override.resolve()
        independent(workspace, [romfs_override])
        if not source.is_file() or not romfs_override.is_dir():
            raise ValueError("--romfs est reserve a un NUP avec un dossier RomFS existant")
    check_tools(tools, engine_id)
    manifest_path, manifest = read_manifest(repo, variant)
    require_dependencies()
    if not source.exists():
        raise ValueError("Source introuvable : %s" % source)
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Choisissez un dossier de travail vide ; aucune suppression automatique")
    if source.is_dir():
        check_source(source)
    elif source.suffix.lower() != ".nup":
        raise ValueError("La source doit etre un NUP ou un dossier exefs/romfs")
    workspace.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "tool_version": __version__, "status": "preparing",
              "created_utc": datetime.now(timezone.utc).isoformat(), "workspace": str(workspace),
              "source": str(source), "tools_path": str(tools), "engine": engine_id, "mods_repository": str(repo),
              "variant": variant, "manifest": manifest, "manifest_sha256": digest(manifest_path),
              "build_status": "not-built", "gameplay_validation": "not-tested", "preparation_pid": os.getpid()}
    # Atomic claim: concurrent preparations cannot overwrite one another's state.
    with (workspace / REPORT).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    try:
        original = source
        if source.is_file():
            original = workspace / "original"
            log("Extraction %s du NUP sans modifier les modules originaux..." %
                ("ExeFS" if romfs_override else "complete"))
            extract_original_nup(source, original, tools, only_exefs=bool(romfs_override), engine_id=engine_id)
            check_source(original, romfs_override)
        log("Reconstruction de la variante %s avec verification des empreintes..." % variant)
        run([sys.executable, str(repo / "install.py"), "--source", str(source if source.is_file() else original),
             "--variant", variant, "--output", str(workspace / "addon")], repo)
        report["audit"] = normalize_exefs(original / "exefs", workspace / "addon/exefs",
                                          workspace / "prepared/exefs")
        report["romfs"] = str(romfs_override or original / "romfs")
        report["external_romfs"] = bool(romfs_override)
        report["inventory"] = {
            "prepared": inventory(workspace / "prepared"), "addon": inventory(workspace / "addon")}
        report["status"] = "prepared"
        write_json(workspace / REPORT, report)
        log("Preparation terminee. Rapport : %s" % (workspace / REPORT))
        return report
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = "%s: %s" % (type(error).__name__, error)
        write_json(workspace / REPORT, report)
        raise



def work_directory(workspace: Path, report: dict) -> Path:
    """Use the recorded location; standalone CLI preparations remain self-contained."""
    return Path(report.get("build_work", str(workspace / "build-work")))


def build_request(workspace: Path, report: dict, jobs: int, language: str | None,
                  executable: str | None = None) -> BuildRequest:
    return BuildRequest(workspace=workspace, work_directory=work_directory(workspace, report), tools=Path(report["tools_path"]),
                        game=Path(report.get("game_dir", str(workspace / "game"))), romfs=Path(report["romfs"]),
                        python=executable or sys.executable, jobs=jobs, language=language,
                        preserve_preferences=bool(report.get("preserve_runtime_settings")),
                        options=report.get("build_options", {}))


def build_command(workspace: Path, report: dict, jobs: int, language: str | None,
                  executable: str | None = None) -> list[str]:
    # Validate optional legacy CLI graphics configuration before invoking tools.
    if not report.get("preserve_runtime_settings"):
        engine_for_report(report).build_environment(report)
    return engine_for_report(report).build_command(build_request(workspace, report, jobs, language, executable))


def build(workspace: Path, *, jobs=2, language=None, plan=False, build_python: Path | None = None,
          game_dir: Path | None = None, object_cache: Path | None = None):
    workspace = workspace.absolute()
    no_links(workspace)
    if plan:
        return _build(workspace, jobs=jobs, language=language, plan=True, build_python=build_python, game_dir=game_dir,
                      object_cache=object_cache)
    with workspace_lock(workspace):
        return _build(workspace, jobs=jobs, language=language, build_python=build_python, game_dir=game_dir,
                      object_cache=object_cache)


def _build(workspace: Path, *, jobs=2, language=None, plan=False, build_python: Path | None = None,
           game_dir: Path | None = None, object_cache: Path | None = None):
    workspace = workspace.absolute()
    no_links(workspace)
    workspace = workspace.resolve()
    report = load_prepared(workspace)
    if not 1 <= jobs <= 64:
        raise ValueError("--jobs doit etre compris entre 1 et 64")
    tools = Path(report["tools_path"])
    check_tools(tools, engine_for_report(report).id)
    game_dir = Path(game_dir or report.get("game_dir") or workspace / "game").absolute()
    no_links(game_dir)
    game_dir = game_dir.resolve()
    own_romfs = Path(report["romfs"]).resolve() == game_dir / "romfs"
    independent(game_dir, [Path(report["source"]), *([] if own_romfs else [Path(report["romfs"])]), tools,
                           Path(report["mods_repository"]), workspace / "prepared", workspace / "addon",
                           work_directory(workspace, report), Path(__file__).resolve().parent])
    if game_dir == workspace or workspace.is_relative_to(game_dir):
        raise ValueError("Le dossier du jeu ne doit pas contenir le dossier de travail")
    report["game_dir"] = str(game_dir)
    executable = str(Path(build_python or report.get("build_python") or sys.executable).resolve())
    command = build_command(workspace, report, jobs, language, executable)
    backend = engine_for_report(report)
    graphics_environment = backend.build_environment(report)
    if plan:
        log(subprocess.list2cmdline(command))
        return
    require_build_python(executable, backend.build_dependencies)
    work = work_directory(workspace, report)
    independent(work, [game_dir, workspace / "prepared", workspace / "addon",
                       Path(report["source"]), Path(report["romfs"]), tools,
                       Path(__file__).resolve().parent])
    for path in (game_dir, work):
        no_links(path)
        if path.exists():
            tree_files(path)
            marker = path / ".hmb-owner.json"
            if not marker.is_file() or json.loads(marker.read_text()) != {"workspace": str(workspace)}:
                raise ValueError("Dossier existant non cree par cet outil : %s" % path)
        path.mkdir(parents=True, exist_ok=True)
        write_json(path / ".hmb-owner.json", {"workspace": str(workspace)})
    # Only the matching RomFS override is installed; ExeFS has already been compiled in.
    mod = game_dir / "mods" / ("00-OOT-" + report["variant"])
    if report["variant"] == "vanilla":
        report["installed_overlay"] = {}
    elif mod.exists():
        if inventory(mod) != report.get("installed_overlay", {}):
            raise ValueError("L'overlay installe a ete modifie ; utilisez un nouveau dossier de preparation")
    else:
        mod.mkdir(parents=True)
        shutil.copytree(workspace / "addon/romfs", mod / "romfs")
    if report["variant"] != "vanilla":
        report["installed_overlay"] = inventory(mod)
    report["build_status"] = "building"
    report["build_command"] = command
    report["build_python"] = executable
    write_json(workspace / REPORT, report)
    try:
        audit_path = Path(__file__).resolve().parents[1] / "audit_engine.py"
        run([executable, "-B", str(audit_path), "--workspace", str(workspace)], tools,
            logfile=workspace / "build.log", engine_id=backend.id)
        # Run the backend's environment check BEFORE importing caches, otherwise a
        # toolchain may invalidate the objects we just imported. The first build of
        # each profile silently deletes every object we just imported.
        log("Verification de l'environnement de compilation avant partage du cache…")
        request = build_request(workspace, report, jobs, language, executable)
        run(backend.preflight_command(request), tools, logfile=workspace / "build.log", environment=graphics_environment, engine_id=backend.id)
        destination_cache = work_directory(workspace, report) / backend.object_cache_relative
        signature = backend.object_cache_signature(destination_cache)
        donors = ([object_cache.absolute()] if object_cache else []) + shared_cache_sources(tools, workspace, engine_id=backend.id)
        seen, seeded = set(), []
        for donor in donors:
            if donor.resolve() in seen:
                continue
            seen.add(donor.resolve())
            donor_signature = backend.object_cache_signature(donor)
            if not signature or donor_signature != signature:
                log("Cache ignore : signature d'environnement absente ou differente (%s)." % donor)
                continue
            copied = backend.seed_objects(donor, destination_cache)
            seeded.append({"source": str(donor.resolve()), "objects_copied": copied})
        report["shared_object_caches"] = seeded
        log("Cache partage : %d objets ajoutes depuis %d cache(s) ; le moteur verifie leurs cles avant reutilisation." %
            (sum(item["objects_copied"] for item in seeded), len(seeded)))
        run(command, tools, logfile=workspace / "build.log", environment=graphics_environment, engine_id=backend.id)
        if not any((game_dir / name).is_file() for name in backend.layout.executables):
            raise ValueError("Le moteur a termine sans executable identifiable")
        report["build_status"] = "built-unverified-in-game"
        write_json(workspace / REPORT, report)
        log("Compilation terminee : %s. Test en jeu encore necessaire." % game_dir)
    except BaseException as error:
        report["build_status"] = "failed"
        report["build_error"] = "%s: %s" % (type(error).__name__, error)
        write_json(workspace / REPORT, report)
        raise
