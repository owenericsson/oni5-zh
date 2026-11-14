import json
import unittest
from pathlib import Path

from scripts.compile_translation_encoding import (
    EMPTY_MACRO_PADDING_CODE,
    ELIGIBLE_CUSTOM_TILE_IDS,
    NATIVE_TILE_BY_CHARACTER,
    NON_TEXT_MAP_TILE_IDS,
    PILOT_RECORD_IDS,
    PROVISIONAL_CUSTOM_TILE_IDS,
    SPACE_CODE,
    compile_encoding,
)


ROOT = Path(__file__).resolve().parents[1]


class CompileTranslationEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "data" / "text_manifest.json").read_text())
        cls.glyph_asset = json.loads((ROOT / "data" / "chinese_glyphs.json").read_text())
        cls.plan = compile_encoding(cls.manifest, cls.glyph_asset)
        cls.records = {record["id"]: record for record in cls.plan["records"]}
        cls.translations = {
            record["id"]: record["translation"]["segments"][0]["text"]
            for record in cls.manifest["records"]
            if record["id"] in PILOT_RECORD_IDS
        }

    def test_code_and_tile_assignments_are_unique_and_exclude_reserved_slots(self):
        glyphs = self.plan["custom_glyphs"]
        codes = [int(glyph["input_code"], 16) for glyph in glyphs]
        tiles = [int(glyph["tile"], 16) for glyph in glyphs]
        glyphs_by_character = {glyph["character"]: glyph for glyph in glyphs}
        native_tiles = set(NATIVE_TILE_BY_CHARACTER.values())

        self.assertEqual(len(glyphs), 37)
        self.assertEqual(len(set(codes)), len(glyphs))
        self.assertEqual(len(set(tiles)), len(glyphs))
        self.assertTrue(all(code < 0x60 for code in codes))
        self.assertTrue(
            all(
                int(glyph["input_code"], 16) + 0x80 == int(glyph["tile"], 16)
                for glyph in glyphs
            )
        )
        self.assertEqual(
            {
                character: int(glyphs_by_character[character]["tile"], 16)
                for character in NATIVE_TILE_BY_CHARACTER
            },
            NATIVE_TILE_BY_CHARACTER,
        )
        self.assertTrue(
            all(
                glyphs_by_character[character]["tile_source"] == "native"
                for character in NATIVE_TILE_BY_CHARACTER
            )
        )
        self.assertTrue(
            all(
                glyph["tile_source"] == "custom"
                for glyph in glyphs
                if glyph["character"] not in NATIVE_TILE_BY_CHARACTER
            )
        )
        custom_tiles = [
            int(glyph["tile"], 16)
            for glyph in glyphs
            if glyph["tile_source"] == "custom"
        ]
        self.assertEqual(len(custom_tiles), 34)
        self.assertEqual(custom_tiles, PROVISIONAL_CUSTOM_TILE_IDS)
        self.assertEqual(
            {
                character: int(glyphs_by_character[character]["tile"], 16)
                for character in ("？", "「", "」")
            },
            {"？": 0xCA, "「": 0xBB, "」": 0xBC},
        )
        self.assertEqual(
            {
                character: int(glyphs_by_character[character]["input_code"], 16)
                for character in ("？", "「", "」")
            },
            {"？": 0x4A, "「": 0x3B, "」": 0x3C},
        )
        self.assertEqual(
            ELIGIBLE_CUSTOM_TILE_IDS,
            [
                tile_id
                for tile_id in range(0x80, 0xC0)
                if tile_id not in NON_TEXT_MAP_TILE_IDS | {0xBB, 0xBC}
            ],
        )
        self.assertEqual(len(ELIGIBLE_CUSTOM_TILE_IDS), 44)
        self.assertEqual(PROVISIONAL_CUSTOM_TILE_IDS, ELIGIBLE_CUSTOM_TILE_IDS[:34])
        self.assertFalse(
            any(0xCA <= tile <= 0xCF for tile in tiles if tile not in native_tiles)
        )
        self.assertFalse(any(0xD0 <= tile <= 0xDF for tile in tiles))
        self.assertFalse(any(0xE0 <= tile <= 0xFF for tile in custom_tiles))
        self.assertNotIn(0x4D, codes)

    def test_candidate_restricts_tile_mapping_to_confirmed_dialogue_contexts(self):
        self.assertEqual(
            self.plan["status"],
            "candidate_restricted_to_confirmed_dialogue_contexts",
        )
        self.assertEqual(
            self.plan["tile_allocation_status"],
            "fixed_34_tile_mapping_for_confirmed_contexts_only",
        )
        self.assertEqual(
            self.plan["provisional_custom_tile_pool"],
            {
                "start": "0x80",
                "end_exclusive": "0xC0",
                "count": 34,
                "eligible_count": 44,
                "reserved_native_tile_ids": ["0xBB", "0xBC"],
                "excluded_non_text_map_ids": [
                    f"0x{tile_id:02X}" for tile_id in sorted(NON_TEXT_MAP_TILE_IDS)
                ],
                "status": "restricted_to_confirmed_contexts_not_global",
            },
        )
        self.assertIn("rejected", self.plan["special_codes"]["padding"]["status"])
        self.assertIn("256", self.plan["special_codes"]["padding"]["status"])
        self.assertTrue(
            any("Reserve 0xE0-0xFF globally" in item for item in self.plan["runtime_requirements"])
        )
        self.assertTrue(
            any("native tile reuse" in item for item in self.plan["runtime_requirements"])
        )
        self.assertTrue(
            any("Prefer native tile reuse" in item for item in self.plan["runtime_requirements"])
        )
        self.assertTrue(
            any("zero expansion length" in item for item in self.plan["runtime_requirements"])
        )
        self.assertTrue(
            any("tile_id - 0x80" in item for item in self.plan["runtime_requirements"])
        )

    def test_noticeboard_stream_preserves_its_source_length(self):
        record = self.records["oni5-bank0c-pointer-030e33"]
        encoded = bytes.fromhex(record["encoded_hex"])

        self.assertEqual(record["source_bytes"], 10)
        self.assertEqual(record["encoded_bytes"], record["source_bytes"])
        self.assertEqual(record["padding_count"], 2)
        self.assertEqual(record["padding_code"], f"0x{SPACE_CODE:02X}")
        self.assertEqual(encoded[-3:-1], bytes([SPACE_CODE, SPACE_CODE]))
        self.assertEqual(encoded[-1], 0x7F)

    def test_woman_stream_terminates_immediately_after_translated_text(self):
        record = self.records["oni5-bank0c-pointer-030e8e"]
        encoded = bytes.fromhex(record["encoded_hex"])

        self.assertEqual(record["source_bytes"], 68)
        self.assertEqual(record["encoded_bytes"], 38)
        self.assertEqual(record["patch_end_exclusive"], "0x030EB4")
        self.assertEqual(record["padding_count"], 0)
        self.assertEqual(record["padding_code"], f"0x{SPACE_CODE:02X}")
        self.assertIn("extra scroll", record["padding_status"])
        self.assertNotIn(SPACE_CODE, encoded)
        self.assertEqual(encoded[-1], 0x7F)

    def test_new_dialogue_uses_a_reusable_context_specific_tile_map(self):
        glyph_asset = json.loads(
            (ROOT / "data" / "chinese_glyphs_oni5_bank0c_030ee8.json").read_text()
        )
        plan = compile_encoding(
            self.manifest,
            glyph_asset,
            record_ids=("oni5-bank0c-pointer-030ee8",),
        )

        self.assertEqual(plan["mode"], "context_scoped")
        self.assertEqual(
            plan["tile_allocation_status"],
            "per_context_mapping_reuses_audited_pool",
        )
        self.assertEqual(plan["provisional_custom_tile_pool"]["count"], 20)
        self.assertEqual(len(plan["custom_glyphs"]), 23)
        record = plan["records"][0]
        self.assertEqual(record["id"], "oni5-bank0c-pointer-030ee8")
        self.assertEqual(record["source_bytes"], 32)
        self.assertEqual(record["encoded_bytes"], 32)
        self.assertEqual(record["padding_count"], 6)
        self.assertEqual(record["patch_end_exclusive"], "0x030F08")
        encoded = bytes.fromhex(record["encoded_hex"])
        self.assertEqual(encoded[-1], 0x7F)
        self.assertEqual(encoded[-7:-1], bytes([SPACE_CODE]) * 6)
        self.assertEqual(encoded[-10:-7], bytes.fromhex("09 4A 3C"))

    def test_candidate_streams_decode_back_to_confirmed_text(self):
        code_to_character = {
            int(glyph["input_code"], 16): glyph["character"]
            for glyph in self.plan["custom_glyphs"]
        }
        for record_id, record in self.records.items():
            decoded = []
            encoded = bytes.fromhex(record["encoded_hex"])
            body = encoded[:-(record["padding_count"] + 1)]
            for code in body:
                if code == 0x7F:
                    break
                if code == 0x7D:
                    decoded.append("\n")
                elif code == 0x4D:
                    decoded.append(" ")
                else:
                    decoded.append(code_to_character[code])
            self.assertEqual("".join(decoded), self.translations[record_id])


if __name__ == "__main__":
    unittest.main()
