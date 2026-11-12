import json
import unittest
from pathlib import Path

from scripts.build_mbc1_expansion_probe import (
    BANK_SWITCH_HELPER_OFFSET,
    ENTRY_OFFSET,
    EXPANDED_SIZE,
    GATEWAY_OFFSET,
    POSTLUDE_OFFSET,
    SOURCE_SIZE,
)
from scripts.build_noticeboard_glyph_probe import (
    BACKUP_ADDRESS,
    ENTRY_AREA_SIZE,
    POSTLUDE_AREA_SIZE,
    POSTLUDE_CODE,
    RESTORE_HELPER_OFFSET,
    RESTORE_HOOK_EXPECTED,
    RESTORE_HOOK_OFFSET,
    RESTORE_HOOK_PATCH,
    build_copy_code,
)
from scripts.build_woman_glyph_probe import (
    CUSTOM_BACKUP_BYTES,
    ROM_BANK_WINDOW_CPU_START,
    WOMAN_FIRST_CHARACTER_CURSOR,
    WOMAN_PATCH_BYTES,
    WOMAN_PAYLOAD_SIZE,
    WOMAN_RESTORE_CURSOR,
    WOMAN_SOURCE_BYTES,
    WOMAN_SOURCE_OFFSET,
    build_bank_layout,
    build_entry_code,
    build_restore_helper,
    build_woman_glyph_probe,
    parse_woman_inputs,
)
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildWomanGlyphProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache_plan = json.loads(
            (ROOT / "data" / "tile_cache_plan_candidate.json").read_text(encoding="utf-8")
        )
        cls.encoding = json.loads(
            (ROOT / "data" / "translation_encoding_candidate.json").read_text(encoding="utf-8")
        )
        cls.glyphs, cls.payload = parse_woman_inputs(cls.cache_plan, cls.encoding)

    def setUp(self):
        source = bytearray(SOURCE_SIZE)
        source[0x147] = 0x03
        source[0x148] = 0x03
        source[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = bytes([0xFF]) * ENTRY_AREA_SIZE
        source[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = bytes([0xFF]) * POSTLUDE_AREA_SIZE
        source[GATEWAY_OFFSET:GATEWAY_OFFSET + 4] = bytes.fromhex("FE 60 30 0E")
        source[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)] = (
            RESTORE_HOOK_EXPECTED
        )
        source[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + 0x20] = bytes([0xFF]) * 0x20
        source[WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + WOMAN_PAYLOAD_SIZE] = WOMAN_SOURCE_BYTES
        self.source = update_checksums(source)

    def test_candidate_stream_and_custom_glyph_set_match_confirmed_dialogue(self):
        mappings = {
            value["character"]: value for value in self.encoding["custom_glyphs"]
        }
        self.assertEqual(len(self.payload), WOMAN_PATCH_BYTES)
        self.assertEqual(self.payload[:3], bytes.fromhex("14 17 7D"))
        self.assertEqual(self.payload[-1], 0x7F)
        self.assertEqual(len(self.glyphs), 27)
        self.assertEqual(self.glyphs[0].character, "女")
        self.assertEqual(self.glyphs[0].tile, 0x94)
        self.assertTrue(
            all(
                mappings[glyph.character]["input_code"] == f"0x{glyph.tile - 0x80:02X}"
                for glyph in self.glyphs
            )
        )

    def test_bank_layout_keeps_loader_patterns_and_restore_helper_disjoint(self):
        pattern_offset, restore_offset, restore_cpu, loader, restore = build_bank_layout(
            self.glyphs
        )
        pattern_end = pattern_offset + len(self.glyphs) * 16

        self.assertLessEqual(BANK_SWITCH_HELPER_OFFSET + len(loader), pattern_offset)
        self.assertEqual(pattern_end, restore_offset)
        self.assertEqual(
            restore_cpu,
            ROM_BANK_WINDOW_CPU_START + restore_offset - SOURCE_SIZE,
        )
        self.assertLess(restore_offset + len(restore), SOURCE_SIZE + 0x4000)
        self.assertEqual(len(self.glyphs) * 16, CUSTOM_BACKUP_BYTES)

    def test_builds_verified_probe_with_early_terminator_and_27_patterns(self):
        probe = build_woman_glyph_probe(self.source, self.glyphs, self.payload)
        pattern_offset, restore_offset, restore_cpu, loader, restore = build_bank_layout(
            self.glyphs
        )

        self.assertEqual(len(probe), EXPANDED_SIZE)
        self.assertTrue(verify_rom(probe).passed)
        self.assertEqual(probe[WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + WOMAN_PATCH_BYTES], self.payload)
        self.assertEqual(
            probe[WOMAN_SOURCE_OFFSET + WOMAN_PATCH_BYTES:
                  WOMAN_SOURCE_OFFSET + WOMAN_PAYLOAD_SIZE],
            WOMAN_SOURCE_BYTES[WOMAN_PATCH_BYTES:],
        )
        self.assertEqual(probe[ENTRY_OFFSET:ENTRY_OFFSET + len(build_entry_code())], build_entry_code())
        self.assertEqual(probe[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)], POSTLUDE_CODE)
        self.assertEqual(
            probe[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)],
            RESTORE_HOOK_PATCH,
        )
        self.assertEqual(
            probe[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(build_restore_helper(restore_cpu))],
            build_restore_helper(restore_cpu),
        )
        self.assertEqual(
            probe[BANK_SWITCH_HELPER_OFFSET:BANK_SWITCH_HELPER_OFFSET + len(loader)],
            loader,
        )
        self.assertEqual(probe[restore_offset:restore_offset + len(restore)], restore)
        for index, glyph in enumerate(self.glyphs):
            start = pattern_offset + index * 16
            self.assertEqual(probe[start:start + 16], glyph.pattern)

    def test_load_and_restore_helpers_cover_all_27_original_tiles(self):
        _, _, _, loader, restore = build_bank_layout(self.glyphs)
        expected_backup_code = b"".join(
            build_copy_code(
                0x8000 + glyph.tile * 16,
                BACKUP_ADDRESS + index * 16,
            )
            for index, glyph in enumerate(self.glyphs)
        )
        expected_restore_code = b"".join(
            build_copy_code(
                BACKUP_ADDRESS + index * 16,
                0x8000 + glyph.tile * 16,
            )
            for index, glyph in enumerate(self.glyphs)
        )

        self.assertIn(expected_backup_code, loader)
        self.assertIn(expected_restore_code, restore)
        self.assertIn(bytes((0xFE, self.glyphs[0].tile)), restore)
        self.assertIn(bytes((0xFE, WOMAN_RESTORE_CURSOR)), restore)

    def test_first_character_gate_uses_woman_stream_cursor(self):
        code = build_entry_code()

        self.assertEqual(code[19], WOMAN_FIRST_CHARACTER_CURSOR)
        fallback_target = POSTLUDE_OFFSET + 23
        for branch_offset in (6, 13, 20):
            self.assertEqual(
                ENTRY_OFFSET + branch_offset + 2 + code[branch_offset + 1],
                fallback_target,
            )

    def test_restore_helper_branches_skip_copy_loop_and_preserve_close_cursor(self):
        _, restore_offset, restore_cpu, _, restore = build_bank_layout(self.glyphs)
        common_offset = len(restore) - 4
        self.assertEqual(
            restore_cpu,
            ROM_BANK_WINDOW_CPU_START + restore_offset - SOURCE_SIZE,
        )
        self.assertEqual(restore[8], 0xC2)
        for operand_offset in (9, 17):
            self.assertEqual(
                int.from_bytes(restore[operand_offset:operand_offset + 2], "little"),
                restore_cpu + common_offset,
            )
        self.assertEqual(restore[15], WOMAN_RESTORE_CURSOR)
        self.assertEqual(restore[-4:], bytes.fromhex("F1 D1 C1 C9"))

    def test_rejects_mismatched_original_woman_payload(self):
        source = bytearray(self.source)
        source[WOMAN_SOURCE_OFFSET] ^= 0x01
        source = update_checksums(source)

        with self.assertRaisesRegex(ValueError, "woman source bytes"):
            build_woman_glyph_probe(source, self.glyphs, self.payload)


if __name__ == "__main__":
    unittest.main()
