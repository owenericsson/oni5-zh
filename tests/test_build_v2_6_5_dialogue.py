import unittest
import hashlib
import json

from scripts import build_v2_6_4_dialogue as previous
from scripts import build_v2_6_5_dialogue as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_v2_6_3_dialogue import _read_macro
from scripts.build_opening_text_preview_patch import FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import verify_rom


def run_candidate_helper(rom, offset, memory):
    """Execute the new dispatchers and wrappers with the existing copy primitives modeled."""
    pc = build.bank_cpu_address(offset)
    a, b, c, d, e, h, l = 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77
    zero = False
    calls = []
    stack = []
    call_stack = []

    def byte():
        nonlocal pc
        if not 0x4000 <= pc < 0x8000:
            raise AssertionError(f"helper jumped outside bank: ${pc:04X}")
        value = rom[build.SOURCE_SIZE + pc - 0x4000]
        pc += 1
        return value

    def word():
        low = byte()
        return low | (byte() << 8)

    for _ in range(500):
        op = byte()
        if op == 0xFA:
            a = memory[word()]
        elif op == 0xFE:
            zero = a == byte()
        elif op == 0x20:
            delta = byte()
            if not zero:
                pc += delta if delta < 128 else delta - 256
        elif op == 0xB7:
            zero = a == 0
        elif op == 0xAF:
            a, zero = 0, True
        elif op == 0x3E:
            a = byte()
        elif op == 0x06:
            b = byte()
        elif op == 0xEA:
            memory[word()] = a
        elif op in (0x21, 0x11, 0x01):
            value = word()
            if op == 0x21:
                h, l = value >> 8, value & 0xFF
            elif op == 0x11:
                d, e = value >> 8, value & 0xFF
            else:
                b, c = value >> 8, value & 0xFF
        elif op in (0xC5, 0xD5, 0xE5, 0xF5):
            stack.append({0xC5: (b, c), 0xD5: (d, e), 0xE5: (h, l), 0xF5: (a, zero)}[op])
        elif op in (0xC1, 0xD1, 0xE1, 0xF1):
            value = stack.pop()
            if op == 0xC1:
                b, c = value
            elif op == 0xD1:
                d, e = value
            elif op == 0xE1:
                h, l = value
            else:
                a, zero = value
        elif op == 0xCD:
            dest = word()
            calls.append(dest)
            if dest == 0x7D3E:
                source = build.SOURCE_SIZE + ((h << 8) | l) - 0x4000
                for index in range(b):
                    record = rom[source + 10 * index:source + 10 * (index + 1)]
                    address = int.from_bytes(record[:2], "little")
                    memory[address:address + 16] = bytes(row for row in record[2:] for _ in range(2))
            elif dest == 0x0521:
                source = build.SOURCE_SIZE + ((h << 8) | l) - 0x4000
                address = (d << 8) | e
                length = (b << 8) | c
                if length != 16:
                    raise AssertionError(f"unexpected copy length {length}")
                memory[address:address + length] = rom[source:source + length]
            elif dest == 0x4290:
                pass
            else:
                call_stack.append(pc)
                pc = dest
        elif op == 0xC3:
            dest = word()
            if dest == 0x4108:
                if stack or call_stack:
                    raise AssertionError("unbalanced stack before old dispatcher")
                return "legacy", (a, b, c, d, e, h, l), calls
            pc = dest
        elif op == 0xC9 or (op == 0xC0 and not zero):
            if call_stack:
                pc = call_stack.pop()
            else:
                if stack:
                    raise AssertionError("unbalanced register stack")
                return "return", (a, b, c, d, e, h, l), calls
        elif op != 0xC0:
            raise AssertionError(f"unexpected opcode ${op:02X} at ${pc - 1:04X}")
    raise AssertionError("candidate helper did not return")


class PreparePagesTests(unittest.TestCase):
    def test_dash_restore_is_gated_to_special_sentence(self):
        helper = build.build_special_dash_restore(0x7000)
        conditions = ((0xFFAA, 4), (0xFFAE, 0x36), (0xFFAD, 0xF2), (0xC4F2, build.LATER_MARKER))
        for i, (address, value) in enumerate(conditions):
            self.assertEqual(helper[i * 6:i * 6 + 6],
                             bytes((0xFA, address & 0xFF, address >> 8, 0xFE, value, 0xC0)))
        self.assertEqual(helper[24:28], bytes.fromhex("C5 D5 E5 F5"))
        self.assertEqual(helper[28:40], bytes.fromhex("21 00 70 11 70 8B 01 10 00 CD 21 05"))
        self.assertEqual(helper[40:], bytes.fromhex("F1 E1 D1 C1 C9"))
        with self.assertRaises(ValueError):
            build.build_special_dash_restore(0x7FF1)

    def test_dash_restore_copies_only_for_matching_context(self):
        helper = build.build_special_dash_restore(0x7000)
        font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
        original_dash = font[0x370:0x380]
        self.assertEqual(len(original_dash), 16)

        def execute(memory):
            pc = 0
            while pc < 24:
                self.assertEqual(helper[pc], 0xFA)
                address = int.from_bytes(helper[pc + 1:pc + 3], "little")
                self.assertEqual(helper[pc + 3], 0xFE)
                self.assertEqual(helper[pc + 5], 0xC0)
                if memory[address] != helper[pc + 4]:
                    return
                pc += 6
            self.assertEqual(helper[28:40], bytes.fromhex("21 00 70 11 70 8B 01 10 00 CD 21 05"))
            memory[0x8B70:0x8B80] = original_dash

        context = {0xFFAA: 4, 0xFFAE: 0x36, 0xFFAD: 0xF2, 0xC4F2: build.LATER_MARKER}
        for mismatch in (None, *context):
            with self.subTest(mismatch=mismatch):
                memory = bytearray(0x10000)
                for address, value in context.items():
                    memory[address] = value
                if mismatch is not None:
                    memory[mismatch] ^= 1
                memory[0x8B70:0x8B80] = b"\xAA" * 16
                before = bytes(memory)
                execute(memory)
                expected = bytearray(before)
                if mismatch is None:
                    expected[0x8B70:0x8B80] = original_dash
                self.assertEqual(memory, expected)

    def test_following_automatic_dialogue_needs_original_font_restoration(self):
        rom = previous.OUTPUT_ROM.read_bytes()
        mappings, _ = build.prepare_pages()
        self.assertEqual(
            build.automatic_scene_tiles(rom) & set(mappings[1].values()),
            {0x88, 0x89, 0x8C, 0x8D, 0x8F, 0x9D, 0xA1, 0xB6, 0xB7},
        )
        altered = bytearray(rom)
        altered[0x136F1] = 0
        with self.assertRaises(ValueError):
            build.automatic_scene_tiles(altered)

    def test_confirmed_pages_fit_and_keep_dynamic_name(self):
        mappings, pages = build.prepare_pages()
        expansions = {0xB0: "原来是", 0xC6: "伽罗", 0x80: "{主角}", 0xD4: "——", 0xD0: "！！」",
                      0x41: "1", 0x46: "6", 0x7D: "\n", 0x4D: "",
                      0x3B: "「", 0x3C: "」", 0x3E: "。", 0x4A: "？", 0x4B: "！"}
        rom = previous.OUTPUT_ROM.read_bytes()
        self.assertEqual(_read_macro(rom, 0xB0), bytes.fromhex("34 18 19"))
        self.assertEqual(_read_macro(rom, 0xC6), bytes.fromhex("29 2F"))
        self.assertEqual(_read_macro(rom, 0xD4), bytes.fromhex("37 37"))
        self.assertEqual(_read_macro(rom, 0xD0), bytes.fromhex("4B 4B 3C"))
        self.assertEqual(mappings[1]["妈"], 0xB7)
        self.assertNotIn("妈", build.PAGES[6][2] + build.PAGES[7][2] + build.PAGES[8][2])
        for index, (start, end, text) in enumerate(build.PAGES):
            with self.subTest(start=start):
                mapping = mappings[0 if index < 4 else 1]
                self.assertFalse(set(mapping.values()) & previous.CURRENT_NAME_TILES)
                self.assertEqual(len(set(mapping.values())), len(mapping))
                self.assertEqual(len(pages[start]), end - start)
                decoded = {tile - 0x80: char for char, tile in mapping.items()} | expansions
                actual = "".join(decoded[byte] for byte in pages[start])
                expected = (text.replace("{16}", "16").replace("{原来是}", "原来是")
                            .replace("{伽罗}", "伽罗").replace("{破折}", "——").replace("{结尾}", "！！」"))
                self.assertEqual(actual, expected)


class CandidateBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = previous.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, cls.version = build.build()
        cls.components = {
            key: int(value, 16)
            for key, value in cls.version["implementation"]["glyph_components"].items()
        }
        cls.mappings, cls.pages = build.prepare_pages()
        cls.font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)

    def test_exact_parent_bps_mirror_and_page_boundaries(self):
        self.assertEqual(hashlib.sha256(self.parent).hexdigest(), build.EXPECTED_PARENT_SHA256)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        self.assertTrue(verify_rom(self.rom).passed)
        for index, (start, end, _) in enumerate(build.PAGES):
            with self.subTest(start=start):
                self.assertEqual(self.rom[start:end], self.pages[start])
                self.assertEqual(self.rom[end], self.parent[end])
                self.assertEqual(self.rom[start - 1], 0x57 if index in (0, 4) else 0x7C)
                self.assertEqual(self.rom[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end],
                                 self.pages[start])
        self.assertEqual(self.rom[0x13629:0x1362D], bytes.fromhex("7C 80 7D 3B"))
        self.assertEqual(self.rom[0x13700:0x13720], self.parent[0x13700:0x13720])
        self.assertEqual(
            self.rom[build.SOURCE_SIZE:build.SOURCE_SIZE + 0x4000],
            self.rom[MBC1_MIRROR_OFFSET + build.SOURCE_SIZE:MBC1_MIRROR_OFFSET + build.SOURCE_SIZE + 0x4000],
        )

    def test_only_pages_checked_free_space_and_gate_operands_change(self):
        ranges = [(start, end) for start, end, _ in build.PAGES]
        ranges += list(build.FREE_RANGES) + [(0x40101, 0x40103), (0x43042, 0x43044)]
        ranges += [(start + MBC1_MIRROR_OFFSET, end + MBC1_MIRROR_OFFSET)
                   for start, end in ranges]
        ranges.append((0x14E, 0x150))
        for offset, (old, new) in enumerate(zip(self.parent, self.rom)):
            if old != new:
                self.assertTrue(any(start <= offset < end for start, end in ranges),
                                f"unexpected change at ${offset:06X}")

    def test_loading_switching_dash_and_final_restore(self):
        memory = bytearray(0x10000)
        memory[0x8800:0x8C00] = self.font[:0x400]
        assets = tuple(
            json.loads((build.ROOT / "data" / name).read_text(encoding="utf-8"))
            for name in ("chinese_glyphs_oni5_v265_dialogues.json", "chinese_glyphs_oni5_v264_dialogues.json")
        )
        patterns = build.load_glyph_patterns(assets, list(dict.fromkeys(
            c for mapping in self.mappings for c in mapping
        )))
        memory[0xFFAA], memory[0xFFAE], memory[0xFFAD] = 4, 0x35, 0xD9
        result, registers, calls = run_candidate_helper(self.rom, self.components["load_dispatcher"], memory)
        self.assertEqual((result, registers[0], registers[1], memory[0xC4F2], memory[0xC4F0]),
                         ("return", 1, 0xCD, build.EARLIER_MARKER, 0xA9))
        for char, tile in self.mappings[0].items():
            address = 0x8800 + (tile - 0x80) * 16
            self.assertEqual(memory[address:address + 16], patterns[char])
        memory[0xFFAE], memory[0xFFAD] = 0x36, 0x73
        result, registers, calls = run_candidate_helper(self.rom, self.components["load_dispatcher"], memory)
        self.assertEqual((result, registers[0], registers[1], memory[0xC4F2], memory[0xC4F0]),
                         ("return", 1, 0xCD, build.LATER_MARKER, 0x81))
        self.assertLess(calls.index(0x7D9A), calls.index(build.bank_cpu_address(self.components["later_loader"])))
        for char, tile in self.mappings[1].items():
            address = 0x8800 + (tile - 0x80) * 16
            self.assertEqual(memory[address:address + 16], patterns[char])
        memory[0xFFAD] = 0xF2
        result, _, calls = run_candidate_helper(self.rom, self.components["load_dispatcher"], memory)
        self.assertEqual(result, "legacy")
        self.assertIn(0x0521, calls)
        self.assertEqual(memory[0x8B70:0x8B80], self.font[0x370:0x380])
        for char, tile in self.mappings[1].items():
            if tile != 0xB7:
                address = 0x8800 + (tile - 0x80) * 16
                self.assertEqual(memory[address:address + 16], patterns[char])
        memory[0xFFAE], memory[0xFFAD] = 0x37, 0
        result, _, calls = run_candidate_helper(self.rom, self.components["close_dispatcher"], memory)
        self.assertEqual(result, "return")
        self.assertEqual(calls[:2], [0x4290, 0x7D9A])
        self.assertEqual(memory[0x8800:0x8C00], self.font[:0x400])
        self.assertEqual(memory[0xC4F2], 0)

    def test_other_contexts_take_original_paths(self):
        for bank, high, cursor, marker in (
            (5, 0x35, 0xD9, 0), (4, 0x35, 0xD8, 0), (4, 0x35, 0xD9, 0x89),
            (4, 0x36, 0x73, 0), (4, 0x36, 0x74, build.EARLIER_MARKER),
            (5, 0x36, 0xF2, build.LATER_MARKER), (4, 0x36, 0xF2, 0x89),
        ):
            with self.subTest(bank=bank, high=high, cursor=cursor, marker=marker):
                memory = bytearray(0x10000)
                memory[0xFFAA], memory[0xFFAE], memory[0xFFAD] = bank, high, cursor
                memory[0xC4F2] = marker
                before = bytes(memory)
                result, _, calls = run_candidate_helper(self.rom, self.components["load_dispatcher"], memory)
                self.assertEqual(result, "legacy")
                self.assertNotIn(0x0521, calls)
                self.assertEqual(memory, before)
        for bank, high, cursor, marker in ((5, 0x37, 0, build.LATER_MARKER),
                                            (4, 0x37, 1, build.LATER_MARKER),
                                            (4, 0x37, 0, 0x89)):
            memory = bytearray(0x10000)
            memory[0xFFAA], memory[0xFFAE], memory[0xFFAD] = bank, high, cursor
            memory[0xC4F2] = marker
            result, _, calls = run_candidate_helper(self.rom, self.components["close_dispatcher"], memory)
            self.assertEqual((result, calls, memory[0xC4F2]), ("return", [0x4290], marker))


if __name__ == "__main__":
    unittest.main()
