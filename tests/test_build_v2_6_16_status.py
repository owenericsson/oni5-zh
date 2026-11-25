import unittest

from scripts import build_v2_6_16_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from test_build_v2_6_10_status import VideoCpu
from test_build_v2_6_15_status import VILLAGE_PARTY_MAP
from test_build_v2_6_8_menu import run_status_entry


class DynamicStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.patch, _ = build.build()
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.labels, cls.patterns = build.status.compile_labels(build.status.previous.OUTPUT_ROM.read_bytes())

    def test_observed_village_map_loads_and_restores_selected_tiles(self):
        for upper, marker, exit_address in ((0x20, 0, 0x4B7B), (0, 0x80, 0x4B96)):
            with self.subTest(upper=upper, marker=marker):
                cpu = VideoCpu(self.rom, upper)
                cpu.memory[0xC4F2] = marker
                if marker == 0:
                    cpu.memory[0x9800:0x9C00] = VILLAGE_PARTY_MAP
                else:
                    cpu.memory[0x98FF] = 0x27
                    cpu.memory[0x9ADF] = 0x3B
                before_map = bytes(cpu.memory[0x9800:0x9C00])
                patterns = bytes((index * 13 + 19) & 0xFF for index in range(0x200))
                cpu.memory[0x9200:0x9400] = patterns
                cpu.call_frame()
                self.assertEqual(cpu.memory[0xFF40], 0xE7)
                snapshot = bytes(cpu.memory[0x9C00:0x9E40])
                if marker:
                    run_status_entry(self.rom, cpu.memory, upper)
                cpu.call_entry()
                chosen = bytes(cpu.memory[0x9FA0:0x9FB6])
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
                self.assertEqual(len(set(chosen)), 22)
                self.assertTrue(all(0x20 <= tile < 0x40 and tile not in before_map and tile not in snapshot
                                    for tile in chosen))
                saved = b"".join(patterns[(tile - 0x20) * 16:(tile - 0x20 + 1) * 16] for tile in chosen)
                self.assertEqual(cpu.memory[0x9E40:0x9FA0], saved)
                for index, tile in enumerate(chosen):
                    address = 0x9000 + tile * 16
                    self.assertEqual(cpu.memory[address:address + 16], self.patterns[index * 16:(index + 1) * 16])
                for tile in set(range(0x20, 0x40)) - set(chosen):
                    address = 0x9000 + tile * 16
                    self.assertEqual(cpu.memory[address:address + 16], patterns[(tile - 0x20) * 16:(tile - 0x1F) * 16])
                for column, row, tiles, _ in self.labels:
                    for index, tile in enumerate(tiles):
                        address = 0x9800 + ((row + 1) & 31) * 32 + ((column + index + 4) & 31)
                        self.assertEqual(cpu.memory[address], chosen[tile - 0x20] if tile != 0xCD else tile)
                cpu.call_frame()
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9FA0:0x9FB6], chosen)
                self.assertEqual(cpu.memory[0x9E40:0x9FA0], saved)
                cpu.call_exit(exit_address)
                self.assertEqual(cpu.memory[0x9200:0x9400], patterns)
                self.assertEqual(cpu.memory[0x9E40:0xA000], b"\xCD" * 0x1C0)
                self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_allocator_checks_both_snapshot_and_redrawn_map(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0x9801] = 0x20
        cpu.call_frame()
        cpu.memory[0x9801] = 0xCD
        cpu.memory[0x9BFF] = 0x21
        cpu.call_entry()
        chosen = bytes(cpu.memory[0x9FA0:0x9FB6])
        self.assertNotIn(0x20, chosen)
        self.assertNotIn(0x21, chosen)
        self.assertEqual(cpu.memory[0xC4F2], 0x94)

    def test_insufficient_tiles_clean_up_and_report_error(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0x9B00:0x9B0B] = bytes(range(0x20, 0x2B))
        patterns = bytes(cpu.memory[0x9200:0x9400])
        cpu.call_frame()
        self.assertEqual(cpu.memory[0xFF40], 0xE7)
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)
        self.assertEqual(cpu.memory[0xFF40], 0xC7)
        self.assertEqual(cpu.memory[0x9200:0x9400], patterns)
        self.assertEqual(cpu.memory[0x9C00:0xA000], b"\xCD" * 0x400)
        self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_metadata_conflict_after_snapshot_fails_without_overwriting(self):
        cpu = VideoCpu(self.rom)
        cpu.call_frame()
        cpu.memory[0x9FEF] = 0x42
        patterns = bytes(cpu.memory[0x9200:0x9400])
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)
        self.assertEqual(cpu.memory[0xFF40], 0xC7)
        self.assertEqual(cpu.memory[0x9FEF], 0x42)
        self.assertEqual(cpu.memory[0x9200:0x9400], patterns)

    def test_cached_failure_still_restores_original_tiles_and_metadata(self):
        cpu = VideoCpu(self.rom)
        patterns = bytes((index * 7 + 11) & 0xFF for index in range(0x200))
        cpu.memory[0x9200:0x9400] = patterns
        cpu.call_frame()
        cpu.call_entry()
        chosen = bytes(cpu.memory[0x9FA0:0x9FB6])
        cpu.memory[0x9C00] = 0x42
        cpu.call_frame()
        self.assertEqual(cpu.memory[0xC4F2], 0x96)
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)
        self.assertEqual(cpu.memory[0x9FA0:0x9FB6], chosen)
        cpu.call_exit(0x4B7B)
        self.assertEqual(cpu.memory[0x9200:0x9400], patterns)
        self.assertEqual(cpu.memory[0x9FA0:0xA000], b"\xCD" * 0x60)

    def test_menu_tile_conflict_still_fails_closed(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0xC4F2] = 0x80
        cpu.memory[0x98C4:0x98C7] = bytes.fromhex("8F 85 AF")
        cpu.call_frame()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x80, 0xC7))
        run_status_entry(self.rom, cpu.memory)
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)

    def test_observed_menu_tile_conflict_then_reentry_without_menu_marker(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0xC4F2] = 0x80
        cpu.memory[0x9A49] = 0x94
        list_map = bytes(cpu.memory[0x9800:0x9C00])
        cpu.call_frame()
        run_status_entry(self.rom, cpu.memory)
        cpu.call_entry()
        self.assertEqual((cpu.memory[0x9850], cpu.memory[0xC4F2]), (0xCB, 0))
        cpu.call_exit(0x4B7B)
        cpu.memory[0x9800:0x9C00] = list_map
        cpu.call_frame()
        cpu.call_entry()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
        cpu.call_exit(0x4B7B)
        cpu.memory[0x9800:0x9C00] = list_map
        cpu.call_frame()
        cpu.call_entry()
        self.assertEqual(cpu.memory[0xC4F2], 0x94)

    def test_patch_roundtrip_and_mirror(self):
        component, _ = build.build_components(build.status.previous.OUTPUT_ROM.read_bytes())
        offset = build.status.COMPONENT_START
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
