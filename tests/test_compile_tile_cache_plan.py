import json
import unittest
from pathlib import Path

from scripts.compile_tile_cache_plan import compile_tile_cache_plan


ROOT = Path(__file__).resolve().parents[1]


class CompileTileCachePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = (ROOT / "roms" / "oni5_original.gb").read_bytes()
        cls.candidate = json.loads(
            (ROOT / "data" / "translation_encoding_candidate.json").read_text()
        )
        cls.glyph_asset = json.loads(
            (ROOT / "data" / "chinese_glyphs.json").read_text()
        )
        cls.plan = compile_tile_cache_plan(cls.rom, cls.candidate, cls.glyph_asset)
        cls.entries = {entry["character"]: entry for entry in cls.plan["entries"]}

    def test_plan_contains_custom_patterns_and_exact_original_backups(self):
        custom_entries = [
            entry for entry in self.plan["entries"] if entry["tile_source"] == "custom"
        ]
        self.assertEqual(len(custom_entries), 34)
        self.assertEqual(len({entry["tile"] for entry in custom_entries}), 34)
        for entry in custom_entries:
            self.assertEqual(len(bytes.fromhex(entry["glyph_pattern_2bpp_hex"])), 16)
            self.assertEqual(len(bytes.fromhex(entry["restore_pattern_2bpp_hex"])), 16)
            self.assertIsNotNone(entry["font_output_offset"])

    def test_tile_82_patterns_match_runtime_probe_and_original_dump(self):
        entry = self.entries["中"]
        self.assertEqual(entry["tile"], "0x82")
        self.assertEqual(
            entry["glyph_pattern_2bpp_hex"],
            "10 10 FE FE 92 92 92 92 FE FE 10 10 10 10 00 00",
        )
        self.assertEqual(
            entry["restore_pattern_2bpp_hex"],
            "00 00 00 00 30 30 00 00 38 38 44 44 04 04 38 38",
        )
        self.assertEqual(entry["font_output_offset"], "0x020")

    def test_native_tiles_are_not_scheduled_for_overwrite(self):
        native_entries = [
            entry for entry in self.plan["entries"] if entry["tile_source"] == "native"
        ]
        self.assertEqual(len(native_entries), 3)
        self.assertTrue(
            all(
                entry["glyph_pattern_2bpp_hex"] is None
                and entry["restore_pattern_2bpp_hex"] is None
                for entry in native_entries
            )
        )

    def test_plan_preserves_blocked_status_and_resource_provenance(self):
        self.assertEqual(
            self.plan["status"],
            "blocked_pending_runtime_loader_and_restore_validation",
        )
        self.assertEqual(self.plan["mode"], "fixed_tile_mapping")
        self.assertEqual(self.plan["font_resource"]["decoded_length"], 0x800)
        self.assertEqual(self.plan["tile_pool"], self.candidate["provisional_custom_tile_pool"])


if __name__ == "__main__":
    unittest.main()
