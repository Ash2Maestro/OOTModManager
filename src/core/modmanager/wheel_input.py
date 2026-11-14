"""Version-specific Item Wheel 0.1.7 opening-state correction.

The old helper exempts only a fully open selector from heartbeat expiry.
Opening also pauses gameplay, so accept states 1 and 2, as upstream now does.
All other context, binding and ocarina checks remain in the original helper.
"""
import struct

REVISION = 3
CHECK = 0x968
CONTINUE = 0x970
BYPASS = 0x90C
GATE_OFFSET = 0x1000


def _branch(source, target, condition=None):
    delta = target - source
    bits = 26 if condition is None else 19
    if delta % 4 or not -(1 << (bits + 1)) <= delta < (1 << (bits + 1)):
        raise ValueError("Branchement de correction hors limites")
    immediate = (delta // 4) & ((1 << bits) - 1)
    return struct.pack("<I", (0x14000000 | immediate) if condition is None
                       else (0x54000000 | (immediate << 5) | condition))


def opening_gate(text, base, cave):
    """Patch the audited comparison and return code to append at cave+0x1000."""
    expected = struct.pack("<II", 0x7100095F, 0x54FFFD01)
    if text[CHECK:CHECK + 8] != expected:
        raise ValueError("Helper Item Wheel différent : correction d'ouverture refusée")
    gate = base + cave + GATE_OFFSET
    code = (struct.pack("<I", 0x7100055F)  # cmp w10, #1
            + _branch(gate + 4, base + CONTINUE, 0)  # opening
            + struct.pack("<I", 0x7100095F)  # cmp w10, #2
            + _branch(gate + 12, base + BYPASS, 1)
            + _branch(gate + 16, base + CONTINUE))
    text[CHECK:CHECK + 8] = _branch(base + CHECK, gate) + struct.pack("<I", 0xD503201F)
    return code
