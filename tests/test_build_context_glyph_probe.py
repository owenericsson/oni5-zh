import json
import unittest
from pathlib import Path

from scripts.build_context_glyph_probe import (
    BACKUP_BYTES,
    CONTEXT_FIRST_CHARACTER_CURSOR,
    CONTEXT_PADDING_BYTES,
    CONTEXT_PATCH_BYTES,
    CONTEXT_RESTORE_CURSOR,
    CONTEXT_SOURCE_BYTES,
    CONTEXT_SOURCE_OFFSET,
    CONTEXT_SOURCE_SIZE,
    ROM_BANK_WINDOW_CPU_START,
    build_context_bank_layout,
    build_context_entry_code,
    build_context_glyph_probe,
    build_restore_helper,
    parse_context_inputs,
)
from scripts.build_mbc1_expansion_probe import (
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
    RESTORE_HELPER_OFFSET,
    RESTORE_HOOK_EXPECTED,
    RESTORE_HOOK_OFFSET,
    RESTORE_HOOK_PATCH,
    build_copy_code,
)
from scripts.rom_checksums import update_checksums, verify_rom


ROOT = Path(__file__).resolve().parents[1]


class BuildContextGlyphProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache_plan = json.loads(
            (ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json").read_text(
                encoding="utf-8"
            )
        )
        cls.encoding = json.loads(
            (ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json").read_text(
                encoding="utf-8"
            )
        )
        cls.glyphs, cls.payload = parse_context_inputs(cls.cache_plan, cls.encoding)

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
        source[CONTEXT_SOURCE_OFFSET:CONTEXT_SOURCE_OFFSET + CONTEXT_SOURCE_SIZE] = (
            CONTEXT_SOURCE_BYTES
        )
        self.source = update_checksums(source)

    def test_context_input_contains_twenty_glyphs_and_a_terminator(self):
        self.assertEqual(len(self.glyphs), 20)
        self.assertEqual(len({glyph.tile for glyph in self.glyphs}), 20)
        self.assertEqual(len(self.payload), CONTEXT_PATCH_BYTES)
        self.assertEqual(self.payload[-1], 0x7F)
        self.assertEqual(
            self.payload[-CONTEXT_PADDING_BYTES - 1:-1],
            bytes([0x4D]) * CONTEXT_PADDING_BYTES,
        )
        self.assertEqual(self.payload[-CONTEXT_PADDING_BYTES - 4:-CONTEXT_PADDING_BYTES - 1],
                         bytes.fromhex("09 4A 3C"))
        self.assertEqual(self.payload.count(0x7D), 2)
        self.assertEqual(self.glyphs[0].character, "伽")
        self.assertEqual(self.glyphs[0].tile - 0x80, self.payload[0])

    def test_context_entry_gate_uses_cursor_after_first_character(self):
        code = build_context_entry_code()

        self.assertEqual(code[19], CONTEXT_FIRST_CHARACTER_CURSOR)

    def test_layout_keeps_loader_patterns_and_restore_helper_disjoint(self):
        pattern_offset, restore_offset, restore_cpu, loader, restore = (
            build_context_bank_layout(self.glyphs)
        )
        pattern_end = pattern_offset + len(self.glyphs) * 16

        self.assertLessEqual(len(loader) + 0x40000, pattern_offset)
        self.assertEqual(pattern_end, restore_offset)
        self.assertEqual(
            restore_cpu,
            ROM_BANK_WINDOW_CPU_START + restore_offset - SOURCE_SIZE,
        )
        self.assertLess(restore_offset + len(restore), SOURCE_SIZE + 0x4000)
        self.assertEqual(BACKUP_BYTES, len(self.glyphs) * 16)

    def test_probe_builds_context_translation_and_restores_twenty_tiles(self):
        probe = build_context_glyph_probe(self.source, self.glyphs, self.payload)
        pattern_offset, restore_offset, restore_cpu, loader, restore = (
            build_context_bank_layout(self.glyphs)
        )

        self.assertEqual(len(probe), EXPANDED_SIZE)
        self.assertTrue(verify_rom(probe).passed)
        self.assertEqual(
            probe[CONTEXT_SOURCE_OFFSET:CONTEXT_SOURCE_OFFSET + CONTEXT_PATCH_BYTES],
            self.payload,
        )
        self.assertEqual(
            probe[
                CONTEXT_SOURCE_OFFSET + CONTEXT_PATCH_BYTES:
                CONTEXT_SOURCE_OFFSET + CONTEXT_SOURCE_SIZE
            ],
            b"",
        )
        self.assertEqual(
            probe[CONTEXT_SOURCE_OFFSET + CONTEXT_PATCH_BYTES],
            self.source[CONTEXT_SOURCE_OFFSET + CONTEXT_SOURCE_SIZE],
        )
        self.assertEqual(
            probe[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)],
            RESTORE_HOOK_PATCH,
        )
        self.assertEqual(
            probe[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(build_restore_helper(restore_cpu))],
            build_restore_helper(restore_cpu),
        )
        self.assertEqual(probe[restore_offset:restore_offset + len(restore)], restore)
        self.assertEqual(
            probe[0x40000:0x40000 + len(loader)],
            loader,
        )
        for index, glyph in enumerate(self.glyphs):
            start = pattern_offset + index * 16
            self.assertEqual(probe[start:start + 16], glyph.pattern)

    def test_loader_and_restore_cover_each_original_tile_pattern(self):
        _, _, _, loader, restore = build_context_bank_layout(self.glyphs)
        expected_backup = b"".join(
            build_copy_code(
                0x8000 + glyph.tile * 16,
                BACKUP_ADDRESS + index * 16,
            )
            for index, glyph in enumerate(self.glyphs)
        )
        expected_restore = b"".join(
            build_copy_code(
                BACKUP_ADDRESS + index * 16,
                0x8000 + glyph.tile * 16,
            )
            for index, glyph in enumerate(self.glyphs)
        )

        self.assertIn(expected_backup, loader)
        self.assertIn(expected_restore, restore)
        self.assertIn(bytes((0xFE, self.glyphs[0].tile)), restore)
        self.assertIn(bytes((0xFE, CONTEXT_RESTORE_CURSOR)), restore)


if __name__ == "__main__":
    unittest.main()
