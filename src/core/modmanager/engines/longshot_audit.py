"""Cross-check prepared modules using Longshot's actual loader before recompiling."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

from ..storage import write_json


def audit(workspace: Path, tools: Path, report: dict):
    root = tools.resolve()
    from . import get_engine
    get_engine("longshot").validate_tools(root)
    sys.path.insert(0, str(root / "nx2"))
    import kit  # noqa: F401 - installs the vendored kit's import paths
    import nso2  # noqa: F401 - adds Switch 2 relocations
    import nso
    import image
    import standalone

    exefs = str(workspace / "prepared/exefs")
    hle, stubbed = standalone.hle_set(nso.load_exefs(exefs))
    img = image.EdenImage(exefs, 0, hle=hle | stubbed)
    actual = {m.name: m for m in img.modules}
    for expected in report["audit"]["layout"]:
        module = actual[expected["name"]]
        if module.base != expected["base"]:
            raise ValueError("Le chargeur Longshot place %s a une autre adresse" % module.name)
        if image.eden_size(module) != expected["size"]:
            raise ValueError("La taille calculee par Longshot differe pour %s" % module.name)
    for branch in report["audit"]["changed_direct_branches"]:
        if not img.in_code(branch["target"]):
            raise ValueError("Longshot ne reconnait pas la cible de branchement %#x" % branch["target"])
    overlaps = []
    for name, ranges in report["audit"]["changed_code_ranges"].items():
        module = actual[name]
        for symbol in module.symbols:
            address = module.base + symbol["value"]
            if not symbol["defined"] or address not in img.hooks:
                continue
            size = max(4, symbol["size"])
            if any(start < symbol["value"] + size and symbol["value"] < stop for start, stop in ranges):
                overlaps.append({"module": name, "symbol": symbol["name"], "address": address})
    ips_checked = 0
    for patch in report["audit"]["ips"]:
        module = actual[patch["module"]]
        # The prepared NSO's initialized bytes must survive the real loader/relocator.
        from modmanager.formats import Nso
        prepared = Nso((Path(exefs) / module.name).read_bytes())
        for change in patch["changes"]:
            lo, size = change["offset"], change["size"]
            segment = prepared.segments[change["segment"]]
            expected = segment.data[lo - segment.memory:lo - segment.memory + size]
            if img.read(module.base + lo, size) != expected:
                raise ValueError("Les octets IPS different apres chargement/relocalisation Longshot")
            ips_checked += 1
    result = {"loader": "Longshot EdenImage", "tools_path": str(root), "module_bases_match": True,
              "ips_records_preserved": ips_checked, "hle_overlaps": overlaps,
              "unresolved_imports": img.unresolved,
              "note": "Ne couvre pas tous les appels indirects, hooks internes et comportements runtime"}
    result["image_sha256"] = hashlib.sha256(img.mem).hexdigest()
    config = next((a.get("runtime_config") for a in report.get("native_adapters", []) if a.get("revision") in (2, 3)), None)
    if config is not None:
        raw = bytearray(img.mem)
        offset = config - img.modules[0].base
        raw[offset:offset + 4] = bytes(4)
        result["image_sha256_without_clock_config"] = hashlib.sha256(raw).hexdigest()
    result["clock_exports"] = {}
    for name in ("_ZN2nn2os13GetSystemTickEv", "_ZN2nn2os22GetSystemTickFrequencyEv"):
        if name in img.exports:
            owner, symbol = img.exports[name]
            result["clock_exports"][name] = owner.base + symbol["value"]
    write_json(workspace / "longshot-loader-audit.json", result)
    if overlaps:
        raise ValueError("Modification dans une fonction remplacee par HLE ; voir longshot-loader-audit.json")
    print("Audit du chargeur Longshot reussi ; gameplay encore non qualifie.", flush=True)
