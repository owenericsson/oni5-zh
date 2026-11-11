import json
import unittest
from pathlib import Path

from scripts.compile_translation_encoding import (
    EMPTY_MACRO_PADDING_CODE,
    PILOT_RECORD_IDS,
    SPACE_CODE,
    TILE_IDS,
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

        self.assertEqual(len(glyphs), 37)
        self.assertEqual(len(set(codes)), len(glyphs))
        self.assertEqual(len(set(tiles)), len(glyphs))
        self.assertEqual(tiles, TILE_IDS[:len(glyphs)])
        self.assertFalse(any(0xD0 <= tile <= 0xDF for tile in tiles))
        self.assertNotIn(0x4D, codes)

    def test_candidate_keeps_context_runtime_validation_pending(self):
        self.assertEqual(self.plan["status"], "pending_context_runtime_probe")
        self.assertIn("rejected", self.plan["special_codes"]["padding"]["status"])
        self.assertIn("256", self.plan["special_codes"]["padding"]["status"])
        self.assertTrue(
            any("zero expansion length" in item for item in self.plan["runtime_requirements"])
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

    def test_woman_stream_uses_verified_space_padding_without_moving_terminator(self):
        record = self.records["oni5-bank0c-pointer-030e8e"]
        encoded = bytes.fromhex(record["encoded_hex"])

        self.assertEqual(record["source_bytes"], 68)
        self.assertEqual(record["encoded_bytes"], record["source_bytes"])
        self.assertEqual(record["padding_count"], 30)
        self.assertEqual(record["padding_code"], f"0x{SPACE_CODE:02X}")
        self.assertIn("verified", record["padding_status"])
        self.assertEqual(encoded[-31:-1], bytes([SPACE_CODE]) * 30)
        self.assertEqual(encoded[-1], 0x7F)

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
