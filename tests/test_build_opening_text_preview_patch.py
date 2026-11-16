import unittest

from scripts.build_opening_text_preview_patch import (
    ELLIPSIS,
    FONT_SOURCE_SHA256,
    LINE_ADVANCE_OFFSETS,
    OPENING_GATE_MISS_CODE,
    OPENING_LOAD_CURSOR,
    OPENING_POSTLUDE_CODE,
    OPENING_TEXT,
    ORIGINAL_ELLIPSIS_OFFSETS,
    SOURCE_PAYLOAD_SIZE,
    SPACE_CODE,
    TAIL_START_OFFSET,
    TERMINATOR_CODE,
    CachedGlyph,
    build_loader,
    build_opening_entry_code,
    build_opening_mbc1_layout,
    create_glyph_mapping,
    build_opening_restore_helper,
    encode_opening_payload,
    encode_translation_line,
    required_custom_characters,
)


def make_original_payload():
    payload = bytearray([0x4D] * SOURCE_PAYLOAD_SIZE)
    payload[0] = 0x3B
    for offset in ORIGINAL_ELLIPSIS_OFFSETS:
        payload[offset] = 0xD5
    for offset in LINE_ADVANCE_OFFSETS:
        payload[offset] = 0x7D
    payload[0x56] = 0x3C
    payload[TAIL_START_OFFSET:] = bytes([0x7D, 0x7D, 0x7D, TERMINATOR_CODE])
    return bytes(payload)


class BuildOpeningTextPreviewPatchTests(unittest.TestCase):
    def test_load_gate_uses_the_sameboy_confirmed_opening_cursor(self):
        self.assertEqual(OPENING_LOAD_CURSOR, 0x1D)

    def test_opening_entry_loads_once_per_text_cache_lifetime(self):
        entry_code = build_opening_entry_code()
        loader = build_loader(
            [CachedGlyph("远", 0x80, bytes(16))],
            0x4300,
        )

        self.assertEqual(len(entry_code), 31)
        self.assertEqual(entry_code[5], 0x04)
        self.assertEqual(entry_code[12], 0x33)
        self.assertEqual(entry_code[19], 0x1D)
        self.assertEqual(
            entry_code[-9:],
            bytes.fromhex("FA F2 C4 B7 20 3B C3 E0 00"),
        )
        self.assertTrue(loader.endswith(bytes.fromhex("EA F2 C4 E1 D1 C1 06 CD C9")))

    def test_gateway_miss_restores_af_and_replays_original_threshold_branch(self):
        self.assertEqual(
            OPENING_GATE_MISS_CODE,
            bytes.fromhex("F1 FE 60 D2 15 18 C3 07 18"),
        )

    def test_opening_loader_preserves_first_text_code(self):
        self.assertEqual(
            OPENING_POSTLUDE_CODE,
            bytes.fromhex(
                "F3 3E 10 EA 00 20 CD 00 40 3E 04 EA 00 20 FB F1 "
                "3E BB C3 0C 18"
            ),
        )
        self.assertEqual(
            build_opening_restore_helper(0x4567),
            bytes.fromhex(
                "F5 FA AA FF F5 F3 3E 10 EA 00 20 CD 67 45 "
                "F1 EA 00 20 FB F1 21 03 00 C9"
            ),
        )

    def test_mbc1_layout_mirrors_fixed_banks_and_aliases_extension_bank_30(self):
        source_rom = bytearray([0x35]) * 0x40000
        source_rom[0x134:0x150] = bytes(range(0x1C))
        base_target = bytearray([0xA7]) * 0x80000
        base_target[:0x40000] = source_rom
        base_target[0x148] = 0x04
        extension_bank = bytes(index % 0x100 for index in range(0x4000))
        base_target[0x40000:0x44000] = extension_bank

        target = build_opening_mbc1_layout(bytes(base_target), bytes(source_rom))

        self.assertEqual(len(target), 0x100000)
        self.assertEqual(target[0x148], 0x05)
        self.assertEqual(target[0x80000:0x80134], target[:0x134])
        self.assertEqual(target[0x80134:0x80150], source_rom[0x134:0x150])
        self.assertEqual(target[0x80150:0xC0000], target[0x150:0x40000])
        self.assertEqual(target[0x40000:0x44000], extension_bank)
        self.assertEqual(target[0xC0000:0xC4000], extension_bank)

    def test_encodes_confirmed_text_while_preserving_native_punctuation_and_controls(self):
        codes = {
            character: index
            for index, character in enumerate(required_custom_characters(OPENING_TEXT))
        }

        payload = encode_opening_payload(OPENING_TEXT, make_original_payload(), codes)

        self.assertEqual(len(payload), SOURCE_PAYLOAD_SIZE)
        self.assertEqual(payload[0], 0x3B)
        closing_quote_offset = payload.index(0x3C)
        self.assertEqual(closing_quote_offset, 0x4F)
        self.assertEqual(payload[0x4D:0x4F], bytes([0xD5, 0xD5]))
        self.assertTrue(all(value == SPACE_CODE for value in payload[0x50:0x57]))
        self.assertEqual(payload.count(0xD5), 4)
        self.assertEqual(tuple(index for index, value in enumerate(payload) if value == 0x7D),
                         (*LINE_ADVANCE_OFFSETS, 0x57, 0x58, 0x59))
        self.assertEqual(payload[-4:], bytes([0x7D, 0x7D, 0x7D, TERMINATOR_CODE]))

    def test_maps_chinese_glyphs_into_the_audited_tile_pool(self):
        characters = required_custom_characters(OPENING_TEXT)
        glyphs = [
            {
                "character": character,
                "codepoint": f"U+{ord(character):04X}",
                "tile_2bpp_hex": "00 " * 15 + "00",
            }
            for character in characters
        ]
        asset = {
            "schema_version": 1,
            "font": {"source_sha256": FONT_SOURCE_SHA256},
            "glyphs": glyphs,
        }
        pool = {
            "start": "0x80",
            "end_exclusive": "0xC0",
            "count": 34,
            "eligible_count": 44,
            "reserved_native_tile_ids": ["0xBB", "0xBC"],
            "excluded_non_text_map_ids": [
                "0x88", "0x8A", "0x8B", "0x8D", "0x8E", "0x90", "0x92",
                "0x95", "0x98", "0x9C", "0x9D", "0xA1", "0xAB", "0xB1",
                "0xB2", "0xB3", "0xB6", "0xB8",
            ],
        }

        cached_glyphs, code_map = create_glyph_mapping(
            OPENING_TEXT,
            (asset,),
            {"tile_pool": pool},
        )

        self.assertEqual(len(cached_glyphs), 43)
        self.assertEqual(len(code_map), 43)
        self.assertEqual(len({glyph.tile for glyph in cached_glyphs}), 43)
        glyph_tile_by_character = {glyph.character: glyph.tile for glyph in cached_glyphs}
        self.assertEqual(glyph_tile_by_character["活"], 0xBF)
        self.assertEqual(code_map["活"], 0x3F)
        self.assertNotIn(0xBB, glyph_tile_by_character.values())
        self.assertNotIn(0xBC, glyph_tile_by_character.values())
        self.assertNotIn(0xBA, glyph_tile_by_character.values())
        self.assertNotIn(ELLIPSIS, code_map)

    def test_requires_two_character_ellipsis_groups(self):
        with self.assertRaisesRegex(ValueError, "two-character ellipsis"):
            encode_translation_line(ELLIPSIS, {}, 1, 1)


if __name__ == "__main__":
    unittest.main()
