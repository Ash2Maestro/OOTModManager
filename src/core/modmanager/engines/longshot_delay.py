"""Change the clock adapter's data setting in a matching installed build."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import struct

from modmanager.formats import Nso, Record
from modmanager.state import REPORT, load_prepared
from modmanager.storage import digest, inventory, no_links, write_json


def set_delay(workspace: Path, milliseconds: int, mark_installed=False):
    if not 40 <= milliseconds <= 500:
        raise ValueError("Delai attendu entre 40 et 500 ms")
    workspace = workspace.resolve()
    report = load_prepared(workspace)
    report_before = (workspace / REPORT).read_bytes()
    adapters = report.get("native_adapters", [])
    if len(adapters) != 1 or adapters[0].get("revision") not in (2, 3):
        raise ValueError("La revision reglable doit d'abord etre preparee et compilee")
    adapter = adapters[0]
    game = Path(report["game_dir"])
    image = game / "image.bin"
    exe = game / "bin/longshot.exe"
    marker = game / ".hmb-wheel-clock.json"
    for path in (game, image, exe, marker):
        no_links(path)
    if json.loads((game / ".hmb-owner.json").read_text())["workspace"] != str(workspace):
        raise ValueError("Cette installation appartient a un autre dossier de travail")
    if not marker.exists() and not mark_installed:
        raise ValueError("Une premiere compilation de la revision reglable est necessaire (-Build)")
    if mark_installed and not report["build_status"].startswith("built"):
        raise ValueError("Le build doit avoir reussi avant d'enregistrer son installation")
    image_base = report["audit"]["layout"][0]["base"]
    offset = adapter["runtime_config"] - image_base
    code_offset = adapter["cave"] - image_base
    with image.open("rb") as stream:
        stream.seek(code_offset)
        code = stream.read(adapter["code_size"])
        stream.seek(offset)
        before = stream.read(4)
    if hashlib.sha256(code).hexdigest() != adapter["code_sha256"] or len(before) != 4:
        raise ValueError("L'image installee ne contient pas cette revision de l'adaptation")
    exe_hash = digest(exe)
    identity = {"exe_sha256": exe_hash, "code_sha256": adapter["code_sha256"], "config_offset": offset}
    marker_before = marker.read_bytes() if marker.exists() else None
    if marker.exists() and not mark_installed and json.loads(marker.read_text()) != identity:
        raise ValueError("L'executable a change ; refaire une installation verifiee")
    module_path = workspace / "prepared/exefs/subsdk1"
    old_module = module_path.read_bytes()
    module = Nso(old_module)
    base = next(m["base"] for m in report["audit"]["layout"] if m["name"] == "subsdk1")
    value = struct.pack("<I", milliseconds)
    module.apply([Record(adapter["runtime_config"] - base, value)])
    try:
        with image.open("r+b") as stream:
            stream.seek(offset)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        module_path.write_bytes(module.encode())
        adapter["hold_ms"] = milliseconds
        report["inventory"]["prepared"] = inventory(workspace / "prepared")
        report["wheel_hold_ms_installed"] = milliseconds
        write_json(workspace / REPORT, report)
        write_json(marker, identity)
    except BaseException:
        with image.open("r+b") as stream:
            stream.seek(offset)
            stream.write(before)
        module_path.write_bytes(old_module)
        (workspace / REPORT).write_bytes(report_before)
        if marker_before is not None:
            marker.write_bytes(marker_before)
        elif marker.exists():
            marker.unlink()
        raise
    print("Delai regle a %d ms. Relancez le jeu ; aucune recompilation." % milliseconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--hold-ms", type=int, required=True)
    parser.add_argument("--mark-installed", action="store_true")
    args = parser.parse_args()
    try:
        set_delay(args.workspace, args.hold_ms, args.mark_installed)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")
