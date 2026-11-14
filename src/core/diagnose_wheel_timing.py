"""Replay the shipped wheel input helper locally, without launching the game."""
from pathlib import Path
import argparse
import struct

from modmanager.formats import Nso


def replay(exefs: Path, stride: int, fps=60, module_path=None, tap_ms=None):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X30, UC_ARM64_REG_SP
    # Exact Item Wheel 0.1.7 profile, validated against the source build below.
    module = Nso((module_path or exefs / "subsdk1").read_bytes())
    base, entry, cache = 0x84FA5000, 0x84FA58CC, 0x84EC1000
    state, stack, stop = 0x90000000, 0x91000000, 0x92000000
    emu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for address, size in [(base, 0x80000), (cache, 0x4000), (0x84EA4000, 0x1000),
                          (state, 0x1000), (stack, 0x10000), (stop, 0x1000), (0x8518B000, 0x1000)]:
        emu.mem_map(address, size)
    for segment in module.segments:
        emu.mem_write(base + segment.memory, segment.data)
    clock = {"tick": 0}

    def tick_call(uc, address, size, user_data):
        if address in (0x8518B370, 0x8518B3A0):
            uc.reg_write(UC_ARM64_REG_X0, clock["tick"] if address == 0x8518B370 else 31250000)
            from unicorn.arm64_const import UC_ARM64_REG_PC
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))

    emu.hook_add(UC_HOOK_CODE, tick_call, begin=0x8518B370, end=0x8518B3A0)
    for frame in range(1, 3 if tap_ms is not None else 601):
        clock["tick"] = (0 if frame == 1 else int(tap_ms * 31250)) if tap_ms is not None else frame * 31250000 // fps
        emu.mem_write(cache + 124, struct.pack("<I", frame))
        emu.mem_write(state, struct.pack("<5Q", frame * stride, 0 if tap_ms is not None and frame == 2 else 0x80, 0, 0, 1))
        emu.reg_write(UC_ARM64_REG_X0, state)
        emu.reg_write(UC_ARM64_REG_X1, 1)
        emu.reg_write(UC_ARM64_REG_X30, stop)
        emu.reg_write(UC_ARM64_REG_SP, stack + 0xFFF0)
        emu.emu_start(entry, stop, count=10000)
        if struct.unpack("<Q", emu.mem_read(state, 8))[0] != frame * stride:
            raise ValueError("L'adaptation a modifie le compteur HID visible par le jeu")
        if tap_ms is not None and frame == 2:
            return struct.unpack("<I", emu.mem_read(cache + 112, 4))[0]
        buttons = struct.unpack("<Q", emu.mem_read(state + 8, 8))[0]
        if buttons & 0x80:
            return frame
    raise ValueError("R jamais transmis dans les 600 lectures rejouees")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exefs", type=Path, required=True)
    parser.add_argument("--verify-clock", action="store_true")
    parser.add_argument("--hold-ms", type=int, default=100)
    args = parser.parse_args()
    if args.verify_clock:
        for fps in (30, 60, 120, 240):
            frame = replay(args.exefs, 1, fps)
            elapsed = (frame - 1) / fps
            assert args.hold_ms / 1000 - 0.002 < elapsed <= args.hold_ms / 1000 + 0.002 + 1 / fps, (fps, frame, elapsed)
            assert replay(args.exefs, 8, fps) == frame
            print("%d lectures/s : maintien transmis apres %.3f s ; compteur HID preserve." % (fps, elapsed))
        assert replay(args.exefs, 1, tap_ms=args.hold_ms - 5) == 1
        assert replay(args.exefs, 1, tap_ms=args.hold_ms + 5) == 2
        print("Appui court / maintien : classification preservee autour du seuil.")
    else:
        frame = replay(args.exefs, 1)
        print("Compteur +1 par lecture : R transmis a la lecture %d (%.2f s a 60 lectures/s)." % (frame, frame / 60))
        print("Compteur +8 par lecture : R transmis a la lecture %d." % replay(args.exefs, 8))
