"""Install the Item Wheel 0.1.7 clock adapter before recompilation."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import subprocess
import sys

from modmanager.formats import Nso, Record, branch_target
from modmanager.storage import digest, inventory, write_json
from modmanager.state import REPORT, load_prepared
from modmanager.engines import get_engine
from modmanager.wheel_input import REVISION, GATE_OFFSET, opening_gate

BASE = 0x84FA5000
ENTRY = 0x8CC
CAVE = 0x18000
TRAMPOLINE = 0x1C000
TICK = 0x8518B370
FREQUENCY = 0x8518B3A0
CONFIG = 0x1E100  # unused data-page padding, before the module's BSS symbols


def branch(source, target):
    delta = target - source
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError("Branchement d'adaptation hors limites")
    return struct.pack("<I", 0x14000000 | ((delta // 4) & 0x3FFFFFF))


def apply(workspace: Path, longshot: Path, hold_ms=100):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    workspace, longshot = workspace.resolve(), longshot.resolve()
    report = load_prepared(workspace)
    if not 40 <= hold_ms <= 500:
        raise ValueError("Le delai doit etre compris entre 40 et 500 ms")
    if report["variant"] != "item-wheel" or report["manifest"]["version"] != "0.1.7":
        raise ValueError("Profil limite a Item Wheel 0.1.7")
    if report.get("native_adapters"):
        if [a.get("name") for a in report["native_adapters"]] != ["wheel-clock-ms"]:
            raise ValueError("Une autre adaptation est deja installee")
    get_engine("longshot").validate_tools(longshot)
    path = workspace / "prepared/exefs/subsdk1"
    work = workspace / "native-adapter"
    work.mkdir(exist_ok=True)
    backup = work / "original-subsdk1.nso"
    raw = backup.read_bytes() if backup.exists() else path.read_bytes()
    module = Nso(raw)
    reference = Nso((workspace / "addon/exefs/subsdk1").read_bytes())
    if module.segments != reference.segments or module.end != reference.end:
        raise ValueError("La sauvegarde originale ne correspond pas a l'addon verifie")
    text = bytearray(module.segments[0].data)
    if len(text) != 0x1D000 or any(text[CAVE:TRAMPOLINE + 8]):
        raise ValueError("Emplacement libre du profil absent")
    instructions = list(Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(bytes(text[ENTRY:ENTRY + 4]), BASE + ENTRY))
    if len(instructions) != 1 or instructions[0].mnemonic != "cbz" or not instructions[0].op_str.startswith("x0,"):
        raise ValueError("Prologue du helper different du profil attendu")
    first_word = struct.unpack_from("<I", text, ENTRY)[0]
    first_target = branch_target(first_word, BASE + ENTRY)
    delta = first_target - (BASE + TRAMPOLINE)
    if delta % 4 or not -(1 << 20) <= delta < (1 << 20):
        raise ValueError("Relocalisation du CBZ hors limites")
    relocated_first = struct.pack("<I", (first_word & ~(0x7FFFF << 5)) | (((delta // 4) & 0x7FFFF) << 5))
    # Validate canonical HLE entry addresses against the already-generated metadata.
    hooks_path = workspace / "build-work/sa/gen/a64_hooks.c"
    hooks = hooks_path.read_text() if hooks_path.exists() else ""
    audited = workspace / "longshot-loader-audit.json"
    exports = json.loads(audited.read_text()).get("clock_exports", {}) if audited.exists() else {}
    for address, symbol in [(TICK, "_ZN2nn2os13GetSystemTickEv"),
                             (FREQUENCY, "_ZN2nn2os22GetSystemTickFrequencyEv")]:
        if ("void f_%08x(Ctx *A64_NOESC c) { TAILCALL(imp_%s); }" % (address, symbol)) not in hooks and exports.get(symbol) != address:
            raise ValueError("Liaison d'horloge HLE differente")
    source = Path(__file__).resolve().parents[2] / "adapters/wheel_clock.c"
    linker = work / "clock.ld"
    linker.write_text("ENTRY(hmb_wheel_clock)\nSECTIONS { . = %#x; .text : { *(.text.hmb_wheel_clock) *(.text*) *(.rodata*) } "
                      "/DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) } }\n"
                      "hmb_original_raw = %#x; hmb_get_tick = %#x; hmb_get_tick_frequency = %#x; hmb_hold_ms = %#x;\n" %
                      (BASE + CAVE, BASE + TRAMPOLINE, TICK, FREQUENCY, BASE + CONFIG))
    tools = longshot / "llvm-mingw/bin"
    subprocess.run([str(tools / "clang.exe"), "--target=aarch64-none-elf", "-Oz", "-ffreestanding",
                    "-fno-stack-protector", "-fno-builtin", "-ffunction-sections", "-mbranch-protection=none",
                    "-c", str(source), "-o", str(work / "clock.o")], check=True)
    subprocess.run([str(tools / "ld.lld.exe"), "-T", str(linker), str(work / "clock.o"),
                    "-o", str(work / "clock.elf")], check=True)
    subprocess.run([str(tools / "llvm-objcopy.exe"), "-O", "binary", "--only-section=.text",
                    str(work / "clock.elf"), str(work / "clock.bin")], check=True)
    code = (work / "clock.bin").read_bytes()
    if len(code) > 0x1000:
        raise ValueError("Adaptation trop grande")
    gate = opening_gate(text, BASE, CAVE)
    code = code.ljust(GATE_OFFSET, b'\0') + gate
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    text[TRAMPOLINE:TRAMPOLINE + 4] = relocated_first
    text[TRAMPOLINE + 4:TRAMPOLINE + 8] = branch(BASE + TRAMPOLINE + 4, BASE + ENTRY + 4)
    text[CAVE:CAVE + len(code)] = code
    text[ENTRY:ENTRY + 4] = branch(BASE + ENTRY, BASE + CAVE)
    module.segments[0].data = bytes(text)
    module.apply([Record(CONFIG, struct.pack("<I", hold_ms))])
    path.write_bytes(module.encode())
    report["native_adapters"] = [{"name": "wheel-clock-ms", "source_sha256": digest(source),
                                   "code_sha256": hashlib.sha256(code).hexdigest(), "code_size": len(code),
                                   "entry": BASE + ENTRY, "cave": BASE + CAVE,
                                   "tick": TICK, "frequency": FREQUENCY,
                                   "revision": REVISION, "hold_ms": hold_ms,
                                   "runtime_config": BASE + CONFIG}]
    report["inventory"]["prepared"] = inventory(workspace / "prepared")
    report["prior_build_status"] = report["build_status"]
    report["build_status"] = "needs-rebuild"
    report["tools_path"] = str(longshot)
    report["build_python"] = str(sys.executable)
    write_json(workspace / REPORT, report)
    print("Adaptation d'horloge installee dans les modules prepares. Recompilation necessaire.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--tools", dest="tools_path", type=Path, required=True)
    parser.add_argument("--hold-ms", type=int, default=100)
    args = parser.parse_args()
    apply(args.workspace, args.tools_path, args.hold_ms)
