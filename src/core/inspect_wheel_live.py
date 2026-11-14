"""Read-only inspection of the wheel's private state in a running Longshot."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import struct
import time

HOST_BASE = 0x100000000000
CACHE = 0x84EC1000


def inspect(expected: Path, seconds: float, probe_mode=False):
    kernel = c.WinDLL("kernel32", use_last_error=True)
    class Entry(c.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                    ("heap", c.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                    ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD), ("exe", w.WCHAR * 260)]
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, c.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [w.HANDLE, c.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
    kernel.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    handle, pid = None, None
    entry = Entry()
    entry.size = c.sizeof(entry)
    try:
        okay = kernel.Process32FirstW(snapshot, c.byref(entry))
        while okay:
            if entry.exe.lower() == "longshot.exe":
                candidate = kernel.OpenProcess(0x1010, False, entry.pid)  # query + read only
                if candidate:
                    name, length = c.create_unicode_buffer(32768), w.DWORD(32768)
                    if kernel.QueryFullProcessImageNameW(candidate, 0, name, c.byref(length)):
                        if name.value.casefold() == str(expected.resolve()).casefold():
                            handle, pid = candidate, entry.pid
                            break
                    kernel.CloseHandle(candidate)
            okay = kernel.Process32NextW(snapshot, c.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    if not handle:
        raise ValueError("Processus cible absent ou inaccessible : " + str(expected))

    def read(address, size):
        if not 0 <= address < 0x8000000000:
            raise ValueError("Adresse invite hors limites")
        buf, got = c.create_string_buffer(size), c.c_size_t()
        if not kernel.ReadProcessMemory(handle, c.c_void_p(HOST_BASE + address), buf, size, c.byref(got)):
            raise c.WinError(c.get_last_error())
        if got.value != size:
            raise ValueError("Lecture incomplete")
        return buf.raw

    def state():
        raw = read(CACHE, 144)
        q = lambda off: struct.unpack_from("<Q", raw, off)[0]
        u = lambda off: struct.unpack_from("<I", raw, off)[0]
        result = {"pid": pid, "list": hex(q(16)), "binding_generation": u(32),
                  "bound_items": u(36), "controller": hex(q(48)), "held": u(68),
                  "press_sample": q(96), "event": u(112), "remembered": u(116),
                  "explicit_bypass": u(120), "heartbeat": u(124), "seen_heartbeat": u(128),
                  "stale_polls": u(132), "last_bypass": u(136)}
        if q(48):
            controller = read(q(48), 0x80)
            owner, screen = struct.unpack_from("<QQ", controller, 0x18)[1], struct.unpack_from("<Q", controller, 0x18)[0]
            result["controller_items"] = struct.unpack_from("<I", controller, 0x78)[0]
            result["controller_list_matches"] = struct.unpack_from("<Q", controller, 0x68)[0] == q(16)
            if owner:
                result["owner_state"] = read(owner + 0x3A, 1)[0]
            if screen:
                result["screen_state"] = read(screen + 0x1A5, 2).hex()
        return result
    def mode_from_snapshot():
        # Execute ARM64 only in a separate emulator; all writes stay in that emulator.
        # Missing pages are copied read-only from the game. No remote thread or code injection.
        from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_UNMAPPED, UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_X0, UC_ARM64_REG_X30, UC_ARM64_REG_SP
        emu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        stack, stop = 0x7000000000, 0x7000010000
        emu.mem_map(stack, 0x10000)
        emu.mem_map(stop, 0x1000)
        pages = set()

        def missing(uc, access, address, size, value, data):
            page = address & ~0xFFF
            if page not in pages:
                raw = read(page, 0x1000)
                uc.mem_map(page, 0x1000)
                uc.mem_write(page, raw)
                pages.add(page)
            return True

        emu.hook_add(UC_HOOK_MEM_UNMAPPED, missing)
        def pointer_auth_return(uc, address, size, data):
            word = struct.unpack("<I", uc.mem_read(address, 4))[0]
            if word in (0xD65F0BFF, 0xD65F0FFF):  # RETAA/RETAB, as Longshot's lifter treats them
                uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_X30))
        emu.hook_add(UC_HOOK_CODE, pointer_auth_return)
        emu.reg_write(UC_ARM64_REG_SP, stack + 0xFFF0)
        emu.reg_write(UC_ARM64_REG_X30, stop)
        try:
            emu.emu_start(0x84FA5A90, stop, count=100000)
        except UcError as error:
            raise ValueError("Sonde interrompue a %#x : %s" % (emu.reg_read(UC_ARM64_REG_PC), error)) from error
        if emu.reg_read(UC_ARM64_REG_PC) != stop:
            raise ValueError("Sonde de mode non terminee dans sa limite d'instructions")
        mode = emu.reg_read(UC_ARM64_REG_X0)
        return {"value": mode, "name": {0: "Right", 1: "Left", 2: "Both"}.get(mode, "unknown"),
                "pages_read": len(pages), "writes_to_game": False}
    try:
        first = state()
        time.sleep(seconds)
        second = state()
        result = {"first": first, "second": second,
                  "heartbeat_delta": second["heartbeat"] - first["heartbeat"], "read_only": True}
        if probe_mode:
            result["bumper_mode"] = mode_from_snapshot()
        return result
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--probe-mode", action="store_true")
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.seconds, args.probe_mode), indent=2))
