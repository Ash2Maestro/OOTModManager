"""Longshot-specific wheel adaptation and qualification, before deployment."""
from pathlib import Path
import struct

from .base import ModRequest
from ..formats import Nso, Record
from ..storage import digest, inventory, write_json
from ..state import REPORT
from ..wheel_input import REVISION as WHEEL_ADAPTER_REVISION

ROOT = Path(__file__).resolve().parents[2]


def needs_update(report: dict, request: ModRequest) -> bool:
    adapters = report.get("native_adapters", [])
    if not request.clock or request.variant != "item-wheel":
        return bool(adapters)
    return not (len(adapters) == 1 and adapters[0].get("revision") == WHEEL_ADAPTER_REVISION and
                adapters[0].get("source_sha256") == digest(ROOT / "adapters/wheel_clock.c"))


def adapt(report: dict, request: ModRequest, run, stage) -> None:
    if request.clock and request.variant == "item-wheel":
        stage("prepare", "Préparation du délai de la roue…")
        if needs_update(report, request):
            stage("audit", "Comparaison de l'image et des points d'entrée…")
            run([request.python, "-B", str(ROOT / "audit_engine.py"), "--workspace", str(request.workspace),
                 "--tools", str(request.tools)])
            run([request.python, "-B", "-m", "modmanager.engines.longshot_wheel", "--workspace", str(request.workspace),
                      "--tools", str(request.tools), "--hold-ms", str(request.hold_ms)])
        else:
            adapter = report["native_adapters"][0]
            if adapter["hold_ms"] != request.hold_ms:
                path = request.workspace / "prepared/exefs/subsdk1"
                module = Nso(path.read_bytes())
                base = next(m["base"] for m in report["audit"]["layout"] if m["name"] == "subsdk1")
                module.apply([Record(adapter["runtime_config"] - base, struct.pack("<I", request.hold_ms))])
                path.write_bytes(module.encode())
                adapter["hold_ms"] = request.hold_ms
                report["inventory"]["prepared"] = inventory(request.workspace / "prepared")
                write_json(request.workspace / REPORT, report)
        run([request.python, "-B", str(ROOT / "diagnose_wheel_timing.py"), "--exefs",
                  str(request.workspace / "prepared/exefs"), "--verify-clock", "--hold-ms", str(request.hold_ms)])
    elif report.get("native_adapters"):
        path = request.workspace / "prepared/exefs/subsdk1"
        original = Nso((request.workspace / "addon/exefs/subsdk1").read_bytes())
        path.write_bytes(original.encode())
        report.pop("native_adapters", None)
        report["inventory"]["prepared"] = inventory(request.workspace / "prepared")
        report["build_status"] = "needs-rebuild"
        write_json(request.workspace / REPORT, report)
