import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StatusTextAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = (ROOT / "roms/oni5_v2_6_8_status_fix.gb").read_bytes()
        cls.manifest = json.loads((ROOT / "data/status_text_manifest.json").read_text())
        cls.glyphs = json.loads((ROOT / "data/chinese_glyphs_oni5_status.json").read_text())

    def test_labels_match_parent_and_fit_without_overlapping(self):
        self.assertEqual(hashlib.sha256(self.rom).hexdigest(), self.manifest["parent_rom_sha256"])
        occupied = set()
        for record in self.manifest["records"]:
            with self.subTest(record=record["id"]):
                source = record["source"]
                start = int(source["start"], 16)
                end = int(source["end_exclusive"], 16)
                raw = bytes.fromhex(source["raw_hex"])
                text = record["translation"]["segments"][0]["text"]
                self.assertEqual(end - start, len(raw))
                self.assertLessEqual(len(text), len(raw))
                self.assertEqual(self.rom[start:end], raw)
                self.assertEqual(self.rom[0x80000 + start:0x80000 + end], raw)
                self.assertFalse(occupied.intersection(range(start, end)))
                occupied.update(range(start, end))

    def test_glyph_asset_covers_exact_confirmed_translations(self):
        characters = {
            character
            for record in self.manifest["records"]
            for segment in record["translation"]["segments"]
            for character in segment["text"]
        }
        glyphs = self.glyphs["glyphs"]
        self.assertEqual(characters, {glyph["character"] for glyph in glyphs})
        self.assertEqual(len(glyphs), len(characters))
        for glyph in glyphs:
            pattern = bytes.fromhex(glyph["tile_2bpp_hex"])
            self.assertEqual(len(pattern), 16)
            self.assertTrue(all(pattern[i] == pattern[i + 1] for i in range(0, 16, 2)))

    def test_positions_match_observed_status_map(self):
        observed = {
            "status-level": (0x9851, "8E 90"),
            "status-next-level": (0x9889, "9A 8F A1 8E 90 A7 9B"),
            "status-health": (0x98C5, "98 8A B0 87 90"),
            "status-spirit": (0x9905, "96 8A 94 B6 B0 87 90"),
            "status-strength": (0x9944, "B4 B6 B0 87 90"),
            "status-attack": (0x994E, "92 8B 91 8F"),
            "status-endurance": (0x9984, "98 8A 8F 86 8B"),
            "status-defense": (0x998E, "A6 8B 8F 87"),
            "status-agility": (0x99C4, "A3 B6 94 87 8B"),
            "status-speed": (0x99CE, "95 A2 AC 93"),
            "status-magic-resistance": (0x9A04, "A7 9B 8A 92 8B"),
            "status-intelligence": (0x9A0E, "99 B0 87 90"),
        }
        for record in self.manifest["records"]:
            with self.subTest(record=record["id"]):
                position = record["position"]
                column = (2 * 1 + position["column"] + 2) & 31
                row = (2 * 0 + position["row"] + 1) & 31
                address = 0x9800 + row * 32 + column
                expected_address, expected_hex = observed[record["id"]]
                self.assertEqual(address, expected_address)
                base_tiles = bytes(
                    code + (0x2E if code >= 0x60 else 0x80)
                    for code in bytes.fromhex(record["source"]["raw_hex"])
                )
                self.assertEqual(base_tiles, bytes.fromhex(expected_hex))


if __name__ == "__main__":
    unittest.main()
