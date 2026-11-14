"""Explicit registry of bundled engines. Unknown IDs never fall back silently."""
from .base import BuildRequest, ModRequest, EngineBackend, EngineCapabilities, InstallationLayout


def _longshot() -> EngineBackend:
    from .longshot import LongshotBackend
    return LongshotBackend()


_FACTORIES = {"longshot": _longshot}


def get_engine(identifier: str = "longshot") -> EngineBackend:
    try:
        factory = _FACTORIES[identifier]
    except (KeyError, TypeError):
        raise ValueError("Moteur non pris en charge : " + str(identifier)) from None
    return factory()


def engine_for_report(report: dict) -> EngineBackend:
    return get_engine(report.get("engine", "longshot"))
