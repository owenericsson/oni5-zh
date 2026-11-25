import unittest
import hashlib
import json

from scripts import build_v2_6_5_dialogue as previous
from scripts import build_v2_6_6_dialogue as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_opening_text_preview_patch import FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM
from scripts.build_v2_6_3_dialogue import _read_macro
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import verify_rom


def run_helper(rom, offset, memory, upper_bank=0):
    """Execute the actual router, mirrored bank thunk and compact copy instructions."""
    pc = build.bank_cpu_address(offset)
    bank = 0x10
    a, b, c, d, e, h, l = 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77
    zero = False
    values, returns, banks, calls = [], [], [], []

    def byte():
        nonlocal pc
        if not 0x4000 <= pc < 0x8000 or bank not in (0x10, 0x11):
            raise AssertionError(f"invalid bank ${bank:02X}, PC ${pc:04X}")
        file_offset = (bank + upper_bank) * 0x4000 + pc - 0x4000
        value = rom[file_offset]
        pc += 1
        return value

    def word():
        low = byte()
        return low | (byte() << 8)

    for _ in range(12000):
        op = byte()
        if op == 0xFA:
            a = memory[word()]
        elif op == 0xFE:
            zero = a == byte()
        elif op in (0x20, 0x28):
            delta = byte()
            if zero == (op == 0x28):
                pc += delta if delta < 128 else delta - 256
        elif op == 0x3E:
            a = byte()
        elif op == 0x06:
            b = byte()
        elif op == 0x0E:
            c = byte()
        elif op == 0xEA:
            address = word()
            if address == 0x2000:
                bank = a
                banks.append(bank)
            else:
                memory[address] = a
        elif op == 0x21:
            value = word()
            h, l = value >> 8, value & 0xFF
        elif op == 0x11:
            value = word()
            d, e = value >> 8, value & 0xFF
        elif op == 0x01:
            value = word()
            b, c = value >> 8, value & 0xFF
        elif op == 0x2A:
            address = (h << 8) | l
            a = rom[(bank + upper_bank) * 0x4000 + address - 0x4000]
            address = (address + 1) & 0xFFFF
            h, l = address >> 8, address & 0xFF
        elif op == 0x5F:
            e = a
        elif op == 0x57:
            d = a
        elif op == 0xF0:
            a = memory[0xFF00 + byte()]
        elif op == 0xE6:
            a &= byte()
            zero = a == 0
        elif op == 0x12:
            memory[(d << 8) | e] = a
        elif op == 0x13:
            value = (((d << 8) | e) + 1) & 0xFFFF
            d, e = value >> 8, value & 0xFF
        elif op == 0x0D:
            c = (c - 1) & 0xFF
            zero = c == 0
        elif op == 0x05:
            b = (b - 1) & 0xFF
            zero = b == 0
        elif op == 0xAF:
            a, zero = 0, True
        elif op == 0xB7:
            zero = a == 0
        elif op in (0xC5, 0xD5, 0xE5, 0xF5):
            values.append({0xC5: (b, c), 0xD5: (d, e), 0xE5: (h, l), 0xF5: (a, zero)}[op])
        elif op in (0xC1, 0xD1, 0xE1, 0xF1):
            value = values.pop()
            if op == 0xC1:
                b, c = value
            elif op == 0xD1:
                d, e = value
            elif op == 0xE1:
                h, l = value
            else:
                a, zero = value
        elif op == 0xCD:
            target = word()
            calls.append((bank, target))
            if target == 0x4290:
                continue
            if target == 0x0521:
                source, dest, length = (h << 8) | l, (d << 8) | e, (b << 8) | c
                if length != 16:
                    raise AssertionError("unexpected full-pattern copy length")
                start = (bank + upper_bank) * 0x4000 + source - 0x4000
                memory[dest:dest + length] = rom[start:start + length]
            else:
                returns.append(pc)
                pc = target
        elif op == 0xC3:
            target = word()
            if target == 0x604F:
                if returns or values or bank != 0x10:
                    raise AssertionError("unbalanced state before previous load dispatcher")
                return "legacy", (a, b, c, d, e, h, l), banks, calls
            pc = target
        elif op in (0xC9, 0xC0):
            if op == 0xC0 and zero:
                continue
            if returns:
                pc = returns.pop()
            else:
                if values or bank != 0x10:
                    raise AssertionError("unbalanced state on return")
                return "return", (a, b, c, d, e, h, l), banks, calls
        else:
            raise AssertionError(f"unexpected opcode ${op:02X} at ${pc - 1:04X}")
    raise AssertionError("helper did not return")


class PreparePagesTests(unittest.TestCase):
    def test_confirmed_pages_fit_and_keep_original_names_and_punctuation(self):
        rom = previous.OUTPUT_ROM.read_bytes()
        self.assertEqual(_read_macro(rom, 0xB0), bytes.fromhex("34 18 19"))
        self.assertEqual(_read_macro(rom, 0xD2), bytes.fromhex("4B 3C"))
        self.assertEqual(_read_macro(rom, 0xCC), bytes.fromhex("4B 4A 3C"))
        self.assertEqual(_read_macro(rom, 0xD0), bytes.fromhex("4B 4B 3C"))
        mapping, pages = build.prepare_pages()
        self.assertFalse(set(mapping.values()) & build.CURRENT_NAME_TILES)
        self.assertEqual(len(set(mapping.values())), len(mapping))
        decode = {tile - 0x80: character for character, tile in mapping.items()}
        decode.update({0x80: "{主角}", 0xB0: "是从外", 0xD2: "！」",
                       0xCC: "！？」", 0xD0: "！！」", 0x7D: "\n",
                       0x3B: "「", 0x4B: "！", 0x4D: ""})
        expected = (
            "{主角}\n「是从外面传来的！」",
            "{主角}\n「啊，在干什么！？」",
            "妖怪\n「啧，糟了！\n事到如今，你也去死吧！！」",
        )
        for (start, end, _), text in zip(build.PAGES, expected):
            with self.subTest(start=start):
                self.assertEqual(len(pages[start]), end - start)
                self.assertEqual("".join(decode[code] for code in pages[start]), text)
                self.assertEqual(rom[end], 0x7F)
        self.assertEqual(pages[0x13738][:4], bytes.fromhex("80 7D 3B B0"))
        self.assertEqual(pages[0x13774][:3], bytes.fromhex("80 7D 3B"))


class CandidateBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = previous.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, cls.version = build.build()
        cls.mapping, cls.pages = build.prepare_pages()
        asset = json.loads((build.ROOT / "data/chinese_glyphs_oni5_v266_dialogues.json").read_text(encoding="utf-8"))
        cls.patterns = build.load_glyph_patterns((asset,), list(cls.mapping))
        cls.font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)

    def test_exact_parent_bps_pages_and_mirrors(self):
        self.assertEqual(hashlib.sha256(self.parent).hexdigest(), build.EXPECTED_PARENT_SHA256)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        self.assertTrue(verify_rom(self.rom).passed)
        for start, end, _ in build.PAGES:
            with self.subTest(start=start):
                self.assertEqual(self.rom[start:end], self.pages[start])
                self.assertEqual(self.rom[end], self.parent[end])
                self.assertEqual(self.rom[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end],
                                 self.pages[start])
        self.assertEqual(self.rom[0x137A3:0x13800], self.parent[0x137A3:0x13800])
        for start in (build.SOURCE_SIZE, build.BANK11):
            self.assertEqual(self.rom[start:start + 0x4000],
                             self.rom[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + start + 0x4000])

    def test_only_checked_ranges_change(self):
        ranges = [(start, end) for start, end, _ in build.PAGES]
        ranges += [(0x40101, 0x40103), (0x43042, 0x43044), (build.FIRST_ROUTER, 0x40F00),
                   (build.SECOND_ROUTER, 0x40FD0), (build.THIRD_ROUTER, 0x41200),
                   (build.CLOSE_ROUTER, 0x42900), (build.BANK_THUNK, 0x43080),
                   (build.BANK11, build.BANK11_END)]
        ranges += [(start + MBC1_MIRROR_OFFSET, end + MBC1_MIRROR_OFFSET) for start, end in ranges]
        ranges.append((0x14E, 0x150))
        for offset, (old, new) in enumerate(zip(self.parent, self.rom)):
            if old != new:
                self.assertTrue(any(start <= offset < end for start, end in ranges),
                                f"unexpected change at ${offset:06X}")

    def test_each_page_loads_across_banks_then_final_close_restores(self):
        for upper in (0, 0x20):
            with self.subTest(upper_bank=upper):
                memory = bytearray(0x10000)
                memory[0x8800:0x8C00] = self.font[:0x400]
                memory[0xFFA9], memory[0xFFAA], memory[0xFFAE] = 7, 4, 0x37
                third_tile = self.pages[0x1378B][0] + 0x80
                for cursor, tile in ((0x3B, 0xBB), (0x77, 0xBB), (0x8C, third_tile)):
                    memory[0xFFAD] = cursor
                    result, registers, banks, _ = run_helper(self.rom, build.FIRST_ROUTER, memory, upper)
                    self.assertEqual((result, registers[0], registers[1], memory[0xC4F2], memory[0xC4F0]),
                                     ("return", 1, 0xCD, build.MARKER, tile))
                    self.assertEqual(banks, [0x11, 0x10])
                    self.assertEqual(memory[0xFFA9], 7)
                    for character, tile in self.mapping.items():
                        address = 0x8800 + (tile - 0x80) * 16
                        self.assertEqual(memory[address:address + 16], self.patterns[character])
                    memory[0x8800:0x8C00] = self.font[:0x400]
                memory[0xFFAD] = 0x8C
                run_helper(self.rom, build.FIRST_ROUTER, memory, upper)
                memory[0xFFAD] = 0xA4
                result, _, banks, calls = run_helper(self.rom, build.CLOSE_ROUTER, memory, upper)
                self.assertEqual(result, "return")
                self.assertEqual(banks, [])
                self.assertIn((0x10, 0x7D9A), calls)
                self.assertEqual(memory[0x8800:0x8C00], self.font[:0x400])
                self.assertEqual(memory[0xC4F2], 0)
                self.assertEqual(memory[0xFFA9], 7)

    def test_unrelated_contexts_fall_back_without_switching(self):
        for bank, cursor, marker in ((5, 0x3B, 0), (4, 0x3C, 0), (4, 0x3B, 0x89),
                                     (4, 0x77, 0), (4, 0x8C, 0x89)):
            memory = bytearray(0x10000)
            memory[0xFFAA], memory[0xFFAE], memory[0xFFAD], memory[0xC4F2] = bank, 0x37, cursor, marker
            before = bytes(memory)
            result, _, banks, _ = run_helper(self.rom, build.FIRST_ROUTER, memory)
            self.assertEqual((result, banks), ("legacy", []))
            self.assertEqual(memory, before)
        for bank, cursor, marker in ((5, 0xA4, build.MARKER), (4, 0xA5, build.MARKER), (4, 0xA4, 0x89)):
            memory = bytearray(0x10000)
            memory[0xFFAA], memory[0xFFAE], memory[0xFFAD], memory[0xC4F2] = bank, 0x37, cursor, marker
            result, _, banks, calls = run_helper(self.rom, build.CLOSE_ROUTER, memory)
            self.assertEqual((result, banks, memory[0xC4F2]), ("return", [], marker))
            self.assertNotIn((0x10, 0x7D9A), calls)

    def test_previous_automatic_scene_close_still_restores(self):
        memory = bytearray(0x10000)
        memory[0x8800:0x8C00] = b"\xAA" * 0x400
        memory[0xFFAA], memory[0xFFAE], memory[0xFFAD] = 4, 0x37, 0
        memory[0xC4F2] = previous.LATER_MARKER
        result, _, banks, calls = run_helper(self.rom, build.CLOSE_ROUTER, memory)
        self.assertEqual((result, banks, memory[0xC4F2]), ("return", [], 0))
        self.assertIn((0x10, 0x7D9A), calls)
        for tile in self.mapping.values():
            index = (tile - 0x80) * 16
            self.assertEqual(memory[0x8800 + index:0x8810 + index], self.font[index:index + 16])


if __name__ == "__main__":
    unittest.main()
