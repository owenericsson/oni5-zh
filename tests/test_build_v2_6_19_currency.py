import json
import unittest

from scripts import build_v2_6_19_currency as build
from scripts.apply_bps_patch import apply_bps_patch
from scripts.rom_checksums import verify_rom
from test_build_v2_6_6_dialogue import run_helper
from test_build_v2_6_8_menu import run_status_entry


class CurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = build.previous.OUTPUT_ROM.read_bytes()
        cls.rom, cls.patch, _ = build.build()
        asset = json.loads((build.ROOT / "data/chinese_glyphs_oni5_currency.json").read_text())
        cls.patterns = [bytes.fromhex(glyph["tile_2bpp_hex"]) for glyph in asset["glyphs"]]

    def test_loader_and_status_restore_in_both_mirrors(self):
        for upper in (0, 0x20):
            with self.subTest(upper=upper):
                memory = bytearray(0x10000)
                run_helper(self.rom, 0x42500, memory, upper)
                self.assertEqual(memory[0xC4F2], 0x80)
                self.assertEqual(memory[0x8890:0x88A0], self.patterns[0])
                self.assertEqual(memory[0x88C0:0x88D0], self.patterns[1])
                self.assertEqual(self.rom[build.CURRENCY_TEXT:build.CURRENCY_TEXT + 6],
                                 bytes.fromhex("09 0C 4D 4D 4D 7F"))
                run_status_entry(self.rom, memory, upper)
                self.assertEqual(memory[0xC4F2], 0)
                self.assertEqual(memory[0x8890:0x88A0],
                                 self.parent[0x42280:0x42290])
                self.assertEqual(memory[0x88C0:0x88D0],
                                 self.parent[0x42290:0x422A0])

    def test_patch_is_limited_and_reversible(self):
        self.assertEqual(apply_bps_patch(self.parent, self.patch), self.rom)
        self.assertTrue(verify_rom(self.rom).passed)
        allowed = {0x14E, 0x14F}
        for mirror in (0, build.MBC1_MIRROR_OFFSET):
            allowed.update(range(0x42180 + mirror, 0x421A0 + mirror))
        for index, (old, new) in enumerate(zip(self.parent, self.rom)):
            if old != new:
                self.assertIn(index, allowed)


if __name__ == "__main__":
    unittest.main()
