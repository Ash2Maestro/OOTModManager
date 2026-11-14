"""Execute the generated AArch64 gate, including the failing opening state."""
import struct
import unittest
from modmanager.wheel_input import CHECK, CONTINUE, BYPASS, GATE_OFFSET, opening_gate


class WheelOpeningTests(unittest.TestCase):
    def text(self):
        text = bytearray(0x1D000)
        struct.pack_into('<II', text, CHECK, 0x7100095F, 0x54FFFD01)
        return text

    def test_unknown_helper_is_rejected_without_mutation(self):
        text = self.text()
        text[CHECK] ^= 1
        before = bytes(text)
        with self.assertRaisesRegex(ValueError, 'refusée'):
            opening_gate(text, 0x80000000, 0x18000)
        self.assertEqual(bytes(text), before)

    def test_only_opening_and_open_states_keep_ownership(self):
        try:
            from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
            from unicorn.arm64_const import UC_ARM64_REG_X10, UC_ARM64_REG_PC
        except ImportError:
            self.skipTest('Run with Longshot compiler Python for AArch64 execution')
        base, cave = 0x80000000, 0x18000
        text = self.text()
        code = opening_gate(text, base, cave)
        text[cave + GATE_OFFSET:cave + GATE_OFFSET + len(code)] = code
        emu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        emu.mem_map(base, 0x20000)
        emu.mem_write(base, bytes(text))
        def stop_at_continuation(machine, address, size, user_data):
            if address in (base + CONTINUE, base + BYPASS):
                machine.emu_stop()
        emu.hook_add(UC_HOOK_CODE, stop_at_continuation)
        for state in (0, 1, 2, 3, 4, 255, 0xFFFFFFFF):
            emu.reg_write(UC_ARM64_REG_X10, state)
            # Stop before executing either original continuation.
            emu.emu_start(base + CHECK, base + 0x20000, count=32)
            expected = CONTINUE if state in (1, 2) else BYPASS
            self.assertEqual(emu.reg_read(UC_ARM64_REG_PC), base + expected, state)
            self.assertEqual(emu.reg_read(UC_ARM64_REG_X10), state)
