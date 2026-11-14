"""Longshot's toolchain and runtime conventions; no library or UI state."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys

from .base import (BuildRequest, ModRequest, EngineBackend, EngineCapabilities, InstallationLayout,
                   RuntimeSettings, CommandRunner, StageReporter)
from . import longshot_launcher


class LongshotBackend(EngineBackend):
    id = "longshot"
    name = "Longshot"
    isolated_build_variables = ("LONGSHOT_NGX_SDK",)
    build_dependencies = ("lz4.block", "zstandard", "capstone", "numpy", "unicorn")
    object_cache_relative = "objcache"
    capabilities = EngineCapabilities(native_addons=True, resource_overlays=True, wheel_clock=True)
    layout = InstallationLayout(
        executables=("bin/longshot.exe", "longshot.exe", "longshot"),
        image="image.bin", version="longshot_version.txt", stored_exefs=".longshot_exefs",
        native_roots=("bin", "prompts", ".longshot_exefs", "ngx"),
        preferences=("language.txt", "longshot_options.ini", "longshot_env.txt", "prompts", "ngx",
                     "bin/longshot_vk.dll", "bin/SDL2.dll", "bin/SDL3.dll", "bin/wgpu_native.dll"),
        audit_file="longshot-loader-audit.json",
        extra_files=(".hmb-wheel-clock.json",), library_roots=("bin",),
    )

    def progress_parser(self):
        from .longshot_progress import LongshotProgress
        return LongshotProgress()

    def compiler_python(self, tools: Path) -> str:
        python = tools / "python/python.exe"
        return str(python) if python.is_file() else sys.executable

    def validate_compiler(self, tools: Path) -> None:
        self.validate_tools(tools)
        if not (tools / "python/python.exe").is_file():
            raise ValueError("Les outils Longshot sont incomplets : python/python.exe est absent. Sélectionnez le dossier tools du Builder.")

    def discover_tools(self) -> list[Path]:
        return longshot_launcher.tools_candidates()

    def default_build(self) -> dict:
        return longshot_launcher.default_build()

    def installation_source(self, game: Path) -> str:
        return longshot_launcher.installation_source(game)

    def installed_renderer(self, game: Path, tools: Path) -> tuple[str, str]:
        from .longshot_runtime import renderer
        return renderer(game, tools)

    def build_environment(self, report: dict) -> dict[str, str]:
        if report.get("preserve_runtime_settings"):
            from .longshot_runtime import environment
        else:
            from .longshot_dlss import environment
        return environment(report)

    def staged_runtime(self, report: dict, previous: Path) -> dict:
        from ..storage import safe_relative
        if report.get("preserve_runtime_settings") and report.get("renderer_relative"):
            return {"prebuilt_renderer": str(previous / safe_relative(report["renderer_relative"]))}
        return {}

    def build_command(self, request: BuildRequest) -> list[str]:
        command = [request.python, "-I", "-B", str(request.tools / "nx2/make_game.py"),
                   "--exefs", str(request.workspace / "prepared/exefs"), "--romfs", str(request.romfs),
                   "--out", str(request.game), "--work", str(request.work_directory),
                   "--jobs", str(request.jobs), "--no-prepare-shaders"]
        if request.language and not request.preserve_preferences:
            from .longshot_preferences import canonical_language
            command += ["--language", canonical_language(request.language)]
        if request.options.get("dlss") and not request.preserve_preferences:
            command += ["--fetch-ngx-sdk", "--accept-nvidia-license"]
        return command

    def preflight_command(self, request: BuildRequest) -> list[str]:
        return [request.python, "-I", "-B", "-c",
                "import runpy,sys; m=runpy.run_path(sys.argv[1]); m['check_windows_sdk'](sys.argv[2]); m['drop_stale_objects'](sys.argv[2])",
                str(request.tools / "nx2/make_game.py"), str(request.work_directory)]

    def object_cache_candidates(self, tools: Path) -> list[Path]:
        candidates = []
        for parent in tools.resolve().parents:
            if parent.name.casefold() == "longshotlauncher" and (parent / "toolchains").is_dir():
                candidates.append(parent / "work/objcache")
        candidates.append(longshot_launcher.launcher_root() / "work/objcache")
        return candidates

    def object_cache_signature(self, cache: Path) -> str | None:
        note = cache.parent / "system_headers.txt"
        return note.read_text().strip() if note.is_file() else None

    def seed_objects(self, source: Path, destination: Path) -> int:
        from .longshot_cache import seed_object_cache
        return seed_object_cache(source, destination)

    def audit_preparation(self, workspace: Path, tools: Path, report: dict) -> None:
        from .longshot_audit import audit
        audit(workspace, tools, report)

    def mod_needs_update(self, report: dict, request: ModRequest) -> bool:
        from .longshot_mods import needs_update
        return needs_update(report, request)

    def adapt_mod(self, report: dict, request: ModRequest, run: CommandRunner, stage: StageReporter) -> None:
        from .longshot_mods import adapt
        adapt(report, request, run, stage)

    def configure_mod(self, request: ModRequest, game: Path, run: CommandRunner,
                      stage: StageReporter, *, mark_installed: bool = False) -> None:
        stage("configure", "Enregistrement du réglage modifiable…" if mark_installed else
              "Application du délai, sans recompilation…")
        command = [request.python, "-B", "-m", "modmanager.engines.longshot_delay", "--workspace",
                   str(request.workspace), "--hold-ms", str(request.hold_ms)]
        if mark_installed or not (game / ".hmb-wheel-clock.json").exists():
            command.append("--mark-installed")
        run(command)

    def finalize_build(self, request: ModRequest, game: Path, run: CommandRunner, stage: StageReporter) -> None:
        if request.clock and request.variant == "item-wheel":
            self.configure_mod(request, game, run, stage, mark_installed=True)

    def runtime_matches(self, report: dict, game: Path) -> bool:
        from .longshot_dlss import runtime_matches
        return runtime_matches(report, game)

    def normalize_language(self, language: str) -> str:
        from .longshot_preferences import canonical_language
        return canonical_language(language)

    def validate_runtime_settings(self, settings: RuntimeSettings) -> None:
        from .longshot_preferences import PROMPTS
        if settings.button_prompts not in PROMPTS.values():
            raise ValueError("Icônes de manette inconnues")

    def prepare_runtime(self, settings: RuntimeSettings, tools: Path, python: str,
                        run: CommandRunner, *, read_only: bool) -> dict:
        from .longshot_dlss import prepare_options, default_sdk
        result = {"preserve_runtime_settings": settings.preserve_runtime_settings}
        if settings.preserve_runtime_settings:
            relative, fingerprint = self.installed_renderer(Path(settings.game_dir), tools)
            result.update(build_options={"renderer_sha256": fingerprint},
                          prebuilt_renderer=str(Path(settings.game_dir) / relative), renderer_relative=relative,
                          ngx_sdk="", nvidia_license_accepted=False)
        else:
            result.update(build_options=prepare_options(settings, tools, python, run, read_only=read_only),
                          ngx_sdk=str(Path(settings.ngx_sdk or default_sdk()).resolve()) if settings.dlss else "",
                          nvidia_license_accepted=bool(settings.dlss and settings.dlss_license))
        return result

    def preferences_match(self, game: Path, language: str, prompts: int) -> bool:
        from .longshot_preferences import preferences_match
        return preferences_match(game, language, prompts)

    def apply_preferences(self, settings: RuntimeSettings, report: dict, python: str,
                          run: CommandRunner, stage: StageReporter) -> None:
        from .longshot_preferences import FACES, apply_preferences
        game = Path(settings.game_dir)
        face = FACES.get(settings.button_prompts)
        if face and not (game / "prompts" / face).is_dir():
            stage("configure", "Génération des icônes de manette — sans compiler le jeu…")
            run([python, "-I", "-B", str(Path(settings.tools_path) / "nx2/prompt_assets.py"),
                 "--romfs", report["romfs"], "--out", str(game / "prompts"), "--incremental"])
        apply_preferences(game, settings.language, settings.button_prompts)

    def validate_tools(self, root: Path) -> None:
        from ..storage import no_links
        no_links(root)
        for relative in ("nx2/make_game.py", "nx2/image.py", "nx2/lift.py", "nx2/standalone.py",
                         "third_party/a64-kit/tools/nso.py"):
            if not (root / relative).is_file():
                raise ValueError("Checkout Longshot incomplet : %s" % (root / relative))
        image = (root / "nx2/image.py").read_text(encoding="utf-8")
        if "class EdenImage" not in image or "CODE_39BIT = 0x80000000" not in image:
            raise ValueError("Version du layout Longshot inconnue ; integration a reexaminer")
        if "LONGSHOT_VK_PREBUILT" not in (root / "nx2/make_game.py").read_text(encoding="utf-8"):
            raise ValueError("Ces outils ne sont pas une version Longshot prise en charge.")

    def extract_source(self, source: Path, destination: Path, longshot: Path, *, only_exefs=False) -> None:
        """Keep original NSO bytes while extracting with Longshot's strict parser."""
        from ..storage import load_module, safe_relative, digest
        from ..game import TITLE_ID, UPDATE
        from ..formats import FormatError
        reader = load_module(longshot / "nx2/nup.py", "hmb_upstream_nup")
        nup = reader.Nup(str(source), strict=True)
        try:
            # Switch updates use the application's title ID + 0x800 in NUP metadata.
            application = int(TITLE_ID, 16)
            candidates = [t for t in nup.titles if t["id"] in (application, application + 0x800)
                          and t["version"] == UPDATE]
            if len(candidates) != 1:
                raise ValueError("Le NUP doit contenir exactement le programme/update attendu")
            title = candidates[0]
            # Validate all member names before creating any extraction file.
            members = []
            seen = set()
            for part in (("exefs",) if only_exefs else ("exefs", "romfs")):
                for relative, record in nup.walk(title[part]):
                    path = Path(part) / safe_relative(relative)
                    key = path.as_posix().casefold()
                    if key in seen:
                        raise ValueError("Membre NUP duplique : %s" % path)
                    seen.add(key)
                    members.append((path, record))
            required = sum(r[2] for _, r in members)
            if shutil.disk_usage(destination.parent).free < required + (1 << 30):
                raise ValueError("Espace insuffisant pour extraire le NUP et preparer les modules")
            expected = {id(record): nup.file_details[i][0] for i, record in enumerate(nup.files)}
            for index, (relative, record) in enumerate(members):
                path = destination / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as output:
                    nup.copy_to(record, output)
                if digest(path) != expected[id(record)].hex():
                    raise FormatError("Empreinte du membre NUP incorrecte : %s" % relative)
                if index % 500 == 0:
                    print("Extraction originale : %d/%d fichiers" % (index + 1, len(members)), flush=True)
        finally:
            nup.f.close()

    def tools_signature(self, tools: Path) -> str:
        from ..storage import digest
        h = hashlib.sha256(str(tools.resolve()).encode())
        for top in ("nx2", "host", "gpu", "third_party/a64-kit"):
            folder = tools / top
            for directory, dirs, files in os.walk(folder):
                dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git", "work"))
                for name in sorted(files):
                    p = Path(directory) / name
                    if p.suffix in (".py", ".c", ".cpp", ".h", ".hpp", ".inc", ".inl"):
                        h.update(p.relative_to(tools).as_posix().encode())
                        h.update(bytes.fromhex(digest(p)))
        version = tools / "version.txt"
        if version.is_file():
            h.update(version.read_bytes())
        return h.hexdigest()

    def preparation_signature(self, workspace: Path, report: dict, *, legacy: bool = False) -> str:
        from .longshot_signatures import prepared_signature
        return prepared_signature(workspace, report, legacy=legacy)

    def native_cache_options(self, report: dict) -> dict:
        options = report.get("build_options", {})
        return options if options.get("dlss") or options.get("renderer_sha256") else {}

    def ensure_game_closed(self) -> None:
        """Shared precondition for installation and removal operations."""
        if os.name != "nt":
            return
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq longshot.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, errors="replace",
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError("Impossible de vérifier si Longshot est fermé. Réessayez avant d’appliquer les changements.")
        if '"longshot.exe"' in result.stdout.lower():
            raise ValueError("Fermez Longshot avant d’appliquer les changements ou de désinstaller un mod.")


    def installed_code_matches(self, report: dict, workspace: Path, game: Path) -> bool:
        """Check guest bytes, excluding only a verified adapter's runtime setting."""
        import json
        from ..signatures import image_digest
        audit_path = workspace / self.layout.audit_file
        if not audit_path.is_file():
            return False
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        config = next((a.get("runtime_config") for a in report.get("native_adapters", [])
                       if a.get("revision") in (2, 3)), None)
        ignored = config - report["audit"]["layout"][0]["base"] if config is not None else None
        expected = audit.get("image_sha256_without_clock_config" if config is not None else "image_sha256")
        return bool(expected and image_digest(game / self.layout.image, ignored) == expected)

    def installed_mod_settings(self, report: dict, game: Path, request: ModRequest,
                               executable_hash: str | None) -> tuple[bool, bool]:
        """Return marker integrity and setting equality as separate observations."""
        import json
        import struct
        code_matches = True
        game_exists = any((game/name).is_file() for name in self.layout.executables) and (game/self.layout.image).is_file()
        adapters = report.get("native_adapters", [])
        settings_match = not request.clock or request.variant != "item-wheel"
        if request.clock and request.variant == "item-wheel":
            marker = game / ".hmb-wheel-clock.json"
            settings_match = False
            if adapters and marker.exists() and game_exists:
                try:
                    identity = json.loads(marker.read_text())
                    valid_marker = (identity["exe_sha256"] == executable_hash and
                                    identity["code_sha256"] == adapters[0]["code_sha256"])
                    with (game / self.layout.image).open("rb") as stream:
                        stream.seek(identity["config_offset"])
                        actual_ms = struct.unpack("<I", stream.read(4))[0]
                    settings_match = valid_marker and actual_ms == request.hold_ms
                    if not valid_marker:
                        code_matches = False
                except (ValueError, KeyError, OSError, struct.error):
                    code_matches = False
        return code_matches, settings_match
