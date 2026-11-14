"""Contracts between the manager's orchestration and a recompilation engine.

Backends are trusted, bundled Python modules, never code loaded from Addon ZIPs.
They describe tool/runtime conventions; the manager owns transactions and UI state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from ..progress import Progress

CommandRunner = Callable[[list[str]], None]
StageReporter = Callable[[str, str], None]


class RuntimeSettings(Protocol):
    """Only runtime-related input fields used by the legacy CLI operations."""

    tools_path: str
    game_dir: str
    preserve_runtime_settings: bool
    language: str
    button_prompts: int
    dlss: bool
    dlss_license: bool
    ngx_sdk: str


@dataclass(frozen=True)
class EngineCapabilities:
    """Operations qualified by a backend, not a promise about every Addon."""

    native_addons: bool
    resource_overlays: bool
    wheel_clock: bool


@dataclass(frozen=True)
class InstallationLayout:
    """Relative, backend-owned paths used by deployment and native snapshots."""

    executables: tuple[str, ...]
    image: str
    version: str
    stored_exefs: str
    native_roots: tuple[str, ...]
    preferences: tuple[str, ...]
    audit_file: str
    extra_files: tuple[str, ...] = ()
    library_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from ..storage import safe_relative
        if not self.executables:
            raise ValueError("Le moteur doit déclarer au moins un exécutable.")
        for name in (*self.executables, self.image, self.version, self.stored_exefs,
                     *self.native_roots, *self.preferences, self.audit_file,
                     *self.extra_files, *self.library_roots):
            path = safe_relative(name)
            if path.parts[0].casefold() in ("romfs", "user"):
                raise ValueError("Le moteur ne peut pas gérer le RomFS ou les sauvegardes.")


@dataclass(frozen=True)
class BuildRequest:
    """Resolved inputs for a compiler invocation; no UI or library state."""

    workspace: Path
    work_directory: Path
    tools: Path
    game: Path
    romfs: Path
    python: str
    jobs: int
    language: str | None
    preserve_preferences: bool
    options: dict


@dataclass(frozen=True)
class ModRequest:
    """Mod-specific preparation inputs, isolated from the manager's settings."""

    workspace: Path
    tools: Path
    variant: str
    clock: bool
    hold_ms: int
    python: str


class EngineBackend(ABC):
    """In-process boundary. Methods raise on unsupported/invalid operations.

    Commands are argument lists, not shell text. Implementations may read tools
    and installations, but may not silently update them or choose another backend.
    """

    id: str
    name: str
    capabilities: EngineCapabilities
    layout: InstallationLayout
    isolated_build_variables: tuple[str, ...]
    build_dependencies: tuple[str, ...]
    object_cache_relative: str

    @abstractmethod
    def progress_parser(self) -> Progress: ...

    @abstractmethod
    def validate_tools(self, tools: Path) -> None: ...

    @abstractmethod
    def validate_compiler(self, tools: Path) -> None: ...

    def launch_command(self, game: Path) -> list[str]:
        """Prefer a root launcher to its internal binary when both exist."""
        for name in sorted(self.layout.executables, key=lambda value: len(Path(value).parts)):
            executable = game / name
            if executable.is_file():
                return [str(executable)]
        return []

    @abstractmethod
    def compiler_python(self, tools: Path) -> str: ...

    @abstractmethod
    def discover_tools(self) -> list[Path]: ...

    @abstractmethod
    def default_build(self) -> dict: ...

    def installation_source(self, game: Path) -> str:
        """Optional existing source recorded for this exact installation."""
        return ""

    @abstractmethod
    def installed_renderer(self, game: Path, tools: Path) -> tuple[str, str]: ...

    @abstractmethod
    def build_environment(self, report: dict) -> dict[str, str]: ...

    @abstractmethod
    def staged_runtime(self, report: dict, previous: Path) -> dict: ...

    @abstractmethod
    def build_command(self, request: BuildRequest) -> list[str]: ...

    @abstractmethod
    def preflight_command(self, request: BuildRequest) -> list[str]: ...

    @abstractmethod
    def object_cache_candidates(self, tools: Path) -> list[Path]: ...

    @abstractmethod
    def object_cache_signature(self, cache: Path) -> str | None: ...

    @abstractmethod
    def seed_objects(self, source: Path, destination: Path) -> int: ...

    @abstractmethod
    def tools_signature(self, tools: Path) -> str: ...

    @abstractmethod
    def preparation_signature(self, workspace: Path, report: dict, *, legacy: bool = False) -> str: ...

    @abstractmethod
    def native_cache_options(self, report: dict) -> dict: ...

    @abstractmethod
    def extract_source(self, source: Path, destination: Path, tools: Path,
                       *, only_exefs: bool = False) -> None: ...

    @abstractmethod
    def audit_preparation(self, workspace: Path, tools: Path, report: dict) -> None: ...

    @abstractmethod
    def ensure_game_closed(self) -> None: ...

    @abstractmethod
    def runtime_matches(self, report: dict, game: Path) -> bool: ...

    @abstractmethod
    def normalize_language(self, language: str) -> str: ...

    @abstractmethod
    def validate_runtime_settings(self, settings: RuntimeSettings) -> None: ...

    @abstractmethod
    def prepare_runtime(self, settings: RuntimeSettings, tools: Path, python: str,
                        run: CommandRunner, *, read_only: bool) -> dict: ...

    @abstractmethod
    def preferences_match(self, game: Path, language: str, prompts: int) -> bool: ...

    @abstractmethod
    def apply_preferences(self, settings: RuntimeSettings, report: dict, python: str,
                          run: CommandRunner, stage: StageReporter) -> None: ...

    @abstractmethod
    def mod_needs_update(self, report: dict, request: ModRequest) -> bool: ...

    @abstractmethod
    def adapt_mod(self, report: dict, request: ModRequest, run: CommandRunner, stage: StageReporter) -> None: ...

    @abstractmethod
    def installed_code_matches(self, report: dict, workspace: Path, game: Path) -> bool: ...

    @abstractmethod
    def installed_mod_settings(self, report: dict, game: Path, request: ModRequest,
                               executable_hash: str | None) -> tuple[bool, bool]: ...

    @abstractmethod
    def configure_mod(self, request: ModRequest, game: Path, run: CommandRunner, stage: StageReporter,
                      *, mark_installed: bool = False) -> None: ...

    @abstractmethod
    def finalize_build(self, request: ModRequest, game: Path, run: CommandRunner, stage: StageReporter) -> None: ...
