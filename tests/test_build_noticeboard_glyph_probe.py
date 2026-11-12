import unittest

from scripts.build_mbc1_expansion_probe import (
    BANK_SWITCH_HELPER_OFFSET,
    EXPANDED_SIZE,
    GATEWAY_OFFSET,
    SOURCE_SIZE,
)
from scripts.build_noticeboard_glyph_probe import (
    BACKUP_ADDRESS,
    ENTRY_CODE,
    ENTRY_OFFSET,
    GLYPH_PATTERN_OFFSET,
    NOTICEBOARD_PADDING_CODE,
    NOTICEBOARD_RECORD_ID,
    NOTICEBOARD_SOURCE_BYTES,
    NOTICEBOARD_SOURCE_OFFSET,
    NOTICEBOARD_TEXT,
    NOTICEBOARD_TERMINATOR,
    POSTLUDE_CODE,
    POSTLUDE_OFFSET,
    RESTORE_BANK_HELPER_CPU_ADDRESS,
    RESTORE_BANK_HELPER_OFFSET,
    RESTORE_HELPER,
    RESTORE_HELPER_OFFSET,
    RESTORE_HOOK_EXPECTED,
    RESTORE_HOOK_OFFSET,
    RESTORE_HOOK_PATCH,
    CachedGlyph,
    build_loader_helper,
    build_noticeboard_glyph_probe,
    build_restore_bank_helper,
    parse_noticeboard_inputs,
    tile_vram_address,
)
from scripts.rom_checksums import update_checksums, verify_rom


class BuildNoticeboardGlyphProbeTests(unittest.TestCase):
    def setUp(self):
        source = bytearray(SOURCE_SIZE)
        source[0x147] = 0x03
        source[0x148] = 0x03
        source[0xA0:0xC0] = bytes([0xFF]) * 0x20
        source[0xE0:0x100] = bytes([0xFF]) * 0x20
        source[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(RESTORE_HELPER)] = (
            bytes([0xFF]) * len(RESTORE_HELPER)
        )
        source[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)] = (
            RESTORE_HOOK_EXPECTED
        )
        source[GATEWAY_OFFSET:GATEWAY_OFFSET + 4] = bytes.fromhex("FE 60 30 0E")
        source[
            NOTICEBOARD_SOURCE_OFFSET:
            NOTICEBOARD_SOURCE_OFFSET + len(NOTICEBOARD_SOURCE_BYTES)
        ] = NOTICEBOARD_SOURCE_BYTES
        self.source = update_checksums(source)
        self.glyphs = [
            CachedGlyph(character, tile, bytes([index + 1]) * 16)
            for index, (character, tile) in enumerate(
                zip(NOTICEBOARD_TEXT, (0xA5, 0xAD, 0xA4, 0x86, 0x9A, 0x82, 0xA3))
            )
        ]
        self.payload = bytes(glyph.tile - 0x80 for glyph in self.glyphs) + bytes(
            [NOTICEBOARD_PADDING_CODE, NOTICEBOARD_PADDING_CODE, NOTICEBOARD_TERMINATOR]
        )

    def make_inputs(self):
        mappings = [
            {
                "character": glyph.character,
                "input_code": f"0x{glyph.tile - 0x80:02X}",
                "tile": f"0x{glyph.tile:02X}",
                "tile_source": "custom",
            }
            for glyph in self.glyphs
        ]
        return (
            {
                "schema_version": 1,
                "source_rom_sha256": (
                    "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
                ),
                "font_resource": {"decoded_sha256": "0" * 64},
                "entries": [
                    {
                        "character": glyph.character,
                        "tile": f"0x{glyph.tile:02X}",
                        "tile_source": "custom",
                        "glyph_pattern_2bpp_hex": glyph.pattern.hex(" ").upper(),
                    }
                    for glyph in self.glyphs
                ],
            },
            {
                "schema_version": 1,
                "custom_glyphs": mappings,
                "records": [
                    {
                        "id": NOTICEBOARD_RECORD_ID,
                        "decoded_text": NOTICEBOARD_TEXT,
                        "source_start": "0x030E33",
                        "source_end_exclusive": "0x030E3D",
                        "source_bytes": 10,
                        "encoded_bytes": 10,
                        "padding_count": 2,
                        "encoded_hex": self.payload.hex(" ").upper(),
                    }
                ],
            },
        )

    def test_builds_verified_512_kib_probe_and_patches_confirmed_text(self):
        probe = build_noticeboard_glyph_probe(self.source, self.glyphs, self.payload)

        self.assertEqual(len(probe), EXPANDED_SIZE)
        self.assertTrue(verify_rom(probe).passed)
        self.assertEqual(
            probe[NOTICEBOARD_SOURCE_OFFSET:NOTICEBOARD_SOURCE_OFFSET + len(self.payload)],
            self.payload,
        )
        self.assertEqual(self.source[0x148], 0x03)

    def test_installs_context_hook_loader_and_all_glyph_patterns(self):
        probe = build_noticeboard_glyph_probe(self.source, self.glyphs, self.payload)
        loader = build_loader_helper(self.glyphs)
        restore = build_restore_bank_helper(self.glyphs)

        self.assertEqual(probe[GATEWAY_OFFSET:GATEWAY_OFFSET + 4], bytes.fromhex("C3 A0 00 00"))
        self.assertEqual(probe[ENTRY_OFFSET:ENTRY_OFFSET + len(ENTRY_CODE)], ENTRY_CODE)
        self.assertEqual(
            probe[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)],
            POSTLUDE_CODE,
        )
        self.assertEqual(
            probe[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)],
            RESTORE_HOOK_PATCH,
        )
        self.assertEqual(
            probe[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(RESTORE_HELPER)],
            RESTORE_HELPER,
        )
        self.assertEqual(
            probe[RESTORE_BANK_HELPER_OFFSET:RESTORE_BANK_HELPER_OFFSET + len(restore)],
            restore,
        )
        self.assertEqual(probe[BANK_SWITCH_HELPER_OFFSET:BANK_SWITCH_HELPER_OFFSET + len(loader)], loader)
        for index, glyph in enumerate(self.glyphs):
            start = GLYPH_PATTERN_OFFSET + index * 16
            self.assertEqual(probe[start:start + 16], glyph.pattern)
        self.assertEqual(probe[0x30E33:0x30E3D], self.payload)

    def test_loader_backs_up_and_loads_every_selected_tile(self):
        loader = build_loader_helper(self.glyphs)

        self.assertEqual(len(self.glyphs), 7)
        for index, glyph in enumerate(self.glyphs):
            self.assertIn(
                bytes.fromhex("01 10 00 CD 21 05"),
                loader,
            )
            self.assertEqual(
                tile_vram_address(glyph.tile),
                0x8000 + glyph.tile * 16,
            )
            self.assertIn(
                bytes(
                    (
                        0x21,
                        tile_vram_address(glyph.tile) & 0xFF,
                        tile_vram_address(glyph.tile) >> 8,
                        0x11,
                        (BACKUP_ADDRESS + index * 16) & 0xFF,
                        (BACKUP_ADDRESS + index * 16) >> 8,
                        0x01,
                        0x10,
                        0x00,
                        0xCD,
                        0x21,
                        0x05,
                    )
                ),
                loader,
            )
        self.assertEqual(loader[-9:], bytes.fromhex("3E A5 EA F2 C4 E1 D1 C1 C9"))

    def test_restore_hook_gates_on_loaded_tile_and_noticeboard_end_cursor(self):
        helper = build_restore_bank_helper(self.glyphs)
        self.assertEqual(RESTORE_HOOK_EXPECTED, bytes.fromhex("21 03 00"))
        self.assertEqual(RESTORE_HOOK_PATCH, bytes.fromhex("CD 61 00"))
        self.assertIn(bytes.fromhex("CD 70 41"), RESTORE_HELPER)
        self.assertEqual(
            RESTORE_BANK_HELPER_OFFSET,
            SOURCE_SIZE + 0x170,
        )
        self.assertLess(
            RESTORE_BANK_HELPER_OFFSET + len(helper),
            GLYPH_PATTERN_OFFSET + 7 * 16 + 0x100,
        )
        common_offset = len(helper) - 4
        for branch_offset in (8, 15):
            displacement = helper[branch_offset + 1]
            if displacement >= 0x80:
                displacement -= 0x100
            self.assertEqual(
                RESTORE_BANK_HELPER_CPU_ADDRESS + branch_offset + 2 + displacement,
                RESTORE_BANK_HELPER_CPU_ADDRESS + common_offset,
            )
        self.assertEqual(helper[-4:], bytes.fromhex("F1 D1 C1 C9"))

    def test_context_branches_bypass_loader_outside_noticeboard_first_character(self):
        self.assertEqual(
            ENTRY_CODE,
            bytes.fromhex(
                "F5 FA AA FF FE 0C 20 4F FA AE FF FE 0E 20 48 "
                "FA AD FF FE 34 20 41 06 CD C3 E0 00"
            ),
        )
        fallback_target = POSTLUDE_OFFSET + 23
        for branch_offset in (6, 13, 20):
            branch_target = (
                ENTRY_OFFSET + branch_offset + 2 + ENTRY_CODE[branch_offset + 1]
            )
            self.assertEqual(branch_target, fallback_target)

    def test_reads_all_seven_patterns_from_cache_plan_and_direct_encoding(self):
        plan, encoding = self.make_inputs()

        glyphs, payload = parse_noticeboard_inputs(plan, encoding)

        self.assertEqual(glyphs, self.glyphs)
        self.assertEqual(payload, self.payload)

    def test_rejects_non_direct_code_mapping(self):
        plan, encoding = self.make_inputs()
        encoding["custom_glyphs"][0]["input_code"] = "0x2E"

        with self.assertRaisesRegex(ValueError, "direct input_code"):
            parse_noticeboard_inputs(plan, encoding)

    def test_rejects_invalid_glyph_pattern_length(self):
        with self.assertRaisesRegex(ValueError, "must contain 16 bytes"):
            build_noticeboard_glyph_probe(self.source, self.glyphs[:-1] + [
                CachedGlyph("村", 0xA3, self.glyphs[-1].pattern[:-1])
            ], self.payload)


if __name__ == "__main__":
    unittest.main()
