"""Application data locations, independent from source and executable locations."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @classmethod
    def current(cls, override: str = "") -> "AppPaths":
        configured = override or os.environ.get("MOD_MANAGER_DATA", "")
        if configured:
            return cls(Path(configured).resolve())
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        return cls(base / "OOTModManager")

    @property
    def library(self) -> Path:
        return self.root / "library"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def workspaces(self, engine: str) -> Path:
        return self.root / "workspaces" / self._engine_id(engine)

    def native_cache(self, engine: str) -> Path:
        return self.root / "cache/native-builds" / self._engine_id(engine)

    def compilation(self, workspace: Path, engine: str) -> Path:
        identity = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:12]
        return self.root / "cache/compilation" / self._engine_id(engine) / (workspace.name + "-" + identity)

    @staticmethod
    def _engine_id(engine: str) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", engine):
            raise ValueError("Identifiant de moteur invalide")
        return engine
