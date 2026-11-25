import unittest

from scripts import build_v2_6_11_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from test_build_v2_6_10_status import VideoCpu


class ScrollMaskRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.patch, cls.version = build.build()
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.labels, cls.patterns = build.previous.previous.compile_labels(
            build.previous.previous.previous.OUTPUT_ROM.read_bytes())

    def test_scrolled_status_entry_masks_original_frame(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0xFF43] = 0xF8
        cpu.call_frame()
        self.assertEqual(cpu.memory[0xFF40], 0xE7)
        self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_snapshot_wraps_rows_and_columns_and_restores_glyphs(self):
        for upper in (0, 0x20):
            for scroll_y, scroll_x in ((0, 8), (0, 0xF8), (0xE8, 0x90), (0xF8, 0xF8)):
                with self.subTest(upper=upper, y=scroll_y, x=scroll_x):
                    cpu = VideoCpu(self.rom, upper)
                    cpu.memory[0xFF42], cpu.memory[0xFF43] = scroll_y, scroll_x
                    for row in range(32):
                        for col in range(32):
                            cpu.memory[0x9800 + row * 32 + col] = 0x80 + ((row * 7 + col) % 0x40)
                    bg = bytes(cpu.memory[0x9800:0x9C00])
                    original = bytes((index * 13 + 19) & 0xFF for index in range(len(self.patterns)))
                    cpu.memory[0x9200:0x9360] = original
                    cpu.call_frame()
                    for row in range(18):
                        for col in range(20):
                            source = ((scroll_y // 8 + row) & 31) * 32 + ((scroll_x // 8 + col) & 31)
                            self.assertEqual(cpu.memory[0x9C00 + row * 32 + col], bg[source])
                    self.assertEqual(cpu.memory[0xFF40], 0xE7)
                    cpu.call_entry()
                    self.assertEqual(cpu.memory[0xFF40], 0xC7)
                    self.assertEqual(cpu.memory[0x9200:0x9360], self.patterns)
                    self.assertEqual(cpu.memory[0x9C00:0x9E40], b"\xCD" * 0x240)
                    cpu.call_exit(0x4B7B)
                    self.assertEqual(cpu.memory[0x9200:0x9360], original)
                    self.assertEqual((cpu.memory[0xC4F2], cpu.bank, cpu.memory[0xFFA9], cpu.ime, cpu.sp),
                                     (0, 2, 2, True, 0xD000))

    def test_unaligned_scroll_fails_without_corrupting_background(self):
        for register in (0xFF42, 0xFF43):
            with self.subTest(register=hex(register)):
                cpu = VideoCpu(self.rom)
                cpu.memory[register] |= 1
                before = bytes(cpu.memory[0x9C00:0xA000])
                cpu.call_frame()
                self.assertEqual(cpu.memory[0xC4F2], build.previous.FAILURE_MARKER)
                self.assertEqual(cpu.memory[0x9C00:0xA000], before)
                self.assertFalse(cpu.lcdc_writes)
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9850], 0xCB)
                cpu.call_exit(0x4B7B)
                self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_patch_roundtrip_and_mirror(self):
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        component, _ = build.build_components(build.previous.previous.previous.OUTPUT_ROM.read_bytes())
        offset = build.previous.previous.COMPONENT_START
        self.assertEqual(self.rom[offset:offset + len(component)],
                         self.rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + len(component)])
        allowed = {0x14E, 0x14F}
        allowed.update(range(offset, offset + len(component)))
        allowed.update(range(offset + MBC1_MIRROR_OFFSET, offset + MBC1_MIRROR_OFFSET + len(component)))
        self.assertTrue(all(index in allowed for index, (old, new) in enumerate(zip(self.parent, self.rom))
                            if old != new))


if __name__ == "__main__":
    unittest.main()
