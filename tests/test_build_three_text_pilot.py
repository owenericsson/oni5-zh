import json
import unittest
from pathlib import Path

from scripts.build_context_glyph_probe import parse_context_inputs
from scripts.build_mbc1_expansion_probe import EXPANDED_SIZE
from scripts.build_noticeboard_glyph_probe import (
    BACKUP_ADDRESS,
    NOTICEBOARD_SOURCE_OFFSET,
    TILE_PATTERN_SIZE,
    build_copy_code,
    parse_noticeboard_inputs,
    tile_vram_address,
)
from scripts.build_rom import apply_patch_manifest
from scripts.build_three_text_pilot import (
    CONTEXT_FIRST_TILE,
    CONTEXT_SOURCE_OFFSET,
    ENTRY_CONTEXT_HELPER,
    ENTRY_CONTEXT_HELPER_OFFSET,
    NOTICEBOARD_FIRST_TILE,
    WOMAN_FIRST_TILE,
    build_context_bank_layout,
    build_three_context_entry_code,
    build_three_text_pilot,
    create_patch_manifest,
    PilotContext,
)
from scripts.build_two_text_pilot import (
    NOTICEBOARD_FIRST_CURSOR,
    NOTICEBOARD_RESTORE_CURSOR,
    WOMAN_FIRST_CURSOR,
)
from scripts.build_woman_glyph_probe import (
    WOMAN_PATCH_BYTES,
    WOMAN_RESTORE_CURSOR,
    WOMAN_SOURCE_OFFSET,
    WOMAN_SOURCE_BYTES,
    parse_woman_inputs,
)
from scripts.build_context_glyph_probe import (
    CONTEXT_FIRST_CHARACTER_CURSOR,
    CONTEXT_PATCH_BYTES,
    CONTEXT_RESTORE_CURSOR,
    CONTEXT_SOURCE_BYTES,
)
from scripts.rom_checksums import update_checksums, verify_rom


ROOT = Path(__file__).resolve().parents[1]


class BuildThreeTextPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "roms" / "oni5_original.gb").read_bytes()
        cls.plan = json.loads(
            (ROOT / "data" / "tile_cache_plan_candidate.json").read_text(
                encoding="utf-8"
            )
        )
        cls.encoding = json.loads(
            (ROOT / "data" / "translation_encoding_candidate.json").read_text(
                encoding="utf-8"
            )
        )
        cls.context_plan = json.loads(
            (ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json").read_text(
                encoding="utf-8"
            )
        )
        cls.context_encoding = json.loads(
            (ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json").read_text(
                encoding="utf-8"
            )
        )
        cls.noticeboard_glyphs, cls.noticeboard_payload = parse_noticeboard_inputs(
            cls.plan, cls.encoding
        )
        cls.woman_glyphs, cls.woman_payload = parse_woman_inputs(
            cls.plan, cls.encoding
        )
        cls.context_glyphs, cls.context_payload = parse_context_inputs(
            cls.context_plan, cls.context_encoding
        )
        cls.contexts = (
            PilotContext(
                "noticeboard",
                NOTICEBOARD_FIRST_CURSOR,
                NOTICEBOARD_RESTORE_CURSOR,
                NOTICEBOARD_SOURCE_OFFSET,
                bytes.fromhex("12 1D 0E C6 1E 2E 0B 12 17 7F"),
                cls.noticeboard_glyphs,
                cls.noticeboard_payload,
            ),
            PilotContext(
                "woman",
                WOMAN_FIRST_CURSOR,
                WOMAN_RESTORE_CURSOR,
                WOMAN_SOURCE_OFFSET,
                WOMAN_SOURCE_BYTES,
                cls.woman_glyphs,
                cls.woman_payload,
            ),
            PilotContext(
                "garou",
                CONTEXT_FIRST_CHARACTER_CURSOR,
                CONTEXT_RESTORE_CURSOR,
                CONTEXT_SOURCE_OFFSET,
                CONTEXT_SOURCE_BYTES,
                cls.context_glyphs,
                cls.context_payload,
            ),
        )
        cls.layout = build_context_bank_layout(cls.contexts)
        cls.pilot = build_three_text_pilot(
            cls.source,
            cls.noticeboard_glyphs,
            cls.noticeboard_payload,
            cls.woman_glyphs,
            cls.woman_payload,
            cls.context_glyphs,
            cls.context_payload,
        )

    def test_context_mappings_reuse_tiles_without_sharing_restore_markers(self):
        old_tiles = {
            glyph.tile
            for glyph in self.noticeboard_glyphs + self.woman_glyphs
        }
        new_tiles = {glyph.tile for glyph in self.context_glyphs}
        markers = (
            self.noticeboard_glyphs[0].tile,
            self.woman_glyphs[0].tile,
            self.context_glyphs[0].tile,
        )

        self.assertTrue(old_tiles.intersection(new_tiles))
        self.assertEqual(
            markers,
            (NOTICEBOARD_FIRST_TILE, WOMAN_FIRST_TILE, CONTEXT_FIRST_TILE),
        )
        self.assertEqual(len(set(markers)), 3)
        self.assertEqual(len(self.context_glyphs), 20)
        self.assertEqual(self.context_payload[-10:-7], bytes.fromhex("09 4A 3C"))
        self.assertEqual(self.context_payload[-1], 0x7F)

    def test_entry_gate_accepts_only_the_three_context_cursors(self):
        entry = build_three_context_entry_code()

        self.assertEqual(len(entry), 32)
        self.assertIn(bytes.fromhex("FA AD FF FE 34 28 05 CD 77 00"), entry)
        self.assertEqual(ENTRY_CONTEXT_HELPER, bytes.fromhex("FE 8F 28 02 FE E9 C9"))
        for branch_offset, target in (
            (6, 0x00F7),
            (13, 0x00F7),
            (20, 0x00BB),
            (25, 0x00F7),
        ):
            displacement = entry[branch_offset + 1]
            if displacement >= 0x80:
                displacement -= 0x100
            self.assertEqual(
                0x00A0 + branch_offset + 2 + displacement,
                target,
            )

    def test_dispatchers_and_cache_helpers_cover_all_three_contexts(self):
        layout = self.layout
        for cursor in (0x34, 0x8F, 0xE9):
            self.assertIn(bytes((0xFE, cursor, 0xCA)), layout.load_dispatcher)
        for marker in (NOTICEBOARD_FIRST_TILE, WOMAN_FIRST_TILE, CONTEXT_FIRST_TILE):
            self.assertIn(bytes((0xFE, marker, 0xCA)), layout.restore_dispatcher)

        for context, loader, pattern_offset, restore_helper in zip(
            self.contexts,
            layout.loaders,
            layout.pattern_offsets,
            layout.restore_helpers,
        ):
            expected_backup = b"".join(
                build_copy_code(
                    tile_vram_address(glyph.tile),
                    BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
                )
                for index, glyph in enumerate(context.glyphs)
            )
            expected_restore = b"".join(
                build_copy_code(
                    BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
                    tile_vram_address(glyph.tile),
                )
                for index, glyph in enumerate(context.glyphs)
            )
            self.assertIn(expected_backup, loader)
            self.assertIn(expected_restore, restore_helper)
            self.assertIn(bytes((0xFE, context.restore_cursor)), restore_helper)
            pattern_data = b"".join(glyph.pattern for glyph in context.glyphs)
            self.assertEqual(
                self.pilot[pattern_offset:pattern_offset + len(pattern_data)],
                pattern_data,
            )

    def test_builds_verified_three_context_rom_and_reproducible_manifest(self):
        self.assertEqual(len(self.pilot), EXPANDED_SIZE)
        self.assertTrue(verify_rom(self.pilot).passed)
        self.assertEqual(
            self.pilot[
                NOTICEBOARD_SOURCE_OFFSET:
                NOTICEBOARD_SOURCE_OFFSET + len(self.noticeboard_payload)
            ],
            self.noticeboard_payload,
        )
        self.assertEqual(
            self.pilot[WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + WOMAN_PATCH_BYTES],
            self.woman_payload,
        )
        self.assertEqual(
            self.pilot[CONTEXT_SOURCE_OFFSET:CONTEXT_SOURCE_OFFSET + CONTEXT_PATCH_BYTES],
            self.context_payload,
        )
        self.assertEqual(
            self.pilot[
                CONTEXT_SOURCE_OFFSET + CONTEXT_PATCH_BYTES:
                CONTEXT_SOURCE_OFFSET + len(CONTEXT_SOURCE_BYTES)
            ],
            b"",
        )
        self.assertEqual(
            self.pilot[CONTEXT_SOURCE_OFFSET + CONTEXT_PATCH_BYTES],
            self.source[CONTEXT_SOURCE_OFFSET + len(CONTEXT_SOURCE_BYTES)],
        )
        self.assertEqual(
            self.pilot[
                ENTRY_CONTEXT_HELPER_OFFSET:
                ENTRY_CONTEXT_HELPER_OFFSET + len(ENTRY_CONTEXT_HELPER)
            ],
            ENTRY_CONTEXT_HELPER,
        )
        manifest = create_patch_manifest(self.source, self.pilot)
        manifest["scope"] = (
            "confirmed noticeboard, woman, and context dialogue mappings only; "
            "pilot, not production"
        )
        self.assertIn("context dialogue", manifest["scope"])
        rebuilt = update_checksums(apply_patch_manifest(self.source, manifest))
        self.assertEqual(rebuilt, self.pilot)
        self.assertEqual(self.source[0x148], 0x03)


if __name__ == "__main__":
    unittest.main()
