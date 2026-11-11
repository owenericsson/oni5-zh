import unittest

from scripts.export_chinese_glyphs import (
    collect_required_characters,
    encode_glyph,
    export_glyphs,
    parse_bdf,
)


SAMPLE_BDF = b"""STARTFONT 2.1
FONT sample
CHARS 2
STARTCHAR uni4E2D
ENCODING 20013
DWIDTH 8 0
BBX 7 7 0 -1
BITMAP
10
FE
92
92
FE
10
10
ENDCHAR
STARTCHAR uniFF01
ENCODING 65281
DWIDTH 8 0
BBX 1 7 2 -1
BITMAP
80
80
80
80
80
80
80
ENDCHAR
ENDFONT
"""


class ExportChineseGlyphTests(unittest.TestCase):
    def test_converts_known_bdf_glyph_to_game_boy_2bpp(self):
        records = parse_bdf(SAMPLE_BDF)

        self.assertEqual(
            encode_glyph(records[0x4E2D], "中"),
            bytes.fromhex(
                "10 10 FE FE 92 92 92 92 FE FE 10 10 10 10 00 00"
            ),
        )

    def test_places_narrow_glyph_using_bdf_offsets(self):
        records = parse_bdf(SAMPLE_BDF)

        self.assertEqual(
            encode_glyph(records[0xFF01], "！"),
            bytes.fromhex(
                "20 20 20 20 20 20 20 20 20 20 20 20 20 20 00 00"
            ),
        )

    def test_collects_only_non_whitespace_from_confirmed_translations(self):
        manifest = {
            "records": [
                {
                    "id": "target",
                    "translation": {
                        "status": "confirmed",
                        "segments": [{"text": "中 中\n！"}],
                    }
                },
                {
                    "id": "draft",
                    "translation": {
                        "status": "draft",
                        "segments": [{"text": "不"}],
                    }
                },
            ]
        }

        self.assertEqual(collect_required_characters(manifest), ["中", "！"])

    def test_collects_only_selected_confirmed_records(self):
        manifest = {
            "records": [
                {
                    "id": "target",
                    "translation": {
                        "status": "confirmed",
                        "segments": [{"text": "中"}],
                    },
                },
                {
                    "id": "unrelated",
                    "translation": {
                        "status": "confirmed",
                        "segments": [{"text": "不"}],
                    },
                },
            ]
        }

        self.assertEqual(
            collect_required_characters(manifest, ["target"]),
            ["中"],
        )

    def test_rejects_missing_selected_record(self):
        with self.assertRaisesRegex(ValueError, "missing selected record"):
            collect_required_characters({"records": []}, ["missing"])

    def test_rejects_unconfirmed_selected_record(self):
        manifest = {
            "records": [
                {
                    "id": "draft",
                    "translation": {
                        "status": "draft",
                        "segments": [{"text": "中"}],
                    },
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "selected translation must be confirmed"):
            collect_required_characters(manifest, ["draft"])

    def test_exports_glyph_asset_with_source_provenance(self):
        manifest = {
            "records": [
                {
                    "translation": {
                        "status": "confirmed",
                        "segments": [{"text": "中！"}],
                    }
                }
            ]
        }

        asset = export_glyphs(SAMPLE_BDF, manifest)

        self.assertEqual(len(asset["glyphs"]), 2)
        self.assertEqual(asset["font"]["license"], "SIL Open Font License 1.1")
        self.assertEqual(asset["glyphs"][0]["codepoint"], "U+4E2D")


if __name__ == "__main__":
    unittest.main()
