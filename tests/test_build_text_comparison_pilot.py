import json
import unittest
from pathlib import Path

from scripts.build_context_glyph_probe import (
    CONTEXT_FIRST_CHARACTER_CURSOR,
    CONTEXT_RESTORE_CURSOR,
)
from scripts.build_mbc1_expansion_probe import (
    ENTRY_OFFSET,
    SOURCE_SIZE,
)
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_noticeboard_glyph_probe import CachedGlyph
from scripts.build_rom import apply_patch_manifest
from scripts.build_text_comparison_pilot import (
    ENTRY_BANKS,
    MENU_EXPANDED_SIZE,
    OPENING_GATE_MISS_CODE,
    OPENING_SOURCE_END,
    OPENING_RETURN_CODE,
    OPENING_SOURCE_OFFSET,
    PRACTICE_FIRST_CURSOR,
    PRACTICE_RETURN_CODE,
    PRACTICE_RESTORE_CURSOR,
    PRACTICE_SOURCE_BYTES,
    PRACTICE_SOURCE_END,
    PRACTICE_SOURCE_OFFSET,
    RESTORE_HELPER_OFFSET,
    RESTORE_HELPER_SIZE,
    build_comparison_pilot,
    build_context_bank_layout,
    build_contexts,
    build_entry_code,
    build_postlude,
    create_patch_manifest,
    vertical_expand_pattern,
)
from scripts.build_two_text_pilot import (
    WOMAN_FIRST_CURSOR,
    WOMAN_RESTORE_CURSOR,
)
from scripts.rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildTextComparisonPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "roms" / "oni5_original.gb").read_bytes()
        cls.values = (
            json.loads((ROOT / "data" / "text_manifest.json").read_text(encoding="utf-8")),
            json.loads(
                (ROOT / "data" / "chinese_glyphs_oni5_bank04_01330d.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads((ROOT / "data" / "chinese_glyphs.json").read_text(encoding="utf-8")),
            json.loads(
                (ROOT / "data" / "chinese_glyphs_oni5_bank24_01348f.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads(
                (ROOT / "data" / "tile_cache_plan_candidate.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads(
                (ROOT / "data" / "translation_encoding_candidate.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads(
                (ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads(
                (ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json").read_text(
                    encoding="utf-8"
                )
            ),
        )

    def build_contexts(self, vertical_8=False):
        return build_contexts(self.source, *self.values, vertical_8)

    def test_practice_translation_is_fixed_length_and_keeps_native_controls(self):
        contexts, _ = self.build_contexts()
        practice = next(context for context in contexts if context.record_id == "practice")

        self.assertEqual(len(practice.payload), len(PRACTICE_SOURCE_BYTES))
        self.assertEqual(practice.payload[0], 0x3B)
        self.assertEqual(practice.payload[16], 0x7D)
        self.assertEqual(practice.payload[26], 0x3C)
        self.assertEqual(practice.first_cursor, PRACTICE_FIRST_CURSOR)
        self.assertEqual(practice.restore_cursor, PRACTICE_RESTORE_CURSOR)
        self.assertEqual(practice.marker, practice.glyphs[0].tile)
        self.assertEqual(practice.return_code, PRACTICE_RETURN_CODE)
        self.assertEqual(practice.payload[6:16], bytes([0x4D]) * 10)
        self.assertEqual(practice.payload[22:26], bytes([0x4D]) * 4)

    def test_vertical_expansion_adds_ink_rows_without_changing_tile_width(self):
        rows = [bytes((0x00, 0x00))]
        rows.extend(bytes((0x18 + (index & 1) * 0x04, 0x18 + (index & 1) * 0x04)) for index in range(7))
        pattern = b"".join(rows)

        expanded = vertical_expand_pattern(pattern)
        active_rows = [
            expanded[offset:offset + 2]
            for offset in range(0, len(expanded), 2)
            if expanded[offset] | expanded[offset + 1]
        ]

        self.assertEqual(len(expanded), 16)
        self.assertEqual(len(active_rows), 8)
        self.assertTrue(all(row[0] == row[1] for row in active_rows))
        self.assertEqual(vertical_expand_pattern(bytes(16)), bytes(16))

    def test_all_five_load_and_restore_signatures_are_dispatched(self):
        contexts, _ = self.build_contexts()
        layout = build_context_bank_layout(contexts)
        opening_cache_guard = bytes.fromhex("FA F2 C4 B7 28 02 AF C9")
        self.assertIn(opening_cache_guard, layout.load_dispatcher)

        for context in contexts:
            load_signature = bytes(
                (
                    0xFA, 0xAA, 0xFF, 0xFE, context.bank,
                    0x20, 0x00,
                    0xFA, 0xAE, 0xFF, 0xFE, context.pointer_high,
                )
            )
            self.assertIn(load_signature[:5], layout.load_dispatcher)
            self.assertIn(bytes((0xFE, context.first_cursor)), layout.load_dispatcher)
            self.assertIn(bytes((0xFE, context.marker)), layout.restore_dispatcher)
            self.assertIn(bytes((0xFE, context.restore_cursor)), layout.restore_dispatcher)

        self.assertEqual(contexts[0].marker, contexts[0].glyphs[0].tile)
        self.assertEqual({context.bank for context in contexts}, set(ENTRY_BANKS))
        self.assertEqual(contexts[0].return_code, OPENING_RETURN_CODE)
        self.assertEqual(contexts[0].loader_return_b, 0xCD)
        self.assertEqual(contexts[1].marker, contexts[1].glyphs[0].tile)
        self.assertEqual(contexts[1].return_code, PRACTICE_RETURN_CODE)
        self.assertNotEqual(contexts[0].marker, contexts[0].return_code)
        self.assertTrue(
            layout.loaders[0].endswith(
                bytes.fromhex("EA F0 C4 E1 D1 C1 06 CD C9")
            )
        )
        self.assertTrue(
            layout.loaders[1].endswith(bytes.fromhex("EA F0 C4 E1 D1 C1 C9"))
        )
        self.assertNotEqual(contexts[0].first_cursor, contexts[1].first_cursor)
        self.assertEqual(contexts[3].first_cursor, WOMAN_FIRST_CURSOR)
        self.assertEqual(contexts[3].restore_cursor, WOMAN_RESTORE_CURSOR)
        self.assertEqual(contexts[4].first_cursor, CONTEXT_FIRST_CHARACTER_CURSOR)
        self.assertEqual(contexts[4].restore_cursor, CONTEXT_RESTORE_CURSOR)

    def test_dialogue_layout_accepts_four_contexts_at_a_supplied_offset(self):
        contexts, _ = self.build_contexts()
        start_offset = 0x41000

        layout = build_context_bank_layout(contexts[1:], start_offset)

        self.assertEqual(layout.load_dispatcher_offset, start_offset)
        self.assertEqual(len(layout.loader_offsets), 4)
        self.assertEqual(len(layout.restore_offsets), 4)

    def test_entry_gate_and_postlude_preserve_the_original_fallback(self):
        entry = build_entry_code()
        postlude = build_postlude()

        self.assertEqual(len(entry), 0x20)
        self.assertEqual(len(postlude), 0x20)
        self.assertEqual(entry[:4], bytes.fromhex("F5 FA AA FF"))
        for bank, operand_offset in zip(ENTRY_BANKS, (7, 11, 15)):
            self.assertEqual(entry[operand_offset - 3:operand_offset - 1], bytes((0xFE, bank)))
            self.assertEqual(
                operand_offset + 1 + entry[operand_offset],
                19,
            )
        self.assertEqual(
            entry[19:31],
            bytes.fromhex("FA F2 C4 B7 28 03 C3 F7 00 C3 E0 00"),
        )
        self.assertEqual(entry.count(bytes.fromhex("C3 F7 00")), 2)
        self.assertEqual(entry.count(bytes.fromhex("C3 E0 00")), 1)
        self.assertEqual(postlude[19:21], bytes.fromhex("28 07"))
        self.assertEqual(postlude[21:28], bytes.fromhex("F1 FA F0 C4 C3 0C 18"))
        self.assertEqual(postlude[28:31], bytes.fromhex("C3 F7 00"))
        self.assertEqual(ENTRY_OFFSET, 0x00A0)

    def test_builds_both_checked_one_megabyte_variants(self):
        rom_7x7 = build_comparison_pilot(self.source, *self.values, vertical_8=False)
        rom_7x8 = build_comparison_pilot(self.source, *self.values, vertical_8=True)

        self.assertEqual(len(rom_7x7), MENU_EXPANDED_SIZE)
        self.assertEqual(len(rom_7x8), MENU_EXPANDED_SIZE)
        self.assertTrue(verify_rom(rom_7x7).passed)
        self.assertTrue(verify_rom(rom_7x8).passed)
        self.assertEqual(rom_7x7[0x148], 0x05)
        self.assertEqual(rom_7x8[0x148], 0x05)
        self.assertEqual(RESTORE_HELPER_SIZE, 31)
        for rom in (rom_7x7, rom_7x8):
            helper = rom[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + 24]
            self.assertEqual(helper[:4], bytes.fromhex("F5 FA AA FF"))
            self.assertEqual(helper[14:], bytes.fromhex("F1 EA 00 20 FB F1 21 03 00 C9"))
        self.assertEqual(
            rom_7x7[0x00F7:0x0100],
            OPENING_GATE_MISS_CODE,
        )
        self.assertEqual(
            rom_7x8[0x00F7:0x0100],
            OPENING_GATE_MISS_CODE,
        )
        self.assertEqual(
            rom_7x7[PRACTICE_SOURCE_OFFSET:PRACTICE_SOURCE_END],
            rom_7x8[PRACTICE_SOURCE_OFFSET:PRACTICE_SOURCE_END],
        )
        self.assertEqual(
            rom_7x7[PRACTICE_SOURCE_OFFSET + len(PRACTICE_SOURCE_BYTES)],
            self.source[PRACTICE_SOURCE_END],
        )
        self.assertEqual(
            rom_7x7[OPENING_SOURCE_OFFSET:OPENING_SOURCE_END],
            rom_7x8[OPENING_SOURCE_OFFSET:OPENING_SOURCE_END],
        )

        contexts, _ = self.build_contexts()
        layout = build_context_bank_layout(contexts)
        allowed_differences = set(range(0x14E, 0x150))
        for offset, pattern_data in zip(layout.pattern_offsets, layout.patterns):
            length = len(pattern_data)
            allowed_differences.update(range(offset, offset + length))
            mirror_offset = MBC1_MIRROR_OFFSET + offset
            allowed_differences.update(range(mirror_offset, mirror_offset + length))
        actual_differences = {
            index for index, (old, new) in enumerate(zip(rom_7x7, rom_7x8))
            if old != new
        }
        self.assertTrue(actual_differences)
        self.assertLessEqual(actual_differences, allowed_differences)

        patch_manifest = create_patch_manifest(self.source, rom_7x7, "7x7")
        self.assertEqual(
            apply_patch_manifest(self.source, patch_manifest),
            rom_7x7,
        )

    def test_vertical_variant_changes_glyphs_but_not_text_or_original_backups(self):
        contexts_7x7, _ = self.build_contexts(vertical_8=False)
        contexts_7x8, _ = self.build_contexts(vertical_8=True)
        baseline = {context.record_id: context for context in contexts_7x7}
        expanded = {context.record_id: context for context in contexts_7x8}

        self.assertEqual(
            [context.payload for context in contexts_7x7],
            [context.payload for context in contexts_7x8],
        )
        changed_patterns = 0
        for record_id in baseline:
            for old, new in zip(baseline[record_id].glyphs, expanded[record_id].glyphs):
                changed_patterns += old.pattern != new.pattern
                occupied = [
                    index // 2
                    for index in range(0, 16, 2)
                    if new.pattern[index] | new.pattern[index + 1]
                ]
                self.assertEqual((occupied[0], occupied[-1]), (0, 7))
        self.assertGreater(changed_patterns, 0)
        self.assertEqual(
            baseline["opening"].original_patterns,
            expanded["opening"].original_patterns,
        )


if __name__ == "__main__":
    unittest.main()
