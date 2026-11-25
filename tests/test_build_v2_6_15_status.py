import unittest

from scripts import build_v2_6_15_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from test_build_v2_6_10_status import VideoCpu
from test_build_v2_6_8_menu import run_status_entry


VILLAGE_PARTY_MAP = bytes.fromhex("""
52 d0 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4
d4 d4 d4 d4 d1 55 cd cd cd cd cd cd cd cd 64 65
53 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 54 cd cd cd cd cd cd cd cd 74 75
56 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 5b cd cd cd cd cd cd cd cd 0e 0c
5a d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 5b cd cd cd cd cd cd cd cd 0b 0b
0b d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 1b cd cd cd cd cd cd cd cd 16 17
00 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 00 cd cd cd cd cd cd cd cd 26 18
7b d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 00 cd cd cd cd cd cd cd cd 16 19
43 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 45 cd cd cd cd cd cd cd cd 26 27
52 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 55 cd cd cd cd cd cd cd cd 0c 0b
53 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 54 cd cd cd cd cd cd cd cd 0b 0c
56 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 5b cd cd cd cd cd cd cd cd 0b 0b
5a d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 5b d4 d4 d1 cd cd cd cd cd 0b 0b
0b d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 1b cd cd d5 cd cd cd cd cd 0b 01
00 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 00 cd cd d5 cd cd cd cd cd 01 02
64 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 65 cd cd d5 cd cd cd cd cd 08 00
74 d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 75 b2 98 d5 cd cd cd cd cd 0b 08
6d d5 cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd d5 6e d4 d4 d3 cd cd cd cd cd 0b 07
00 d2 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4
d4 d4 d4 d4 d3 00 cd cd cd cd cd cd cd cd 0b 07
cd ac a7 a2 cd a9 af a1 9e 94 ae bc cd cd cd cd
cd cd d5 65 00 00 cd cd cd cd cd cd cd cd 7b d5
d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4 d4
d4 d4 d3 75 00 00 cd cd cd cd cd cd cd cd 43 d2
d0 d4 d4 d4 d4 d1 00 00 00 00 51 52 d0 d4 d4 d4
d4 d1 64 65 cd cd cd cd cd cd cd cd cd cd 52 52
d5 f0 f1 f2 f3 d5 00 00 00 00 50 53 d5 e0 e1 e2
e3 d5 74 75 cd cd cd cd cd cd cd cd cd cd 53 53
d5 f4 f5 f6 f7 d5 62 63 00 00 59 58 d5 e4 e5 e6
e7 d5 64 65 cd cd cd cd cd cd cd cd cd cd 56 3b
d5 f8 f9 fa fb d5 72 73 00 00 59 5a d5 e8 e9 ea
eb d5 74 75 cd cd cd cd cd cd cd cd cd cd 5a 5a
d5 fc fd fe ff d5 00 00 00 00 0a 0b d5 ec ed ee
ef d5 64 65 cd cd cd cd cd cd cd cd cd cd 0b 0b
d2 d4 d4 d4 d4 d3 00 00 00 00 00 00 d2 d4 d4 d4
d4 d3 74 75 cd cd cd cd cd cd cd cd cd cd 00 00
64 65 64 65 64 65 00 00 00 00 64 65 64 65 64 65
64 65 64 65 cd cd cd cd cd cd cd cd cd cd 64 65
74 75 74 75 74 75 00 00 00 00 74 75 74 75 74 75
74 75 74 75 cd cd cd cd cd cd cd cd cd cd 74 75
6d 6e 6d 6e 6d 6e 00 00 00 00 6d 6e 6d 6e 6d 6e
6d 6e 6d 6e cd cd cd cd cd cd cd cd cd cd 6d 6e
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 cd cd cd cd cd cd cd cd cd cd 00 00
cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd
cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd cd
""")


class SplitStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.patch, _ = build.build()
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.labels, cls.patterns = build.previous.status.compile_labels(
            build.previous.status.previous.OUTPUT_ROM.read_bytes()
        )

    def test_observed_3b_and_26_restore_all_patterns_and_leave_gap_untouched(self):
        for upper, marker, exit_address in ((0x20, 0, 0x4B7B), (0, 0x80, 0x4B96)):
            with self.subTest(upper=upper, marker=marker):
                cpu = VideoCpu(self.rom, upper)
                cpu.memory[0xC4F2] = marker
                cpu.memory[0xFF43] = 0xF8
                cpu.memory[0x9820] = 0x26
                cpu.memory[0x9ADF] = 0x3B
                original = bytes((index * 13 + 19) & 0xFF for index in range(0x170))
                cpu.memory[0x9270:0x93E0] = original
                cpu.call_frame()
                self.assertEqual(cpu.memory[0xFF40], 0xE7)
                run_status_entry(self.rom, cpu.memory, upper)
                cpu.call_entry()
                self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
                self.assertEqual(cpu.memory[0x9270:0x93B0], self.patterns[:0x140])
                self.assertEqual(cpu.memory[0x93B0:0x93C0], original[0x140:0x150])
                self.assertEqual(cpu.memory[0x93C0:0x93E0], self.patterns[0x140:])
                self.assertEqual(cpu.memory[0x9E40:0x9FA0], original[:0x140] + original[0x150:])
                self.assertEqual(cpu.memory[0x9ADF], 0x3B)
                for column, row, tiles, _ in self.labels:
                    for index, tile in enumerate(tiles):
                        address = 0x9800 + ((row + 1) & 31) * 32 + ((column + index + 4) & 31)
                        expected = tile + 7 if tile != 0xCD else tile
                        expected += int(expected in (0x3B, 0x3C))
                        self.assertEqual(cpu.memory[address], expected)
                cpu.call_frame()
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9E40:0x9FA0], original[:0x140] + original[0x150:])
                cpu.call_exit(exit_address)
                self.assertEqual(cpu.memory[0x9270:0x93E0], original)
                self.assertEqual(cpu.memory[0xC4F2], 0)

    def test_split_collision_checks_and_late_failure(self):
        allocated = set(range(0x27, 0x3B)) | {0x3C, 0x3D}
        for marker in (0, 0x80):
            for tile in range(0x20, 0x41):
                with self.subTest(marker=marker, tile=tile):
                    cpu = VideoCpu(self.rom)
                    cpu.memory[0xC4F2] = marker
                    cpu.memory[0x9BFF] = tile
                    cpu.call_frame()
                    self.assertEqual(cpu.memory[0xFF40], 0xC7 if tile in allocated else 0xE7)
        for tile in sorted(allocated):
            with self.subTest(late_tile=tile):
                cpu = VideoCpu(self.rom)
                cpu.call_frame()
                cpu.memory[0x9BFF] = tile
                original = bytes(cpu.memory[0x9270:0x93E0])
                cpu.call_entry()
                self.assertEqual(cpu.memory[0x9850], 0xCB)
                self.assertEqual(cpu.memory[0x9270:0x93E0], original)
                self.assertEqual(cpu.memory[0xFF40], 0xC7)

    def test_party_name_conflict_still_fails_closed(self):
        cpu = VideoCpu(self.rom)
        cpu.memory[0xC4F2] = 0x80
        cpu.memory[0x98C4:0x98C7] = bytes.fromhex("8F 85 AF")
        cpu.call_frame()
        self.assertEqual(cpu.memory[0xFF40], 0xC7)
        run_status_entry(self.rom, cpu.memory)
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)

    def test_observed_village_party_tile_27_fails_closed(self):
        cpu = VideoCpu(self.rom, 0x20)
        cpu.memory[0xFF43] = 0x08
        self.assertEqual(len(VILLAGE_PARTY_MAP), 0x400)
        cpu.memory[0x9800:0x9C00] = VILLAGE_PARTY_MAP
        original = bytes(cpu.memory[0x9270:0x93E0])
        cpu.call_frame()
        self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x95, 0xC7))
        cpu.call_entry()
        self.assertEqual(cpu.memory[0x9850], 0xCB)
        self.assertEqual(cpu.memory[0x9270:0x93E0], original)

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
