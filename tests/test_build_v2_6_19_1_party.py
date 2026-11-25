import io
import shutil
import unittest

from scripts import build_v2_6_19_1_party as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import verify_rom
from test_build_v2_6_9_status_probe import Cpu

try:
    from pyboy import PyBoy
except ImportError:
    PyBoy = None

MENU_TILES = bytes.fromhex("80 81 82 83 84 85 86 87 89 8C 8F 91 93 94")


@unittest.skipUnless(shutil.which("rgbasm") and shutil.which("rgblink"), "RGBDS is not installed")
class FixedPartyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom, cls.patch, _ = build.build()
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()

    def test_patch_roundtrip_and_mirrors(self):
        self.assertTrue(verify_rom(self.rom).passed)
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        for offset, length in (
            (0x9EE6, 3), (0x40001, 2), (0x423AB, 5), (0x424B4, 4),
            (0x42525, 27), (0x43030, 16), (0x47030, 16),
            (0x421F0, 6), (0x461F0, 6), (build.RUNTIME_START, build.RUNTIME_END - build.RUNTIME_START),
        ):
            self.assertEqual(self.rom[offset:offset + length],
                             self.rom[offset + MBC1_MIRROR_OFFSET:offset + MBC1_MIRROR_OFFSET + length])

    def test_title_transfer_matches_parent(self):
        for upper in (0, 0x20):
            with self.subTest(upper=upper):
                cpus = [Cpu(rom, upper) for rom in (self.parent, self.rom)]
                for cpu in cpus:
                    cpu.d, cpu.e = 0x80, 0x5A
                    cpu.memory[0x8000:0x8200] = b"\x77" * 0x200
                    cpu.pc = 0x7CFA
                    cpu.run(0x7D03)
                expected, actual = cpus
                self.assertEqual(actual.memory[0x8000:0x8200], expected.memory[0x8000:0x8200])
                self.assertEqual(actual.registers(), expected.registers())
                self.assertEqual((actual.sp, actual.bank, actual.ime),
                                 (expected.sp, expected.bank, expected.ime))

    @unittest.skipIf(PyBoy is None, "PyBoy is not installed")
    def test_roster_on_first_entry_and_return(self):
        for marker, slot, wrap, upper in ((0x80, 1, False, 0), (0, 3, True, 0x20)):
            with self.subTest(marker=marker, slot=slot, upper=upper):
                result = self.run_roster(marker=marker, slot=slot, wrap=wrap, upper=upper)
                self.assertEqual(result["garo"], bytes.fromhex("A2 A3 CD CD CD"))
                self.assertEqual(result["garo_patterns"], [self.rom[0x44500:0x44510], self.rom[0x44510:0x44520]])
                self.assertEqual(result["main"], bytes.fromhex("89 8C 8F 85 A7"))
                self.assertEqual(result["currency_patterns"], [self.parent[0x42180:0x42190],
                                                                self.parent[0x42190:0x421A0]])
                self.assertEqual(result["marker"], 0x80)
                self.assertEqual(result["registers"], (0x5A, 0x70, 0x19, 0x38, 0, 1, 0xDFFC))

    @unittest.skipIf(PyBoy is None, "PyBoy is not installed")
    def test_unexpected_name_reports_error_without_rewriting_it(self):
        result = self.run_roster(invalid="name")
        self.assertEqual(result["garo"], bytes.fromhex("8E 85 AF CD CD"))
        self.assertEqual(result["error"], 0xCB)

    @unittest.skipIf(PyBoy is None, "PyBoy is not installed")
    def test_other_roster_caller_is_untouched(self):
        for caller in (0x55F1, 0x338A):
            with self.subTest(caller=caller):
                result = self.run_roster(caller=caller)
                self.assertEqual(result["garo"], bytes.fromhex("8F 85 AF CD CD"))
                self.assertEqual(result["main"], bytes.fromhex("89 8C 8F 85 A7"))
                for i, pattern in enumerate(result["all_patterns"]):
                    self.assertEqual(pattern, self.parent[0x42100 + i * 16:0x42110 + i * 16])

    @unittest.skipIf(PyBoy is None, "PyBoy is not installed")
    def test_observed_protagonist_name_remains_unchanged(self):
        p = PyBoy(io.BytesIO(self.rom), window="null", sound_emulated=False)
        try:
            p.set_emulation_speed(0)
            p.tick(5, False)
            p.memory[0xFF50] = 1
            p.memory[0xFF40] = 0
            for address in range(0x9800, 0xA000):
                p.memory[address] = 0xCD
            name = bytes.fromhex("92 8E A0 A7 B1")
            for index, tile in enumerate(name):
                p.memory[0x9862 + index] = tile
                for byte in range(16):
                    p.memory[0x8000 + tile * 16 + byte] = tile ^ byte
            for index, tile in enumerate(bytes.fromhex("8F 85 AF CD CD")):
                p.memory[0x98C2 + index] = tile
            p.memory[0xD006], p.memory[0xD013] = 1, 2
            p.memory[0xFF90], p.memory[0xFF91] = 15, 0
            p.memory[0xD2E3], p.memory[0xD2E4] = 2, 1
            p.memory[0xC4F2], p.memory[0xFFA9] = 0x80, 2
            p.memory[0xDFFC], p.memory[0xDFFD] = 0x8A, 0x49
            p.memory[0xFF40] = 0xC7
            p.memory[0x2000] = 2
            p.register_file.SP, p.register_file.PC = 0xDFFC, 0x5EE6
            results = []

            def on_return(_):
                results.append((
                    bytes(p.memory[0x9862:0x9867]),
                    [bytes(p.memory[0x8000 + tile * 16:0x8010 + tile * 16]) for tile in name],
                    bytes(p.memory[0x98C2:0x98C5]),
                ))

            p.hook_register(2, 0x5EE9, on_return, None)
            p.tick(20, False)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0][0], name)
            self.assertEqual(results[0][1], [bytes(tile ^ byte for byte in range(16)) for tile in name])
            self.assertEqual(results[0][2], bytes.fromhex("A2 A3 CD"))
        finally:
            p.stop(False)

    def run_roster(self, marker=0x80, slot=1, wrap=False, upper=0x20, caller=0x498A, invalid=None):
        if PyBoy is None:
            raise unittest.SkipTest("PyBoy is not installed")
        p = PyBoy(io.BytesIO(self.rom), window="null", sound_emulated=False)
        try:
            p.set_emulation_speed(0)
            p.tick(5, False)
            p.memory[0xFF50] = 1
            p.memory[0xFF40] = 0
            for address in range(0x9800, 0xA000):
                p.memory[address] = 0xCD
            for index, tile in enumerate(MENU_TILES):
                source = (0x42100 if marker else 0x42200) + 16 * index
                for i in range(16):
                    p.memory[0x8000 + 16 * tile + i] = self.parent[source + i]
            scroll_x, scroll_y = (13, 14) if wrap else (0, 0)
            p.memory[0xFF90], p.memory[0xFF91] = scroll_x, scroll_y
            p.memory[0xD2E3], p.memory[0xD2E4] = 2, 1
            x, y = (2 * scroll_x + 4) & 31, (2 * scroll_y + 3) & 31

            def address(row, col):
                return 0x9800 + ((y + row) & 31) * 32 + ((x + col) & 31)

            for i, tile in enumerate(bytes.fromhex("89 8C 8F 85 A7")):
                p.memory[address(0, i)] = tile
            for i, tile in enumerate(bytes.fromhex("8F 85 AF CD CD")):
                p.memory[address(3 * slot, i)] = tile
            if invalid == "name":
                p.memory[address(3 * slot, 0)] = 0x8E
            p.memory[address(11, 11)] = 0x89
            p.memory[address(11, 12)] = 0x8C
            p.memory[0xD006] = 1
            p.memory[0xD006 + 13 * slot] = 2
            p.memory[0xC4F2] = marker
            p.memory[0xFFA9] = 2
            p.memory[0xDFFC] = caller & 0xFF
            p.memory[0xDFFD] = caller >> 8
            p.memory[0xFF40] = 0xC7
            p.memory[0x6000] = 1
            p.memory[0x4000] = upper >> 5
            p.memory[0x2000] = 2
            r = p.register_file
            r.A, r.F, r.B, r.C, r.D, r.E, r.HL = 0x5A, 0x70, 0x19, 0x38, 0xCF, 0x21, 0xD397
            r.SP, r.PC = 0xDFFC, 0x5EE6
            results = []

            def on_return(_):
                def pattern(tile):
                    return bytes(p.memory[0x8000 + 16 * tile:0x8010 + 16 * tile])

                garo = bytes(p.memory[address(3 * slot, i)] for i in range(5))
                results.append({
                    "main": bytes(p.memory[address(0, i)] for i in range(5)),
                    "garo": garo,
                    "garo_patterns": [pattern(tile) for tile in garo[:2]],
                    "currency_patterns": [pattern(0x89), pattern(0x8C)],
                    "all_patterns": [pattern(tile) for tile in MENU_TILES],
                    "error": p.memory[address(10, -1)],
                    "marker": p.memory[0xC4F2],
                    "registers": (r.A, r.F, r.B, r.C, r.D, r.E, r.SP),
                })

            p.hook_register(upper + 2, 0x5EE9, on_return, None)
            p.tick(30, False)
            self.assertEqual(len(results), 1, "runtime did not return to the roster")
            return results[0]
        finally:
            p.stop(False)

    @unittest.skipIf(PyBoy is None, "PyBoy is not installed")
    def test_menu_loader_and_restore_fixed_patterns(self):
        for upper in (0, 0x20):
            with self.subTest(upper=upper):
                p = PyBoy(io.BytesIO(self.rom), window="null", sound_emulated=False)
                try:
                    p.set_emulation_speed(0)
                    p.tick(5, False)
                    p.memory[0xFF50] = 1
                    p.memory[0xFF40] = 0xC7
                    p.memory[0x6000] = 1
                    p.memory[0x4000] = upper >> 5
                    p.memory[0x2000] = 0x10
                    p.memory[0xFF80], p.memory[0xFF81] = 0x18, 0xFE
                    captured = []

                    def on_return(_):
                        if not captured:
                            captured.append((bytes(p.memory[0x8A20:0x8A40]), p.memory[0xC4F2]))
                        p.register_file.PC = 0xFF80

                    p.hook_register(upper + 0x10, 0x6FFF, on_return, None)

                    def execute(address):
                        captured.clear()
                        p.memory[0x2000] = 0x10
                        p.memory[0xDFFC], p.memory[0xDFFD] = 0xFF, 0x6F
                        p.register_file.SP, p.register_file.PC = 0xDFFC, address
                        p.tick(5, False)
                        self.assertTrue(captured, f"routine ${address:04X} did not return")
                        return captured[0]

                    self.assertEqual(execute(0x6300), (self.rom[0x44500:0x44520], 0x80))
                    self.assertEqual(execute(0x6400), (self.rom[0x44520:0x44540], 0))
                finally:
                    p.stop(False)


if __name__ == "__main__":
    unittest.main()
