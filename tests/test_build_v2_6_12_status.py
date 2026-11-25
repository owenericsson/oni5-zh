import unittest

from scripts import build_v2_6_12_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from test_build_v2_6_10_status import VideoCpu
from test_build_v2_6_8_menu import run_status_entry


class StatusReentryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, _, _ = build.build()
        cls.patterns = build.previous.previous.previous.compile_labels(
            build.previous.previous.previous.previous.OUTPUT_ROM.read_bytes()
        )[1]

    def test_menu_marker_is_preserved_until_existing_restore(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0xC4F2] = 0x80
        cpu.memory[0xFF43] = 0xF8
        cpu.memory[0x99F6:0x99F8] = b"\xb2\x98"
        cpu.call_frame()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x80, 0xE7))
        run_status_entry(self.rom, cpu.memory)
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0, 0xE7))
        cpu.call_entry()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
        self.assertEqual(cpu.memory[0x9200:0x9360], self.patterns)

    def test_cached_reentry_masks_and_preserves_backup(self):
        for upper in (0, 0x20):
            with self.subTest(upper=upper):
                cpu = VideoCpu(self.rom, upper)
                cpu.memory[0xFF43] = 0xF8
                original = bytes((index * 13 + 19) & 0xFF for index in range(len(self.patterns)))
                cpu.memory[0x9200:0x9360] = original
                cpu.call_frame()
                cpu.call_entry()
                visible_before = bytes(cpu.memory[0x9800:0x9C00])
                cpu.call_frame()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xE7))
                for row in range(18):
                    for column in range(20):
                        source = row * 32 + ((31 + column) & 31)
                        self.assertEqual(cpu.memory[0x9C00 + row * 32 + column], visible_before[source])
                write_start = len(cpu.video_writes)
                cpu.call_entry()
                label_writes = [entry for entry in cpu.video_writes[write_start:] if entry[0] < 0x9C00]
                self.assertTrue(label_writes)
                self.assertTrue(all(entry[2] == 0xE7 for entry in label_writes))
                self.assertEqual(cpu.memory[0x9E40:0x9FA0], original)
                cpu.call_exit(0x4B7B)
                self.assertEqual(cpu.memory[0x9200:0x9360], original)
                self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_initial_failures_preserve_menu_marker_and_report_error(self):
                for marker in (0, 0x80):
                    for case in ("scroll", "scratch", "backup", "map"):
                        with self.subTest(marker=marker, case=case):
                            cpu = VideoCpu(self.rom)
                            cpu.memory[0xC4F2] = marker
                            if case == "scroll":
                                cpu.memory[0xFF43] |= 1
                            elif case == "scratch":
                                cpu.memory[0x9C00] = 0x42
                            elif case == "backup":
                                cpu.memory[0x9FFF] = 0x42
                            else:
                                cpu.memory[0x9900] = 0x20
                            before = bytes(cpu.memory[0x9C00:0xA000])
                            cpu.call_frame()
                            self.assertEqual(cpu.memory[0xFF40], 0xC7)
                            self.assertEqual(cpu.memory[0xC4F2], 0x80 if marker else 0x95)
                            self.assertEqual(cpu.memory[0x9C00:0xA000], before)
                            if marker:
                                run_status_entry(self.rom, cpu.memory)
                            cpu.call_entry()
                            self.assertEqual(cpu.memory[0x9850], 0xCB)

    def test_patch_scope_and_mirror(self):
        rom, patch, _ = build.build()
        parent = build.previous.OUTPUT_ROM.read_bytes()
        component, _ = build.build_components(
            build.previous.previous.previous.previous.OUTPUT_ROM.read_bytes()
        )
        self.assertEqual(apply_bps_patch(parent, patch), rom)
        offset = build.previous.previous.previous.COMPONENT_START
        self.assertEqual(rom[offset:offset + len(component)],
                                 rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + len(component)])
        allowed = {0x14E, 0x14F}
        allowed.update(range(offset, offset + len(component)))
        allowed.update(range(offset + MBC1_MIRROR_OFFSET, offset + MBC1_MIRROR_OFFSET + len(component)))
        self.assertTrue(all(index in allowed for index, (old, new) in enumerate(zip(parent, rom)) if old != new))

    def test_menu_tile_collision_does_not_discard_menu_backup(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0xC4F2] = 0x80
        cpu.memory[0x9900] = 0x80
        cpu.call_frame()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x80, 0xC7))
        self.assertEqual(cpu.memory[0x9C00:0xA000], b"\xcd" * 0x400)

    def test_cached_failure_preserves_backup_for_exit(self):
        for exit_address in (0x4B7B, 0x4B96):
            with self.subTest(exit=hex(exit_address)):
                cpu = VideoCpu(self.rom)
                original = bytes((index * 13 + 19) & 0xFF for index in range(len(self.patterns)))
                cpu.memory[0x9200:0x9360] = original
                cpu.call_frame()
                cpu.call_entry()
                cpu.memory[0x9C00] = 0x42
                cpu.call_frame()
                self.assertEqual(cpu.memory[0xFF40], 0xC7)
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9850], 0xCB)
                self.assertEqual(cpu.memory[0x9E40:0x9FA0], original)
                cpu.call_exit(exit_address)
                self.assertEqual(cpu.memory[0x9200:0x9360], original)
                self.assertEqual(cpu.memory[0xC4F2], 0)


if __name__ == "__main__":
    unittest.main()
