import unittest

from scripts import build_v2_6_18_title as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import verify_rom
from test_build_v2_6_9_status_probe import Cpu
from test_build_v2_6_10_status import VideoCpu
from test_build_v2_6_17_status import FIRST_MENU_MAP
from test_build_v2_6_8_menu import run_status_entry


class TitleSgbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.original = build.original.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, _ = build.build()

    def test_title_transfer_matches_original_registers_and_vram(self):
        for upper in (0, 0x20):
            with self.subTest(upper=upper):
                cpus = [Cpu(rom, upper) for rom in (self.original, self.rom)]
                for cpu in cpus:
                    cpu.d, cpu.e = 0x80, 0x5A
                    cpu.memory[0x8000:0x8200] = b"\x77" * 0x200
                    cpu.pc = 0x7CFA
                    cpu.run(0x7D03)
                expected, actual = cpus
                self.assertEqual(actual.memory[0x8000:0x8200], expected.memory[0x8000:0x8200])
                self.assertEqual(actual.memory[0x805A:0x810E],
                                 self.original[build.SOURCE:build.SOURCE + build.SOURCE_SIZE])
                self.assertEqual(actual.registers(), expected.registers())
                self.assertEqual((actual.sp, actual.bank, actual.memory[0xFFA9], actual.ime),
                                 (expected.sp, expected.bank, expected.memory[0xFFA9], expected.ime))

    def test_status_entry_and_both_exits_still_restore_patterns(self):
        for upper, exit_address in ((0, 0x4B7B), (0x20, 0x4B96)):
            with self.subTest(upper=upper):
                cpu = VideoCpu(self.rom, upper)
                cpu.memory[0xC4F2] = 0x80
                cpu.memory[0xFF43] = 0x18
                cpu.memory[0x9800:0x9C00] = FIRST_MENU_MAP
                original = bytes((index * 13 + 19) & 0xFF for index in range(0x200))
                cpu.memory[0x9200:0x9400] = original
                cpu.call_frame()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x80, 0xE7))
                run_status_entry(self.rom, cpu.memory, upper)
                cpu.call_entry()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
                cpu.call_exit(exit_address)
                self.assertEqual(cpu.memory[0x9200:0x9400], original)
                self.assertEqual(cpu.memory[0x9E40:0xA000], b"\xCD" * 0x1C0)

    def test_patch_scope_mirrors_and_checksums(self):
        self.assertTrue(verify_rom(self.rom).passed)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        allowed = {0x14E, 0x14F}
        for offset, size in ((build.COPY_HOOK, len(build.NEW_COPY)),
                             (build.COMPONENT, build.HELPER_SIZE + build.SOURCE_SIZE)):
            self.assertEqual(self.rom[offset:offset + size],
                             self.rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + size])
            allowed.update(range(offset, offset + size))
            allowed.update(range(offset + MBC1_MIRROR_OFFSET, offset + MBC1_MIRROR_OFFSET + size))
        self.assertTrue(all(index in allowed for index, (old, new) in enumerate(zip(self.parent, self.rom))
                            if old != new))


if __name__ == "__main__":
    unittest.main()
