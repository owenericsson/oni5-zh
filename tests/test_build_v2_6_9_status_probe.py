import unittest

from scripts import build_v2_6_8_menu as previous
from scripts import build_v2_6_9_status_probe as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET


class Cpu:
    """Execute the patched entry, native bank dispatcher, and VRAM copy loops."""

    def __init__(self, rom, upper=0):
        self.rom = rom
        self.upper = upper
        self.memory = bytearray(0x10000)
        self.memory[0xFFA9] = 2
        self.memory[0xFF40] = 0xC7
        self.memory[0x9800:0xA000] = b"\xCD" * 0x800
        self.memory[0xFF90], self.memory[0xFF91] = 1, 0
        self.memory[0xD2E3], self.memory[0xD2E4] = 2, 1
        self.a, self.f, self.b, self.c = 0x5A, 0x70, 0x19, 0x38
        self.d, self.e, self.h, self.l = 0xCF, 0x21, 0xD3, 0x97
        self.sp, self.pc, self.bank, self.ime = 0xD000, 0, 2, True
        self.calls = []
        self.native_states = []
        self.writes = []
        self.interrupt_changes = []

    def read(self, address):
        if address < 0x4000:
            return self.rom[self.upper * 0x4000 + address]
        if address < 0x8000:
            return self.rom[(self.bank + self.upper) * 0x4000 + address - 0x4000]
        return self.memory[address]

    def write(self, address, value):
        if address == 0x2100:
            self.bank = value
        else:
            self.memory[address] = value
            if 0x8000 <= address < 0xA000:
                self.writes.append((address, value, self.ime))

    def byte(self):
        value = self.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return value

    def word(self):
        return self.byte() | self.byte() << 8

    def push(self, value):
        self.sp = (self.sp - 2) & 0xFFFF
        self.memory[self.sp:self.sp + 2] = value.to_bytes(2, "little")

    def pop(self):
        value = self.memory[self.sp] | self.memory[self.sp + 1] << 8
        self.sp = (self.sp + 2) & 0xFFFF
        return value

    def registers(self):
        return self.a, self.f, self.b, self.c, self.d, self.e, self.h, self.l

    def call_entry(self):
        self.pc = 0x4B26
        self.run(0x4B2E)

    def call_exit(self, address):
        self.pc = address
        self.run(address + 3)

    def run(self, stop):
        for _ in range(500000):
            if self.pc == stop and self.bank == 2:
                return
            if self.pc in (0x1934, 0x1A89) or (self.bank == 2 and self.pc in (0x7A30, 0x7ACB)):
                self.calls.append((self.bank, self.pc, self.registers()))
                self.native_states.append((self.pc, self.memory[0xFF40], self.ime))
                self.a, self.f, self.b, self.c = 0x41, 0xB0, 0x61, 0x72
                self.d, self.e, self.h, self.l = 0x83, 0x94, 0xA5, 0xB6
                self.pc = self.pop()
                continue
            op = self.byte()
            if op == 0x00:
                pass
            elif op in (0xC5, 0xD5, 0xE5, 0xF5):
                self.push({0xC5: self.b << 8 | self.c, 0xD5: self.d << 8 | self.e,
                           0xE5: self.h << 8 | self.l, 0xF5: self.a << 8 | self.f}[op])
            elif op in (0xC1, 0xD1, 0xE1, 0xF1):
                value = self.pop()
                if op == 0xC1:
                    self.b, self.c = value >> 8, value & 0xFF
                elif op == 0xD1:
                    self.d, self.e = value >> 8, value & 0xFF
                elif op == 0xE1:
                    self.h, self.l = value >> 8, value & 0xFF
                else:
                    self.a, self.f = value >> 8, value & 0xF0
            elif op in (0x21, 0x11, 0x01):
                value = self.word()
                if op == 0x21:
                    self.h, self.l = value >> 8, value & 0xFF
                elif op == 0x11:
                    self.d, self.e = value >> 8, value & 0xFF
                else:
                    self.b, self.c = value >> 8, value & 0xFF
            elif op in (0x3E, 0x2E, 0x16, 0x26, 0x06, 0x0E, 0xF0, 0xE0):
                value = self.byte()
                if op == 0x3E:
                    self.a = value
                elif op == 0x2E:
                    self.l = value
                elif op == 0x16:
                    self.d = value
                elif op == 0x26:
                    self.h = value
                elif op == 0x06:
                    self.b = value
                elif op == 0x0E:
                    self.c = value
                elif op == 0xF0:
                    self.a = self.read(0xFF00 + value)
                else:
                    self.write(0xFF00 + value, self.a)
            elif op == 0xFA:
                self.a = self.read(self.word())
            elif op == 0xEA:
                self.write(self.word(), self.a)
            elif op == 0xF8:
                displacement = self.byte()
                displacement = displacement if displacement < 128 else displacement - 256
                value = (self.sp + displacement) & 0xFFFF
                self.h, self.l = value >> 8, value & 0xFF
                self.f = 0
            elif op == 0x2A:
                value = self.h << 8 | self.l
                self.a = self.read(value)
                value = (value + 1) & 0xFFFF
                self.h, self.l = value >> 8, value & 0xFF
            elif op == 0x7E:
                self.a = self.read(self.h << 8 | self.l)
            elif op == 0x1A:
                self.a = self.read(self.d << 8 | self.e)
            elif op == 0x22:
                value = self.h << 8 | self.l
                self.write(value, self.a)
                value = (value + 1) & 0xFFFF
                self.h, self.l = value >> 8, value & 0xFF
            elif op in (0x12, 0x77):
                self.write(self.d << 8 | self.e if op == 0x12 else self.h << 8 | self.l, self.a)
            elif op == 0x13:
                value = ((self.d << 8 | self.e) + 1) & 0xFFFF
                self.d, self.e = value >> 8, value & 0xFF
            elif op == 0x0B:
                value = ((self.b << 8 | self.c) - 1) & 0xFFFF
                self.b, self.c = value >> 8, value & 0xFF
            elif op in (0x14, 0x15, 0x1C, 0x2C, 0x05, 0x0D, 0x3D):
                value = {0x14: self.d, 0x15: self.d, 0x1C: self.e,
                         0x2C: self.l, 0x05: self.b, 0x0D: self.c, 0x3D: self.a}[op]
                decrement = op in (0x15, 0x05, 0x0D, 0x3D)
                result = (value + (-1 if decrement else 1)) & 0xFF
                self.f = (self.f & 0x10) | (0x80 if result == 0 else 0)
                if decrement:
                    self.f |= 0x40 | (0x20 if value & 15 == 0 else 0)
                else:
                    self.f |= 0x20 if value & 15 == 15 else 0
                if op == 0x1C:
                    self.e = result
                elif op == 0x2C:
                    self.l = result
                elif op == 0x05:
                    self.b = result
                elif op == 0x0D:
                    self.c = result
                elif op == 0x3D:
                    self.a = result
                else:
                    self.d = result
            elif op in (0x7A, 0x7B, 0x7C, 0x7D, 0x78, 0x79):
                self.a = {0x7A: self.d, 0x7B: self.e, 0x7C: self.h,
                          0x7D: self.l, 0x78: self.b, 0x79: self.c}[op]
            elif op in (0x5F, 0x57, 0x4F, 0x47, 0x67, 0x54, 0x5D, 0x6F, 0x62, 0x6B):
                if op == 0x5F:
                    self.e = self.a
                elif op == 0x57:
                    self.d = self.a
                elif op == 0x4F:
                    self.c = self.a
                elif op == 0x47:
                    self.b = self.a
                elif op == 0x67:
                    self.h = self.a
                elif op == 0x54:
                    self.d = self.h
                elif op == 0x6F:
                    self.l = self.a
                elif op == 0x62:
                    self.h = self.d
                elif op == 0x6B:
                    self.l = self.e
                else:
                    self.e = self.l
            elif op in (0x81, 0x82, 0x83, 0xC6):
                value = self.byte() if op == 0xC6 else self.c if op == 0x81 else self.d if op == 0x82 else self.e
                result = self.a + value
                self.f = ((0x80 if result & 0xFF == 0 else 0)
                          | (0x20 if (self.a & 15) + (value & 15) > 15 else 0)
                          | (0x10 if result > 255 else 0))
                self.a = result & 0xFF
            elif op in (0x09, 0x19, 0x29):
                right = (self.b << 8 | self.c) if op == 0x09 else (
                    (self.d << 8 | self.e) if op == 0x19 else (self.h << 8 | self.l))
                value = (self.h << 8 | self.l) + right
                self.h, self.l = value >> 8 & 0xFF, value & 0xFF
            elif op == 0xCB:
                sub = self.byte()
                if sub == 0x27:
                    value, carry = self.a, self.a >> 7
                    self.a = value << 1 & 0xFF
                    result = self.a
                elif sub == 0x3C:
                    carry = self.h & 1
                    self.h >>= 1
                    result = self.h
                elif sub == 0x1D:
                    carry = self.l & 1
                    self.l = self.l >> 1 | (0x80 if self.f & 0x10 else 0)
                    result = self.l
                elif sub == 0x3F:
                    carry = self.a & 1
                    self.a >>= 1
                    result = self.a
                else:
                    raise AssertionError(f"unknown CB opcode ${sub:02X}")
                self.f = (0x80 if result == 0 else 0) | (0x10 if carry else 0)
            elif op == 0xFE:
                value = self.byte()
                self.f = (0x40 | (0x80 if self.a == value else 0)
                          | (0x20 if self.a & 15 < value & 15 else 0)
                          | (0x10 if self.a < value else 0))
            elif op == 0xE6:
                self.a &= self.byte()
                self.f = 0x20 | (0x80 if self.a == 0 else 0)
            elif op == 0xD6:
                value = self.byte()
                before = self.a
                self.a = (self.a - value) & 0xFF
                self.f = (0x40 | (0x80 if self.a == 0 else 0)
                          | (0x20 if (before & 15) < (value & 15) else 0)
                          | (0x10 if before < value else 0))
            elif op in (0xB0, 0xB1, 0xB7, 0xAF):
                self.a = (self.a | self.b if op == 0xB0 else self.a | self.c if op == 0xB1
                          else 0 if op == 0xAF else self.a)
                self.f = 0x80 if self.a == 0 else 0
            elif op in (0xC3, 0xCA, 0xC2, 0xDA, 0xD2, 0xCD):
                address = self.word()
                if op == 0xCD:
                    self.push(self.pc)
                if (op in (0xC3, 0xCD) or op == 0xCA and self.f & 0x80
                        or op == 0xC2 and not self.f & 0x80 or op == 0xDA and self.f & 0x10
                        or op == 0xD2 and not self.f & 0x10):
                    self.pc = address
            elif op in (0x20, 0x28):
                displacement = self.byte()
                if bool(self.f & 0x80) == (op == 0x28):
                    self.pc = (self.pc + (displacement if displacement < 128 else displacement - 256)) & 0xFFFF
            elif op == 0xEF:
                self.push(self.pc)
                self.pc = 0x28
            elif op == 0xC9:
                self.pc = self.pop()
            elif op in (0xF3, 0xFB):
                self.ime = op == 0xFB
                self.interrupt_changes.append((self.ime, self.bank, self.memory[0xFFA9]))
            else:
                raise AssertionError(f"unknown opcode ${op:02X} at ${self.bank:02X}:${self.pc - 1:04X}")
        raise AssertionError("machine code failed to return")


class StatusProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = previous.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, cls.version = build.build()
        cls.labels, cls.patterns = build.compile_labels(cls.parent)

    def test_patch_and_mirror(self):
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        spans = ((build.STATUS_CALL, 8), (build.EXIT_WRAPPER, 10),
                 (build.COMPONENT_START, len(build.build_components(self.labels, self.patterns)[0])),
                 (0x8B7B, 3), (0x8B96, 3))
        allowed = {0x14E, 0x14F}
        for offset, length in spans:
            self.assertEqual(self.rom[offset:offset + length],
                             self.rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + length])
            allowed.update(range(offset, offset + length))
            allowed.update(range(offset + MBC1_MIRROR_OFFSET, offset + MBC1_MIRROR_OFFSET + length))
        self.assertTrue(all(index in allowed for index, (old, new) in enumerate(zip(self.parent, self.rom))
                            if old != new))

    def test_entry_reentry_and_both_exits(self):
        for upper in (0, 0x20):
            for exit_address, target in ((0x4B7B, 0x7A30), (0x4B96, 0x7ACB)):
                with self.subTest(upper=upper, exit=hex(exit_address)):
                    cpu = Cpu(self.rom, upper)
                    original = bytes((i * 13 + 19) & 0xFF for i in range(len(self.patterns)))
                    cpu.memory[0x9200:0x9360] = original
                    initial = cpu.registers()
                    for column, row, tiles, voiced in self.labels:
                        for index in range(len(tiles)):
                            x, y = (column + index + 4) & 31, row & 31
                            cpu.memory[0x9800 + y * 32 + x] = 0xB8 if index in voiced else 0x42
                    cpu.call_entry()
                    self.assertEqual(cpu.calls[0], (1, 0x1934, initial))
                    self.assertEqual(cpu.registers(), (0x41, 0xB0, 0x61, 0x72, 0x83, 0x94, 0xA5, 0xB6))
                    self.assertEqual((cpu.sp, cpu.bank, cpu.memory[0xFFA9], cpu.ime), (0xD000, 2, 2, True))
                    self.assertEqual(cpu.memory[0xC4F2], build.MARKER)
                    self.assertEqual(cpu.memory[0x9C00:0x9D60], original)
                    self.assertEqual(cpu.memory[0x9200:0x9360], self.patterns)
                    expected = {}
                    for column, row, tiles, voiced in self.labels:
                        for index, tile in enumerate(tiles):
                            x, y = (column + index + 4) & 31, (row + 1) & 31
                            expected[0x9800 + y * 32 + x] = tile
                            expected[0x9800 + ((y - 1) & 31) * 32 + x] = 0xCD if index in voiced else 0x42
                    for address, tile in expected.items():
                        self.assertEqual(cpu.memory[address], tile)
                    map_writes = {address for address, _, _ in cpu.writes if 0x9800 <= address < 0x9C00}
                    self.assertEqual(map_writes, {
                        address for address in expected
                        if expected[address] != 0x42
                    })
                    cpu.call_entry()
                    self.assertEqual(cpu.memory[0x9C00:0x9D60], original)
                    before_exit = cpu.registers()
                    cpu.call_exit(exit_address)
                    self.assertEqual(cpu.calls[-1], (2, target, before_exit))
                    self.assertEqual(cpu.registers(), (0x41, 0xB0, 0x61, 0x72, 0x83, 0x94, 0xA5, 0xB6))
                    self.assertEqual(cpu.memory[0x9200:0x9360], original)
                    self.assertEqual(cpu.memory[0x9C00:0x9D60], b"\xCD" * len(original))
                    self.assertEqual((cpu.sp, cpu.bank, cpu.memory[0xFFA9], cpu.memory[0xC4F2], cpu.ime),
                                     (0xD000, 2, 2, 0, True))
                    self.assertTrue(all(not ime for address, _, ime in cpu.writes
                                        if 0x9200 <= address < 0x9360 or 0x9C00 <= address < 0x9D60))
                    self.assertTrue(all(bank == 2 and selected == 2
                                        for enabled, bank, selected in cpu.interrupt_changes if enabled))

    def test_guard_failures_do_not_modify_candidates(self):
        for case in ("scratch", "map", "display", "marker"):
            with self.subTest(case=case):
                cpu = Cpu(self.rom)
                cpu.memory[0x9200:0x9360] = bytes((i & 0xFF for i in range(0x160)))
                if case == "scratch":
                    cpu.memory[0x9C99] = 0x42
                elif case == "map":
                    cpu.memory[0x99FF] = 0x20
                elif case == "display":
                    cpu.memory[0xFF40] = 0xD7
                else:
                    cpu.memory[0xC4F2] = 0x80
                original = cpu.memory[0x9200:0x9360], cpu.memory[0x9C00:0x9D60], cpu.memory[0xC4F2]
                cpu.call_entry()
                self.assertEqual((cpu.memory[0x9200:0x9360], cpu.memory[0x9C00:0x9D60],
                                  cpu.memory[0xC4F2]), original)
                self.assertEqual(cpu.memory[0x9850], 0xCB)
                self.assertEqual((cpu.sp, cpu.bank, cpu.memory[0xFFA9], cpu.ime), (0xD000, 2, 2, True))
                cpu.call_exit(0x4B7B)
                self.assertEqual((cpu.memory[0x9200:0x9360], cpu.memory[0x9C00:0x9D60],
                                  cpu.memory[0xC4F2]), original)


if __name__ == "__main__":
    unittest.main()
