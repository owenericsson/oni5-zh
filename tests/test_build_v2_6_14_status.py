import unittest

from scripts import build_v2_6_14_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from test_build_v2_6_10_status import VideoCpu
from test_build_v2_6_8_menu import run_status_entry


class OverworldStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.patch, _ = build.build()
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.labels, cls.patterns = build.status.compile_labels(build.status.previous.OUTPUT_ROM.read_bytes())

    def test_observed_background_tile_is_preserved_and_status_glyphs_restore(self):
        for upper, marker, exit_address in ((0, 0, 0x4B7B), (0x20, 0x80, 0x4B96)):
            with self.subTest(upper=upper, marker=marker, exit_address=exit_address):
                cpu = VideoCpu(self.rom, upper)
                cpu.memory[0xC4F2] = marker
                cpu.memory[0x9800] = 0x16
                cpu.memory[0x9820] = 0x26
                original = bytes((index * 13 + 19) & 0xFF for index in range(len(self.patterns)))
                cpu.memory[0x9270:0x93D0] = original
                cpu.call_frame()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (marker, 0xE7))
                run_status_entry(self.rom, cpu.memory, upper)
                cpu.call_entry()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
                self.assertEqual(cpu.memory[0x9270:0x93D0], self.patterns)
                self.assertEqual(cpu.memory[0x9820], 0x26)
                for column, row, tiles, _ in self.labels:
                    for index, tile in enumerate(tiles):
                        address = 0x9800 + ((row + 1) & 31) * 32 + ((column + index + 4) & 31)
                        expected = tile + 7 if tile != 0xCD else tile
                        self.assertEqual(cpu.memory[address], expected)
                cpu.call_frame()
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9E40:0x9FA0], original)
                cpu.call_exit(exit_address)
                self.assertEqual(cpu.memory[0x9270:0x93D0], original)
                self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_alternate_tile_conflicts_fail_closed_at_initial_and_later_checks(self):
        for tile in range(0x27, 0x3D):
            with self.subTest(tile=tile):
                cpu = VideoCpu(self.rom)
                cpu.memory[0x9BFF] = tile
                cpu.call_frame()
                self.assertEqual(cpu.memory[0xC4F2], 0x95)
                self.assertEqual(cpu.memory[0xFF40], 0xC7)
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9850], 0xCB)
        cpu = VideoCpu(self.rom)
        cpu.call_frame()
        cpu.memory[0x9BFF] = 0x3C
        before = bytes(cpu.memory[0x9270:0x93D0])
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)
        self.assertEqual(cpu.memory[0x9270:0x93D0], before)
        self.assertEqual(cpu.memory[0xFF40], 0xC7)

    def test_party_name_tiles_still_block_menu_restore_snapshot(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0xC4F2] = 0x80
        cpu.memory[0x9820] = 0x26
        cpu.memory[0x98C4:0x98C7] = bytes.fromhex("8F 85 AF")
        cpu.call_frame()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x80, 0xC7))
        run_status_entry(self.rom, cpu.memory)
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)

    def test_observed_3b_map_collision_fails_closed(self):
        cpu = VideoCpu(self.rom, 0x20)
        cpu.memory[0xFF43] = 0xF8
        cpu.memory[0x9ADF] = 0x3B
        original = bytes(cpu.memory[0x9270:0x93D0])
        cpu.call_frame()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x95, 0xC7))
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)
        self.assertEqual(cpu.memory[0x9270:0x93D0], original)

    def test_patch_roundtrip_and_mirror(self):
        status = build.status
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
