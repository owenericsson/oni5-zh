import json
import unittest
from pathlib import Path

from scripts.build_mbc1_expansion_probe import (
    EXPANDED_SIZE,
    SOURCE_SIZE,
)
from scripts.build_noticeboard_glyph_probe import (
    BACKUP_ADDRESS,
    NOTICEBOARD_SOURCE_OFFSET,
    RESTORE_HELPER_OFFSET,
    RESTORE_HOOK_OFFSET,
    RESTORE_HOOK_PATCH,
    TILE_PATTERN_SIZE,
    build_copy_code,
    parse_noticeboard_inputs,
    tile_vram_address,
)
from scripts.build_rom import apply_patch_manifest
from scripts.build_two_text_pilot import (
    build_context_entry_code,
    build_pilot_bank_layout,
    build_two_text_pilot,
    create_patch_manifest,
)
from scripts.build_woman_glyph_probe import (
    WOMAN_PATCH_BYTES,
    WOMAN_SOURCE_OFFSET,
    parse_woman_inputs,
)
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildTwoTextPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "roms" / "oni5_original.gb").read_bytes()
        cls.plan = json.loads(
            (ROOT / "data" / "tile_cache_plan_candidate.json").read_text(encoding="utf-8")
        )
        cls.encoding = json.loads(
            (ROOT / "data" / "translation_encoding_candidate.json").read_text(encoding="utf-8")
        )
        cls.noticeboard_glyphs, cls.noticeboard_payload = parse_noticeboard_inputs(
            cls.plan, cls.encoding
        )
        cls.woman_glyphs, cls.woman_payload = parse_woman_inputs(cls.plan, cls.encoding)
        cls.pilot = build_two_text_pilot(
            cls.source,
            cls.noticeboard_glyphs,
            cls.noticeboard_payload,
            cls.woman_glyphs,
            cls.woman_payload,
        )
        cls.layout = build_pilot_bank_layout(
            cls.noticeboard_glyphs,
            cls.woman_glyphs,
        )

    def test_builds_verified_rom_with_both_confirmed_text_streams(self):
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
            self.pilot[
                WOMAN_SOURCE_OFFSET + WOMAN_PATCH_BYTES:
                WOMAN_SOURCE_OFFSET + 68
            ],
            self.source[
                WOMAN_SOURCE_OFFSET + WOMAN_PATCH_BYTES:
                WOMAN_SOURCE_OFFSET + 68
            ],
        )
        self.assertEqual(self.source[0x148], 0x03)

    def test_entry_gate_targets_both_dialogues_and_preserves_fallback(self):
        entry = build_context_entry_code()

        self.assertEqual(len(entry), 31)
        self.assertEqual(entry[-5:], bytes.fromhex("06 CD C3 E0 00"))
        for branch_offset in (6, 13, 24):
            displacement = entry[branch_offset + 1]
            if displacement >= 0x80:
                displacement -= 0x100
            self.assertEqual(
                0x00A0 + branch_offset + 2 + displacement,
                0x00F7,
            )
        displacement = entry[21]
        self.assertEqual(0x00A0 + 22 + displacement, 0x00BA)

    def test_load_dispatcher_and_pattern_blocks_cover_both_glyph_sets(self):
        self.assertEqual(
            self.pilot[
                self.layout.load_dispatcher_offset:
                self.layout.load_dispatcher_offset + len(self.layout.load_dispatcher)
            ],
            self.layout.load_dispatcher,
        )
        self.assertIn(bytes.fromhex("FE 34 CA"), self.layout.load_dispatcher)
        self.assertIn(bytes.fromhex("FE 8F CA"), self.layout.load_dispatcher)

        for glyphs, loader_offset, loader, pattern_offset in (
            (
                self.noticeboard_glyphs,
                self.layout.noticeboard_loader_offset,
                self.layout.noticeboard_loader,
                self.layout.noticeboard_pattern_offset,
            ),
            (
                self.woman_glyphs,
                self.layout.woman_loader_offset,
                self.layout.woman_loader,
                self.layout.woman_pattern_offset,
            ),
        ):
            self.assertEqual(
                self.pilot[loader_offset:loader_offset + len(loader)],
                loader,
            )
            for index, glyph in enumerate(glyphs):
                start = pattern_offset + index * TILE_PATTERN_SIZE
                self.assertEqual(self.pilot[start:start + TILE_PATTERN_SIZE], glyph.pattern)
                self.assertIn(
                    build_copy_code(
                        tile_vram_address(glyph.tile),
                        BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
                    ),
                    loader,
                )

    def test_restore_dispatcher_routes_both_markers_and_cursor_gates(self):
        layout = self.layout
        self.assertEqual(
            self.pilot[
                layout.restore_dispatcher_offset:
                layout.restore_dispatcher_offset + len(layout.restore_dispatcher)
            ],
            layout.restore_dispatcher,
        )
        self.assertIn(bytes.fromhex("FE A5 CA"), layout.restore_dispatcher)
        self.assertIn(bytes.fromhex("FE 94 CA"), layout.restore_dispatcher)
        self.assertIn(bytes.fromhex("FE 3D"), layout.noticeboard_restore)
        self.assertIn(bytes.fromhex("FE B4"), layout.woman_restore)
        for glyphs, helper in (
            (self.noticeboard_glyphs, layout.noticeboard_restore),
            (self.woman_glyphs, layout.woman_restore),
        ):
            for index, glyph in enumerate(glyphs):
                self.assertIn(
                    build_copy_code(
                        BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
                        tile_vram_address(glyph.tile),
                    ),
                    helper,
                )
        self.assertEqual(
            self.pilot[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)],
            RESTORE_HOOK_PATCH,
        )
        self.assertIn(
            (layout.restore_dispatcher_offset - SOURCE_SIZE + 0x4000).to_bytes(2, "little"),
            self.pilot[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + 22],
        )

    def test_guarded_manifest_expands_and_reproduces_exact_pilot(self):
        manifest = create_patch_manifest(self.source, self.pilot)

        self.assertEqual(manifest["target_size"], "0x80000")
        self.assertEqual(manifest["extension_fill_byte"], "0xFF")
        self.assertIn("pilot, not production", manifest["scope"])
        self.assertTrue(manifest["patches"])
        rebuilt = update_checksums(apply_patch_manifest(self.source, manifest))
        self.assertEqual(rebuilt, self.pilot)


if __name__ == "__main__":
    unittest.main()
