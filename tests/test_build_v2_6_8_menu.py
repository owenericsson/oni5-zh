import hashlib
import json
import unittest

from scripts import build_v2_6_8_menu as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, compile_menu_payloads
from scripts.build_opening_text_preview_patch import FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import verify_rom
from test_build_v2_6_6_dialogue import run_helper


def run_router(rom, memory, return_address, upper=0, zero=False):
    pc, sp = build.bank_cpu_address(build.ROUTER), 0xD000
    a, b, c, d, e, h, l = 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77
    memory[sp:sp + 2] = b"\xff\xff"
    memory[sp + 6:sp + 8] = return_address.to_bytes(2, "little")
    calls = []

    def byte():
        nonlocal pc
        value = rom[(0x10 + upper) * 0x4000 + pc - 0x4000]
        pc += 1
        return value

    def word():
        return byte() | byte() << 8

    def push(value):
        nonlocal sp
        sp -= 2
        memory[sp:sp + 2] = value.to_bytes(2, "little")

    def pop():
        nonlocal sp
        value = memory[sp] | memory[sp + 1] << 8
        sp += 2
        return value

    for _ in range(1000):
        op = byte()
        if op in (0xC5, 0xD5, 0xE5, 0xF5):
            push({0xC5: b << 8 | c, 0xD5: d << 8 | e, 0xE5: h << 8 | l,
                  0xF5: a << 8 | (0x80 if zero else 0)}[op])
        elif op in (0xC1, 0xD1, 0xE1, 0xF1):
            value = pop()
            if op == 0xC1:
                b, c = value >> 8, value & 0xFF
            elif op == 0xD1:
                d, e = value >> 8, value & 0xFF
            elif op == 0xE1:
                h, l = value >> 8, value & 0xFF
            else:
                a, zero = value >> 8, bool(value & 0x80)
        elif op == 0xF8:
            displacement = byte()
            address = (sp + (displacement if displacement < 128 else displacement - 256)) & 0xFFFF
            h, l = address >> 8, address & 0xFF
        elif op in (0x2A, 0x7E):
            address = h << 8 | l
            a = memory[address]
            if op == 0x2A:
                address = (address + 1) & 0xFFFF
                h, l = address >> 8, address & 0xFF
        elif op == 0xFA:
            a = memory[word()]
        elif op == 0xFE:
            zero = a == byte()
        elif op == 0x20:
            displacement = byte()
            if not zero:
                pc += displacement if displacement < 128 else displacement - 256
        elif op == 0xC2:
            address = word()
            if not zero:
                pc = address
        elif op == 0xC3:
            address = word()
            if address == build.OLD_ROUTER:
                return "legacy", (a, b, c, d, e, h, l), zero, sp, calls
            pc = address
        elif op == 0xCD:
            address = word()
            calls.append(address)
            if address == 0x0521:
                source, destination, length = h << 8 | l, d << 8 | e, b << 8 | c
                self_start = (0x10 + upper) * 0x4000 + source - 0x4000
                memory[destination:destination + length] = rom[self_start:self_start + length]
            else:
                push(pc)
                pc = address
        elif op in (0x21, 0x11, 0x01):
            value = word()
            if op == 0x21:
                h, l = value >> 8, value & 0xFF
            elif op == 0x11:
                d, e = value >> 8, value & 0xFF
            else:
                b, c = value >> 8, value & 0xFF
        elif op == 0x3E:
            a = byte()
        elif op == 0xAF:
            a, zero = 0, True
        elif op == 0xEA:
            memory[word()] = a
        elif op == 0xC9:
            pc = pop()
            if pc == 0xFFFF:
                return "return", (a, b, c, d, e, h, l), zero, sp, calls
        else:
            raise AssertionError(f"unexpected opcode ${op:02X} at ${pc - 1:04X}")
    raise AssertionError("router did not return")


def run_status_entry(rom, memory, upper=0):
    pc, sp, bank, ime = 0x49E0, 0xDFF9, 2, True
    a, f, b, c, d, e, h, l = 0, 0xC0, 0, 0, 0xCF, 0x21, 0xCF, 0x22
    memory[0xFFA9], memory[0xC4F2] = 2, 0x80

    def byte():
        nonlocal pc
        offset = pc if pc < 0x4000 else (bank + upper) * 0x4000 + pc - 0x4000
        value = rom[offset]
        pc += 1
        return value

    def word():
        return byte() | byte() << 8

    def push(value):
        nonlocal sp
        sp -= 2
        memory[sp:sp + 2] = value.to_bytes(2, "little")

    def pop():
        nonlocal sp
        value = memory[sp] | memory[sp + 1] << 8
        sp += 2
        return value

    for _ in range(1000):
        op = byte()
        if op == 0xEF:
            return (bank, ime, sp, a, f, b, c, d, e, h, l, memory[0xC4F2])
        if op in (0xC5, 0xD5, 0xE5, 0xF5):
            push({0xC5: b << 8 | c, 0xD5: d << 8 | e, 0xE5: h << 8 | l, 0xF5: a << 8 | f}[op])
        elif op in (0xC1, 0xD1, 0xE1, 0xF1):
            value = pop()
            if op == 0xC1:
                b, c = value >> 8, value & 0xFF
            elif op == 0xD1:
                d, e = value >> 8, value & 0xFF
            elif op == 0xE1:
                h, l = value >> 8, value & 0xFF
            else:
                a, f = value >> 8, value & 0xF0
        elif op == 0xF8:
            displacement = byte()
            address = (sp + (displacement if displacement < 128 else displacement - 256)) & 0xFFFF
            h, l, f = address >> 8, address & 0xFF, 0
        elif op in (0x2A, 0x7E):
            address = h << 8 | l
            a = memory[address]
            if op == 0x2A:
                address = (address + 1) & 0xFFFF
                h, l = address >> 8, address & 0xFF
        elif op == 0xFA:
            a = memory[word()]
        elif op == 0xF0:
            a = memory[0xFF00 + byte()]
        elif op == 0xFE:
            f = 0x80 if a == byte() else 0
        elif op in (0x20, 0x28):
            displacement = byte()
            if bool(f & 0x80) == (op == 0x28):
                pc += displacement if displacement < 128 else displacement - 256
        elif op == 0xC2:
            address = word()
            if not f & 0x80:
                pc = address
        elif op == 0xC3:
            pc = word()
        elif op == 0xCD:
            address = word()
            if address == 0x0521:
                source, destination, length = h << 8 | l, d << 8 | e, b << 8 | c
                offset = (bank + upper) * 0x4000 + source - 0x4000
                memory[destination:destination + length] = rom[offset:offset + length]
            else:
                push(pc)
                pc = address
        elif op in (0x21, 0x11, 0x01):
            value = word()
            if op == 0x21:
                h, l = value >> 8, value & 0xFF
            elif op == 0x11:
                d, e = value >> 8, value & 0xFF
            else:
                b, c = value >> 8, value & 0xFF
        elif op == 0x3E:
            a = byte()
        elif op == 0xAF:
            a, f = 0, 0x80
        elif op == 0xEA:
            address = word()
            if address == 0x2000:
                bank = a
            else:
                memory[address] = a
        elif op == 0xF3:
            ime = False
        elif op == 0xFB:
            ime = True
        elif op == 0xC9:
            pc = pop()
        else:
            raise AssertionError(f"unexpected opcode ${op:02X} at ${pc - 1:04X} in bank ${bank:02X}")
    raise AssertionError("status entry did not reach its original RST")


class StatusFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, _ = build.build()
        cls.font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
        manifest = json.loads((build.ROOT / "data/menu_text_manifest.json").read_text())
        asset = json.loads((build.ROOT / "data/menu_chinese_glyphs.json").read_text())
        _, cls.glyphs = compile_menu_payloads(SOURCE_ROM.read_bytes(), manifest, asset)

    def test_patch_is_limited_and_mirrored(self):
        self.assertEqual(hashlib.sha256(self.parent).hexdigest(), build.EXPECTED_PARENT_SHA256)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        self.assertTrue(verify_rom(self.rom).passed)
        self.assertEqual(self.rom[build.STATUS_WRAPPER:build.STATUS_WRAPPER + 16],
                         build.build_status_wrapper())
        self.assertEqual(self.rom[build.STATUS_WRAPPER + 5:build.STATUS_WRAPPER + 13],
                         build.OLD_STATUS_CODE)
        ranges = [(build.STATUS_HOOK, build.STATUS_HOOK + 8),
                  (build.STATUS_WRAPPER, build.STATUS_WRAPPER + len(build.build_status_wrapper())),
                  (0x40001, 0x40003), (build.ROUTER, build.ROUTER + len(build.build_router()))]
        ranges += [(start + MBC1_MIRROR_OFFSET, end + MBC1_MIRROR_OFFSET) for start, end in ranges]
        ranges.append((0x14E, 0x150))
        for offset, (old, new) in enumerate(zip(self.parent, self.rom)):
            if old != new:
                self.assertTrue(any(start <= offset < end for start, end in ranges),
                                f"unexpected change at ${offset:06X}")

    def test_status_entry_restores_menu_tiles_in_both_banks(self):
        return_address = 0x4000 + build.STATUS_WRAPPER - 0x8000 + 4
        for upper in (0, 0x20):
            for zero in (False, True):
                memory = bytearray(0x10000)
                memory[0x8800:0x8C00] = b"\xaa" * 0x400
                memory[0xC4F2] = 0x80
                result, registers, flag, sp, calls = run_router(self.rom, memory, return_address, upper, zero)
                self.assertEqual((result, registers, flag, sp), ("return", (2, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77),
                                                                 zero, 0xD002))
                self.assertEqual((memory[0xC4F2], calls.count(0x0521)), (0, len(self.glyphs)))
                for glyph in self.glyphs:
                    index = (glyph.tile - 0x80) * 16
                    self.assertEqual(memory[0x8800 + index:0x8810 + index], self.font[index:index + 16])

    def test_status_entry_preserves_bank_registers_and_original_stack(self):
        for upper in (0, 0x20):
            memory = bytearray(0x10000)
            memory[0x8800:0x8C00] = b"\xaa" * 0x400
            result = run_status_entry(self.rom, memory, upper)
            self.assertEqual(result, (2, True, 0xDFF5, 1, 0xC0, 0, 0, 0xCF, 0x21, 0x20, 0x56, 0))
            self.assertEqual(memory[0xDFF5:0xDFF9], bytes.fromhex("22 CF C0 00"))
            self.assertEqual(memory[0xFFA9], 2)
            for glyph in self.glyphs:
                index = (glyph.tile - 0x80) * 16
                self.assertEqual(memory[0x8800 + index:0x8810 + index], self.font[index:index + 16])

    def test_returning_to_main_menu_reloads_chinese_glyphs(self):
        memory = bytearray(0x10000)
        run_status_entry(self.rom, memory)
        self.assertEqual(memory[0xC4F2], 0)
        result, _, banks, _ = run_helper(self.rom, 0x42500, memory)
        self.assertEqual((result, banks, memory[0xC4F2]), ("return", [], 0x80))
        for glyph in self.glyphs:
            address = 0x8800 + (glyph.tile - 0x80) * 16
            self.assertEqual(memory[address:address + 16], glyph.pattern)

    def test_unrelated_callers_and_non_menu_marker_are_unchanged(self):
        target = 0x4000 + build.STATUS_WRAPPER - 0x8000 + 4
        for address, marker in ((0x494A, 0x80), (0x1BEB, 0x80), (target + 1, 0x80), (target ^ 0x100, 0x80)):
            memory = bytearray(0x10000)
            memory[0xC4F2] = marker
            result, registers, flag, sp, calls = run_router(self.rom, memory, address, zero=True)
            self.assertEqual((result, registers, flag, sp, calls),
                             ("legacy", (0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77), True, 0xD000, []))
            self.assertEqual(memory[0xC4F2], marker)
        for marker in (0, 0x8F, 0x93):
            memory = bytearray(0x10000)
            memory[0xC4F2] = marker
            result, _, _, _, calls = run_router(self.rom, memory, target)
            self.assertEqual((result, memory[0xC4F2], calls.count(0x0521)), ("return", marker, 0))


if __name__ == "__main__":
    unittest.main()
