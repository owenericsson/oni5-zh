import hashlib
import json
import unittest

from scripts import build_v2_6_6_dialogue as previous
from scripts import build_v2_6_7_dialogue as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_opening_text_preview_patch import FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM
from scripts.build_v2_6_3_dialogue import _read_macro
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import verify_rom
from test_build_v2_6_6_dialogue import run_helper


class PreparePagesTests(unittest.TestCase):
    def test_confirmed_pages_fit_and_keep_names_and_native_punctuation(self):
        rom = previous.OUTPUT_ROM.read_bytes()
        for code, expected in ((0xB0, "34 18 19"), (0xD4, "37 37"), (0xD5, "3A 3A"),
                               (0xCE, "4A 3C"), (0xD2, "4B 3C"),
                               (0xD0, "4B 4B 3C"), (0xCC, "4B 4A 3C")):
            self.assertEqual(_read_macro(rom, code), bytes.fromhex(expected))
        mappings, pages = build.prepare_pages()
        substitutions = {"{省略}": "……", "{长音}": "——", "{问结}": "？」",
                         "{感叹结}": "！」", "{双感叹结}": "！！」",
                         "{惊问结}": "！？」", "{竟敢对}": "竟敢对", "{什么声}": "什么声"}
        expected_pages = (
            "{主角}\n「那家伙到底是什么人……？」", "伽罗\n「{主角}————！」",
            "伽罗\n「你没事吧，{主角}？」", "{主角}\n「嗯。」",
            "妖怪\n「竟敢对同伴下手！吃我这招！」", "弥生\n「啊！」",
            "伽罗\n「啊！阿姨！」", "妖怪\n「那个女人我们要带走，\n献给魔王当祭品！」",
            "{主角}\n「妈——妈妈！！」",
            "弥生\n「呜……{主角}，去三日月山……\n那里有能改变你命运的东西……」",
            "{主角}\n「你在说什么啊？」", "弥生\n「是三日月山…………」",
            "伽罗\n「啊，阿姨——！！」", "{主角}\n「妈妈————！」",
            "男人\n「什么？这是什么声音！？」", "男人\n「喂，发生什么事了？」",
        )
        page_index = 0
        for index, group in enumerate(build.GROUPS):
            mapping = mappings[index]
            self.assertFalse(set(mapping.values()) & (build.CURRENT_NAME_TILES | {0xB7, 0xBA}))
            self.assertEqual(len(set(mapping.values())), len(mapping))
            decode = {tile - 0x80: character for character, tile in mapping.items()}
            decode.update({0x80: "{主角}", 0xD5: "……", 0xD4: "——", 0xCE: "？」", 0xD2: "！」",
                           0xD0: "！！」", 0xCC: "！？」", 0x7D: "\n",
                           0x3B: "「", 0x3C: "」", 0x3E: "。", 0x4A: "？", 0x4B: "！", 0x4D: ""})
            if index == 1:
                decode[0xB0] = "竟敢对"
            elif index == 3:
                decode[0xB0] = "什么声"
            for start, end, text in group:
                with self.subTest(start=start):
                    for token, rendered in substitutions.items():
                        text = text.replace(token, rendered)
                    self.assertEqual(len(pages[start]), end - start)
                    self.assertEqual("".join(decode[code] for code in pages[start]), text)
                    self.assertEqual(text, expected_pages[page_index])
                    self.assertIn(rom[end], (0x7E, 0x7F))
                    page_index += 1


class CandidateBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = previous.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, cls.version = build.build()
        cls.mappings, cls.pages = build.prepare_pages()
        asset = json.loads((build.ROOT / "data/chinese_glyphs_oni5_v267_dialogues.json").read_text(encoding="utf-8"))
        cls.patterns = build.load_glyph_patterns((asset,), list(dict.fromkeys(
            character for mapping in cls.mappings for character in mapping)))
        cls.font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)

    def test_patch_boundaries_checksums_and_mirrors(self):
        self.assertEqual(hashlib.sha256(self.parent).hexdigest(), build.EXPECTED_PARENT_SHA256)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        self.assertTrue(verify_rom(self.rom).passed)
        for start, end, _ in build.PAGES:
            self.assertEqual(self.rom[start:end], self.pages[start])
            self.assertEqual(self.rom[end], self.parent[end])
            self.assertEqual(self.rom[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end], self.pages[start])
        for start in (build.SOURCE_SIZE, previous.BANK11):
            self.assertEqual(self.rom[start:start + 0x4000],
                             self.rom[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + start + 0x4000])
        ranges = [(start, end) for start, end, _ in build.PAGES]
        ranges += [(0x40101, 0x40103), (0x43042, 0x43044),
                   (build.LOAD_THUNK, build.LOAD_THUNK + 16), (build.LOAD_GATE, build.LOAD_GATE + 17),
                   (build.CLOSE_THUNK, build.CLOSE_GATE + 14),
                   (build.LOAD_THUNK + 0x4000, build.LOAD_THUNK + 0x4010),
                   (build.CLOSE_THUNK + 0x4000, build.CLOSE_THUNK + 0x4010),
                   (build.COMPONENT_START, build.COMPONENT_END)]
        ranges += [(start + MBC1_MIRROR_OFFSET, end + MBC1_MIRROR_OFFSET) for start, end in ranges]
        ranges.append((0x14E, 0x150))
        for offset, (old, new) in enumerate(zip(self.parent, self.rom)):
            if old != new:
                self.assertTrue(any(start <= offset < end for start, end in ranges),
                                f"unexpected change at ${offset:06X}")

    def test_actual_router_group_switches_and_final_restore_in_both_mirrors(self):
        all_tiles = set().union(*(set(mapping.values()) for mapping in self.mappings))
        for upper in (0, 0x20):
            memory = bytearray(0x10000)
            memory[0x8800:0x8C00] = self.font[:0x400]
            memory[0xFFA9], memory[0xFFAA] = 7, 4
            for index, (high, low, tile) in enumerate((
                (0x3A, 0x43, 0xBB), (0x3A, 0xA5, self.pages[0x13AA4][0] + 0x80),
                (0x3B, 0x23, self.pages[0x13B22][0] + 0x80),
                (0x3B, 0x89, self.pages[0x13B88][0] + 0x80),
            )):
                with self.subTest(upper=upper, group=index):
                    memory[0xFFAE], memory[0xFFAD] = high, low
                    result, registers, banks, _ = run_helper(self.rom, build.LOAD_GATE, memory, upper)
                    self.assertEqual((result, registers[0], registers[1]), ("return", 1, 0xCD))
                    self.assertEqual((memory[0xC4F2], memory[0xC4F0]), (build.MARKERS[index], tile))
                    self.assertEqual((banks, memory[0xFFA9]), ([0x11, 0x10], 7))
                    for glyph_tile in all_tiles:
                        address = 0x8800 + (glyph_tile - 0x80) * 16
                        character = next((c for c, t in self.mappings[index].items() if t == glyph_tile), None)
                        expected = (self.patterns[character] if character is not None
                                    else self.font[address - 0x8800:address - 0x8800 + 16])
                        self.assertEqual(memory[address:address + 16], expected)
            memory[0xFFAE], memory[0xFFAD] = 0x3B, 0xC6
            result, _, banks, _ = run_helper(self.rom, build.CLOSE_GATE, memory, upper)
            self.assertEqual((result, banks, memory[0xC4F2], memory[0xFFA9]),
                             ("return", [0x11, 0x10], 0, 7))
            self.assertEqual(memory[0x8800:0x8C00], self.font[:0x400])

    def test_unrelated_contexts_and_previous_close_remain_intact(self):
        for bank, high, low, marker in ((5, 0x3A, 0x43, 0), (0x0C, 0x3A, 0x43, 0),
                                        (4, 0x3A, 0x44, 0), (4, 0x3A, 0xA5, 0x89),
                                        (4, 0x37, 0xA5, 0x89)):
            memory = bytearray(0x10000)
            memory[0xFFAA], memory[0xFFAE], memory[0xFFAD], memory[0xC4F2] = bank, high, low, marker
            before = bytes(memory)
            result, _, banks, _ = run_helper(self.rom, build.LOAD_GATE, memory)
            self.assertEqual((result, banks), ("legacy", [0x11, 0x10] if high in (0x3A, 0x3B) else []))
            self.assertEqual(memory, before)
        for bank, low, marker in ((5, 0xC6, build.MARKERS[-1]), (4, 0xC7, build.MARKERS[-1]),
                                  (4, 0xC6, 0x89)):
            memory = bytearray(0x10000)
            memory[0xFFAA], memory[0xFFAE], memory[0xFFAD], memory[0xC4F2] = bank, 0x3B, low, marker
            before = bytes(memory)
            result, _, banks, _ = run_helper(self.rom, build.CLOSE_GATE, memory)
            self.assertEqual((result, banks), ("return", [0x11, 0x10]))
            self.assertEqual(memory, before)
        memory = bytearray(0x10000)
        memory[0xFFAA], memory[0xFFAE], memory[0xFFAD] = 4, 0x37, 0x3B
        result, _, banks, _ = run_helper(self.rom, build.LOAD_GATE, memory)
        self.assertEqual((result, banks, memory[0xC4F2]), ("return", [0x11, 0x10], previous.MARKER))
        memory = bytearray(0x10000)
        memory[0x8800:0x8C00] = b"\xAA" * 0x400
        memory[0xFFAA], memory[0xFFAE], memory[0xFFAD], memory[0xC4F2] = 4, 0x37, 0xA4, previous.MARKER
        result, _, banks, calls = run_helper(self.rom, build.CLOSE_GATE, memory)
        self.assertEqual((result, banks, memory[0xC4F2]), ("return", [], 0))
        self.assertIn((0x10, 0x7D9A), calls)


if __name__ == "__main__":
    unittest.main()
