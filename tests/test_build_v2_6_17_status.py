import json
import unittest

from scripts import build_v2_6_17_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, build_menu_candidate
from test_build_v2_6_10_status import VideoCpu
from test_build_v2_6_15_status import VILLAGE_PARTY_MAP
from test_build_v2_6_8_menu import run_status_entry


FIRST_MENU_MAP = bytes.fromhex("""
52 52 52 d0 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4
d4 d4 d4 d4 d4 d4 d1 65 cd cd cd cd cd cd 6d 6e
53 53 53 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 cd cd cd cd cd cd 00 00
56 58 08 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 65 cd cd cd cd cd cd 00 00
5a 5a 18 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 cd cd cd cd cd cd 00 00
0b 0b 0b d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 65 cd cd cd cd cd cd 00 00
00 00 00 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 cd cd cd cd cd cd 00 00
7b 7b 7b d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 65 cd cd cd cd cd cd 00 00
43 43 43 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 cd cd cd cd cd cd 00 00
52 52 52 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 65 cd cd cd cd cd cd 00 00
53 53 53 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 cd cd cd cd cd cd 00 00
56 58 56 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 65 cd cd cd cd cd cd 7b 7b
5a 5a 5a d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 d1 cd cd cd cd cd 43 43
0b 0b 0b d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 65 d5 cd cd cd cd cd 52 d0
00 00 00 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 d5 cd cd cd cd cd 53 d5
64 65 64 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 65 d5 cd cd cd cd cd 08 d5
74 75 74 d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 75 d5 cd cd cd cd cd 18 d5
6d 6e 6d d5 cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd d5 6e d3 cd cd cd cd cd 0b d5
00 00 00 d2 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4
d4 d4 d4 d4 d4 d4 d3 00 cd cd cd cd cd cd 00 d5
""") + VILLAGE_PARTY_MAP[0x240:]


class SnapshotMenuGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.patch, _ = build.build()
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        asset = json.loads((build.ROOT / "data/menu_chinese_glyphs.json").read_text())
        cls.menu_tiles = {int(glyph["tile"], 16) for glyph in build_menu_candidate(asset)["custom_glyphs"]}

    def test_recorded_first_entry_masks_and_restores_with_offscreen_menu_tile(self):
        self.assertEqual(len(FIRST_MENU_MAP), 0x400)
        self.assertEqual(FIRST_MENU_MAP[0x249], 0x94)
        for upper, exit_address in ((0, 0x4B7B), (0x20, 0x4B96)):
            with self.subTest(upper=upper):
                cpu = VideoCpu(self.rom, upper)
                cpu.memory[0xC4F2] = 0x80
                cpu.memory[0xFF43] = 0x18
                cpu.memory[0x9800:0x9C00] = FIRST_MENU_MAP
                original = bytes((index * 13 + 19) & 0xFF for index in range(0x200))
                cpu.memory[0x9200:0x9400] = original
                cpu.call_frame()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40], cpu.memory[0xFF4A]),
                                 (0x80, 0xE7, 0))
                for row in range(18):
                    for column in range(20):
                        tile = FIRST_MENU_MAP[row * 32 + (3 + column) % 32]
                        self.assertEqual(cpu.memory[0x9C00 + row * 32 + column], tile)
                        self.assertNotIn(tile, self.menu_tiles)
                run_status_entry(self.rom, cpu.memory, upper)
                cpu.call_entry()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
                cpu.call_exit(exit_address)
                self.assertEqual(cpu.memory[0x9200:0x9400], original)
                self.assertEqual(cpu.memory[0x9E40:0xA000], b"\xCD" * 0x1C0)

    def test_visible_menu_glyphs_fail_closed_and_clear_snapshot(self):
        for scroll_y, scroll_x, position in ((0, 0x08, 0x9801), (0, 0xF8, 0x981F),
                                             (0xF8, 0xF8, 0x9BFF)):
            for tile in sorted(self.menu_tiles):
                with self.subTest(scroll_y=scroll_y, scroll_x=scroll_x, tile=tile):
                    cpu = VideoCpu(self.rom)
                    cpu.memory[0xC4F2] = 0x80
                    cpu.memory[0xFF42] = scroll_y
                    cpu.memory[0xFF43] = scroll_x
                    cpu.memory[position] = tile
                    cpu.call_frame()
                    self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40], cpu.memory[0xFF4A]),
                                     (0x80, 0xC7, 0x88))
                    self.assertEqual(cpu.memory[0x9C00:0xA000], b"\xCD" * 0x400)
                    self.assertFalse(cpu.lcdc_writes)

    def test_cached_status_does_not_treat_original_font_as_menu_font(self):
        cpu = VideoCpu(self.rom)
        cpu.call_frame()
        cpu.call_entry()
        saved = bytes(cpu.memory[0x9E40:0xA000])
        cpu.memory[0x9801] = 0x94
        cpu.call_frame()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xE7))
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9E40:0xA000], saved)
        cpu.call_exit(0x4B7B)

    def test_patch_roundtrip_and_mirror(self):
        status = build.previous.status
        component, _ = build.build_components(status.previous.OUTPUT_ROM.read_bytes())
        offset = status.COMPONENT_START
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        self.assertEqual(self.rom[offset:offset + len(component)],
                         self.rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + len(component)])
        allowed = {0x14E, 0x14F}
        allowed.update(range(offset, offset + len(component)))
        allowed.update(range(offset + MBC1_MIRROR_OFFSET, offset + MBC1_MIRROR_OFFSET + len(component)))
        self.assertTrue(all(index in allowed for index, (old, new) in enumerate(zip(self.parent, self.rom))
                            if old != new))


if __name__ == "__main__":
    unittest.main()
