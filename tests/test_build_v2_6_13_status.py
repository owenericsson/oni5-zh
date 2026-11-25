import json
import unittest

from scripts import build_v2_6_13_status as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, build_menu_candidate
from test_build_v2_6_10_status import VideoCpu
from test_build_v2_6_8_menu import run_status_entry


class CountingCpu(VideoCpu):
    def __init__(self, rom, upper=0):
        super().__init__(rom, upper)
        self.map_reads = 0

    def read(self, address):
        if 0x9800 <= address < 0x9C00:
            self.map_reads += 1
        return super().read(address)


class StatusSpeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.patch, _ = build.build()
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        asset = json.loads((build.ROOT / "data/menu_chinese_glyphs.json").read_text())
        cls.menu_tiles = {int(glyph["tile"], 16) for glyph in build_menu_candidate(asset)["custom_glyphs"]}

    def test_exact_lookup_contents_and_parent_patch(self):
        status = build.previous.previous.previous.previous
        v268 = status.previous.OUTPUT_ROM.read_bytes()
        component, labels = build.build_components(v268)
        table = labels["menu_tile_table"] - status._bank11_address(status.COMPONENT_START)
        self.assertEqual(labels["menu_tile_table"] & 0xFF, 0)
        self.assertEqual(component[table:table + 256],
                         bytes(int(value in self.menu_tiles) for value in range(256)))
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        offset = status.COMPONENT_START
        self.assertEqual(self.rom[offset:offset + len(component)],
                         self.rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + len(component)])
        allowed = {0x14E, 0x14F}
        allowed.update(range(offset, offset + len(component)))
        allowed.update(range(offset + MBC1_MIRROR_OFFSET, offset + MBC1_MIRROR_OFFSET + len(component)))
        self.assertTrue(all(index in allowed for index, (old, new) in enumerate(zip(self.parent, self.rom))
                            if old != new))

    def test_all_tile_values_match_previous_safety_decisions(self):
        for value in range(256):
            with self.subTest(tile=value):
                cpus = [VideoCpu(rom, 0x20 if value & 1 else 0) for rom in (self.parent, self.rom)]
                for cpu in cpus:
                    cpu.memory[0xC4F2] = 0x80
                    cpu.memory[0xFF43] = 0xF8
                    cpu.memory[0x9800] = value
                    cpu.call_frame()
                old, new = cpus
                self.assertEqual((new.memory[0xC4F2], new.memory[0xFF40], new.memory[0xFF4A]),
                                 (old.memory[0xC4F2], old.memory[0xFF40], old.memory[0xFF4A]))
                self.assertEqual(new.memory[0x8000:0xA000], old.memory[0x8000:0xA000])
                self.assertEqual((new.registers(), new.bank, new.sp, new.ime, new.calls),
                                 (old.registers(), old.bank, old.sp, old.ime, old.calls))
                forbidden = value in self.menu_tiles or 0x20 <= value < 0x36
                self.assertEqual(new.memory[0xFF40], 0xC7 if forbidden else 0xE7)

    def test_collisions_at_end_of_map_and_normal_other_markers(self):
        for marker in (0, 0x80):
            for value in sorted(self.menu_tiles | set(range(0x20, 0x36))):
                with self.subTest(marker=marker, tile=value):
                    cpu = VideoCpu(self.rom)
                    cpu.memory[0xC4F2] = marker
                    cpu.memory[0x9BFF] = value
                    cpu.call_frame()
                    forbidden = 0x20 <= value < 0x36 or marker == 0x80 and value in self.menu_tiles
                    self.assertEqual(cpu.memory[0xFF40], 0xC7 if forbidden else 0xE7)
        cpu = VideoCpu(self.rom)
        cpu.call_frame()
        cpu.call_entry()
        backup = bytes(cpu.memory[0x9E40:0x9FA0])
        cpu.call_frame()
        self.assertEqual(cpu.memory[0xFF40], 0xE7)
        cpu.call_entry()
        cpu.call_exit(0x4B96)
        self.assertEqual(cpu.memory[0x9200:0x9360], backup)

    def test_existing_guards_and_reentry_failure_match_parent(self):
        for marker in (0, 0x80, 0x94, 0x95, 0x96):
            for case in ("scratch", "backup", "scroll", "window", "display"):
                with self.subTest(marker=marker, case=case):
                    cpus = [VideoCpu(rom) for rom in (self.parent, self.rom)]
                    for cpu in cpus:
                        cpu.memory[0xC4F2] = marker
                        if case == "scratch":
                            cpu.memory[0x9C00] = 0x42
                        elif case == "backup":
                            cpu.memory[0x9FFF] = 0x42
                        elif case == "scroll":
                            cpu.memory[0xFF43] |= 1
                        elif case == "window":
                            cpu.memory[0xFF4A] = 0
                        else:
                            cpu.memory[0xFF40] = 0xD7
                        cpu.call_frame()
                    old, new = cpus
                    self.assertEqual((new.memory[0xC4F2], new.memory[0xFF40], new.memory[0xFF4A]),
                                     (old.memory[0xC4F2], old.memory[0xFF40], old.memory[0xFF4A]))
                    self.assertEqual(new.memory[0x8000:0xA000], old.memory[0x8000:0xA000])
                    self.assertEqual((new.registers(), new.bank, new.sp, new.ime, new.calls),
                                     (old.registers(), old.bank, old.sp, old.ime, old.calls))

    def test_first_entry_reduces_full_map_reads_and_retains_restore(self):
        reads = []
        for rom in (self.parent, self.rom):
            cpu = CountingCpu(rom)
            cpu.memory[0xC4F2] = 0x80
            cpu.memory[0xFF43] = 0xF8
            cpu.call_frame()
            reads.append(cpu.map_reads)
            run_status_entry(rom, cpu.memory)
            cpu.call_entry()
            self.assertEqual((cpu.memory[0xC4F2], cpu.memory[0xFF40]), (0x94, 0xC7))
        self.assertEqual(reads, [0x800 + 360, 0x400 + 360])


if __name__ == "__main__":
    unittest.main()
