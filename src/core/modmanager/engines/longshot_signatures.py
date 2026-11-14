"""Longshot guest signature; only its qualified runtime clock word is masked."""
import hashlib
from pathlib import Path
from ..formats import Nso
from ..storage import digest


def prepared_signature(workspace: Path, report, legacy=False):
    """The configurable clock word is data, so changing it does not invalidate code."""
    h = hashlib.sha256()
    config = next((a.get("runtime_config") for a in report.get("native_adapters", []) if a.get("revision") in (2, 3)), None)
    bases = {m["name"]: m["base"] for m in report["audit"]["layout"]}
    for p in sorted((workspace / "prepared/exefs").iterdir()):
        h.update(p.name.encode())
        if p.name == "subsdk1" and config is not None:
            module = Nso(p.read_bytes())
            relative = config - bases[p.name]
            for segment in module.segments:
                raw = bytearray(segment.data)
                if segment.memory <= relative and relative + 4 <= segment.memory + len(raw):
                    raw[relative - segment.memory:relative - segment.memory + 4] = bytes(4)
                h.update(str((segment.memory, len(raw))).encode())
                h.update(raw)
            h.update(str(module.end).encode())
        else:
            h.update(bytes.fromhex(digest(p)))
    if legacy:
        h.update(report["manifest_sha256"].encode())
    return h.hexdigest()
