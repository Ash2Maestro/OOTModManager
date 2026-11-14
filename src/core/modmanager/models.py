"""Planning and progress parsing shared by the desktop UI and its worker."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path

from .pipeline import REPORT
from .engines import get_engine
from .paths import AppPaths
from .state import normalize_report

tools_candidates = get_engine().discover_tools


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "gui-build-state.json"



@dataclass
class Settings:
    source: str = ""
    romfs: str = ""
    workspace: str = ""
    game_dir: str = ""
    tools_path: str = ""
    data_root: str = ""
    engine: str = "longshot"
    mods_repo: str = ""
    variant: str = "item-wheel"
    clock: bool = True
    hold_ms: int = 100
    jobs: int = 6
    language: str = "fr"
    button_prompts: int = 0
    native_cache: str = ""
    native_cache_limit_mib: int = 2048
    dlss: bool = False
    dlss_license: bool = False
    ngx_sdk: str = ""
    preserve_runtime_settings: bool = False
    ui_language: str = "fr"

    def __post_init__(self):
        self.language = get_engine(self.engine).normalize_language(self.language)

    def to_dict(self):
        return asdict(self)


@dataclass
class Plan:
    action: str
    title: str
    reason: str



def projects(base: Path | None = None):
    base = base or AppPaths.current().root / "workspaces"
    result = []
    if base.exists():
        paths = {*base.glob("*/" + REPORT), *base.glob("*/*/" + REPORT)}
        for path in sorted(paths):
            try:
                report = normalize_report(json.loads(path.read_text(encoding="utf-8")))
                if report.get("status") == "prepared" and report.get("tools_path"):
                    result.append((path.parent, report))
            except (OSError, ValueError):
                continue
    return sorted(result, key=lambda item: (item[1].get("variant") != "item-wheel", str(item[0])))


def settings_from_report(path, report):
    tools = Path(report["tools_path"])
    if not tools.exists():
        candidates = tools_candidates()
        if candidates:
            tools = candidates[0]
    adapters = report.get("native_adapters", [])
    return Settings(source=report["source"], romfs=report.get("romfs", ""), workspace=str(path),
                    game_dir=report.get("game_dir", str(path / "game")), tools_path=str(tools), engine=report.get("engine", "longshot"),
                    mods_repo=report["mods_repository"], variant=report["variant"],
                    clock=bool(adapters), hold_ms=adapters[0].get("hold_ms", 100) if adapters else 100,
                    dlss=bool(report.get("build_options", {}).get("dlss")),
                    dlss_license=bool(report.get("nvidia_license_accepted")), ngx_sdk=report.get("ngx_sdk", ""),
                    language=report.get("runtime_preferences", {}).get("language", "fr"),
                    button_prompts=report.get("runtime_preferences", {}).get("button_prompts", 0))







def choose_action(*, prepared, code_matches, settings_match, game_exists, force=False, resources_match=True):
    if not prepared:
        return Plan("prepare", "Préparer et compiler", "Ce projet n'a pas encore été préparé.")
    if force or not game_exists or not code_matches:
        return Plan("build", "Recompiler avec le cache", "Le code, les outils ou l'installation ont changé.")
    if not settings_match:
        return Plan("configure", "Appliquer le réglage seul", "Le code est déjà installé : aucune recompilation nécessaire.")
    if not resources_match:
        return Plan("resources", "Appliquer les ressources", "Le code est identique : mise à jour des fichiers du mod sans compilation.")
    return Plan("ready", "Déjà à jour", "Le code installé et les réglages correspondent au projet.")
