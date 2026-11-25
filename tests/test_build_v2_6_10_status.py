import unittest

from scripts import build_v2_6_10_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from test_build_v2_6_9_status_probe import Cpu


class VideoCpu(Cpu):
    def __init__(self, rom, upper=0):
        super().__init__(rom, upper)
        self.memory[0xFF42] = 0
        self.memory[0xFF43] = 8
        self.memory[0xFF4A] = 0x88
        self.memory[0xFF4B] = 7
        self.ly_reads = 0
        self.video_writes = []
        self.lcdc_writes = []

    def read(self, address):
        if address == 0xFF44:
            self.ly_reads += 1
            return 0 if self.ly_reads % 2 else 144
        return super().read(address)

    def write(self, address, value):
        if address == 0xFF40:
            self.lcdc_writes.append((value, self.ly_reads, self.ime))
        if 0x9800 <= address < 0xA000:
            self.video_writes.append((address, value, self.memory[0xFF40]))
        super().write(address, value)

    def call_frame(self):
        self.pc = 0x49CF
        self.run(0x49D7)


class StatusTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.v268 = build.previous.previous.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, cls.version = build.build()
        cls.labels, cls.patterns = build.previous.compile_labels(cls.v268)
        cls.component, _ = build.build_components(cls.v268)

    def test_patch_scope_and_mirrors(self):
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        allowed = {0x14E, 0x14F}
        for offset, length in ((build.FRAME_CALL, 8), (build.previous.COMPONENT_START, len(self.component))):
            self.assertEqual(self.rom[offset:offset + length],
                             self.rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + length])
            allowed.update(range(offset, offset + length))
            allowed.update(range(offset + MBC1_MIRROR_OFFSET, offset + MBC1_MIRROR_OFFSET + length))
        self.assertTrue(all(index in allowed for index, (old, new) in enumerate(zip(self.parent, self.rom))
                            if old != new))

    def test_frame_is_masked_until_all_labels_are_written_and_patterns_restore(self):
        for upper in (0, 0x20):
            with self.subTest(upper=upper):
                cpu = VideoCpu(self.rom, upper)
                for index in range(0x400):
                    cpu.memory[0x9800 + index] = 0x80 + index % 0x40
                initial_bg = bytes(cpu.memory[0x9800:0x9C00])
                patterns = bytes((index * 13 + 19) & 0xFF for index in range(len(self.patterns)))
                cpu.memory[0x9200:0x9360] = patterns
                before = cpu.registers()
                cpu.call_frame()
                self.assertEqual(cpu.calls[0], (1, 0x1A89, before))
                self.assertEqual(cpu.native_states[0], (0x1A89, 0xE7, False))
                self.assertEqual((cpu.bank, cpu.memory[0xFFA9], cpu.ime, cpu.sp), (2, 2, True, 0xD000))
                self.assertEqual(cpu.memory[0xFF4A], 0)
                for row in range(18):
                    self.assertEqual(cpu.memory[0x9C00 + row * 32:0x9C00 + row * 32 + 20],
                                     initial_bg[1 + row * 32:1 + row * 32 + 20])
                cpu.call_entry()
                self.assertEqual(cpu.native_states[1][:2], (0x1934, 0xE7))
                self.assertEqual((cpu.memory[0xFF40], cpu.memory[0xFF4A]), (0xC7, 0x88))
                self.assertEqual(cpu.memory[0x9C00:0x9E40], b"\xCD" * build.SNAPSHOT_SIZE)
                self.assertEqual(cpu.memory[build.BACKUP:build.BACKUP + len(patterns)], patterns)
                self.assertEqual(cpu.memory[0x9200:0x9360], self.patterns)
                for column, row, tiles, _ in self.labels:
                    for index, tile in enumerate(tiles):
                        address = 0x9800 + ((row + 1) & 31) * 32 + ((column + index + 4) & 31)
                        self.assertEqual(cpu.memory[address], tile)
                label_writes = [(address, value, lcdc) for address, value, lcdc in cpu.video_writes
                                if 0x9800 <= address < 0x9C00]
                self.assertTrue(label_writes)
                self.assertTrue(all(lcdc == 0xE7 for _, _, lcdc in label_writes))
                self.assertEqual([value for value, _, _ in cpu.lcdc_writes], [0xE7, 0xC7])
                self.assertTrue(all(reads % 2 == 0 and not ime for _, reads, ime in cpu.lcdc_writes))
                cpu.call_exit(0x4B7B)
                self.assertEqual(cpu.memory[0x9200:0x9360], patterns)
                self.assertEqual(cpu.memory[build.BACKUP:build.BACKUP + len(patterns)],
                                 b"\xCD" * len(patterns))
                self.assertEqual((cpu.bank, cpu.memory[0xFFA9], cpu.ime, cpu.sp, cpu.memory[0xC4F2]),
                                 (2, 2, True, 0xD000, 0))

    def test_preconditions_fail_closed_without_overwriting_vram(self):
        for case in ("scratch", "map", "scroll_x", "scroll_y", "window", "display"):
            with self.subTest(case=case):
                cpu = VideoCpu(self.rom)
                if case == "scratch":
                    cpu.memory[0x9FEF] = 0x42
                elif case == "map":
                    cpu.memory[0x99FF] = 0x20
                elif case == "scroll_x":
                    cpu.memory[0xFF43] = 9
                elif case == "scroll_y":
                    cpu.memory[0xFF42] = 1
                elif case == "window":
                    cpu.memory[0xFF4A] = 0
                else:
                    cpu.memory[0xFF40] = 0xD7
                scratch = bytes(cpu.memory[0x9C00:0xA000])
                glyphs = bytes(cpu.memory[0x9200:0x9360])
                cpu.call_frame()
                self.assertEqual(cpu.memory[0xC4F2], build.FAILURE_MARKER)
                self.assertEqual(cpu.memory[0x9C00:0xA000], scratch)
                self.assertFalse(cpu.lcdc_writes)
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9850], 0xCB)
                self.assertEqual(cpu.memory[0x9200:0x9360], glyphs)
                self.assertEqual(cpu.memory[0x9C00:0xA000], scratch)
                cpu.call_exit(0x4B7B)
                self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_existing_status_cache_does_not_replace_original_backup_on_reentry(self):
        cpu = VideoCpu(self.rom)
        original = bytes((index * 13 + 19) & 0xFF for index in range(len(self.patterns)))
        cpu.memory[0x9200:0x9360] = original
        cpu.call_frame()
        cpu.call_entry()
        cpu.memory[0xFF43] = 0x90
        cpu.call_frame()
        self.assertEqual(cpu.memory[0xFF40], 0xC7)
        cpu.call_entry()
        self.assertEqual(cpu.memory[build.BACKUP:build.BACKUP + len(original)], original)
        cpu.call_exit(0x4B96)
        self.assertEqual(cpu.memory[0x9200:0x9360], original)
        self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_late_collision_unmasks_and_reports_failure(self):
        cpu = VideoCpu(self.rom)
        cpu.call_frame()
        self.assertEqual(cpu.memory[0xFF40], 0xE7)
        cpu.memory[0x99FF] = 0x20
        original = bytes(cpu.memory[0x9200:0x9360])
        cpu.call_entry()
        self.assertEqual((cpu.memory[0xFF40], cpu.memory[0xFF4A]), (0xC7, 0x88))
        self.assertEqual(cpu.memory[0x9850], 0xCB)
        self.assertEqual(cpu.memory[0x9200:0x9360], original)
        self.assertEqual(cpu.memory[0x9C00:0xA000], b"\xCD" * 0x400)
        self.assertEqual(cpu.memory[0xC4F2], 0)


if __name__ == "__main__":
    unittest.main()
