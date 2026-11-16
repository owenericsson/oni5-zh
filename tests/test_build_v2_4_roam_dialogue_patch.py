import hashlib
import json
import unittest
from pathlib import Path

from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, MENU_EXPANDED_SIZE
from scripts.build_noticeboard_glyph_probe import (
    BACKUP_ADDRESS,
    TILE_PATTERN_SIZE,
    build_copy_code,
    tile_vram_address,
)
from scripts.build_opening_dialogue_pilot import _build_v2_2_entry_code
from scripts.build_text_comparison_pilot import (
    bank_cpu_address,
    build_context_bank_layout,
    build_contexts,
)
from scripts.build_v2_4_roam_dialogue_patch import build_v2_4_patch
from scripts.rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildV24RoamDialoguePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = (ROOT / "roms" / "oni5_v1_opening_dialog.gb").read_bytes()
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
            json.loads((ROOT / "data" / "tile_cache_plan_candidate.json").read_text(encoding="utf-8")),
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

    def build(
        self,
        prefilter_pointer_highs=False,
        clear_dialogue_upper_tile=False,
        include_garou=False,
        restore_dialogue_patterns_from_rom=False,
        preserve_dialogue_return_code=False,
    ):
        return build_v2_4_patch(
            self.parent,
            self.source,
            *self.values,
            prefilter_pointer_highs=prefilter_pointer_highs,
            clear_dialogue_upper_tile=clear_dialogue_upper_tile,
            include_garou=include_garou,
            restore_dialogue_patterns_from_rom=restore_dialogue_patterns_from_rom,
            preserve_dialogue_return_code=preserve_dialogue_return_code,
        )

    def test_patch_contains_only_noticeboard_and_woman_dialogues(self):
        patch, target_digest = self.build()
        target = apply_bps_patch(self.parent, patch)
        contexts, _ = build_contexts(self.source, *self.values, vertical_8=False)
        contexts_by_id = {context.record_id: context for context in contexts}

        self.assertEqual(len(target), MENU_EXPANDED_SIZE)
        self.assertTrue(verify_rom(target).passed)
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertEqual(
            target[0x1330D:0x13368],
            self.parent[0x1330D:0x13368],
        )
        self.assertEqual(target[0xF7:0x100], self.parent[0xF7:0x100])

        for context_id in ("noticeboard", "woman"):
            context = contexts_by_id[context_id]
            start = context.source_offset
            end = start + len(context.payload)
            self.assertEqual(target[start:end], context.payload, context_id)
            mirror_start = MBC1_MIRROR_OFFSET + start
            self.assertEqual(
                target[mirror_start:mirror_start + len(context.payload)],
                context.payload,
                context_id,
            )

        for context_id in ("practice", "garou"):
            context = contexts_by_id[context_id]
            start = context.source_offset
            end = start + len(context.payload)
            self.assertEqual(target[start:end], self.parent[start:end], context_id)
            mirror_start = MBC1_MIRROR_OFFSET + start
            self.assertEqual(
                target[mirror_start:mirror_start + len(context.payload)],
                self.parent[mirror_start:mirror_start + len(context.payload)],
                context_id,
            )

        self.assertEqual(target[0xE0:0xE9], bytes.fromhex("F3 3E 10 EA 00 20 CD 00 40"))
        self.assertEqual(target[0x40000:0x40004], bytes.fromhex("CD 04 40 C9"))

    def test_rebuild_is_deterministic(self):
        first_patch, first_digest = self.build()
        second_patch, second_digest = self.build()

        self.assertEqual(first_patch, second_patch)
        self.assertEqual(first_digest, second_digest)

    def test_first_dialogue_glyph_codes_match_the_loader_markers(self):
        contexts, _ = build_contexts(self.source, *self.values, vertical_8=False)
        contexts_by_id = {context.record_id: context for context in contexts}

        for context_id, input_code, marker, cursor in (
            ("noticeboard", 0x25, 0xA5, 0x34),
            ("woman", 0x14, 0x94, 0x8F),
        ):
            context = contexts_by_id[context_id]
            with self.subTest(context=context_id):
                self.assertEqual(context.payload[0], input_code)
                self.assertEqual(context.glyphs[0].tile, marker)
                self.assertEqual(context.marker, marker)
                self.assertEqual(context.first_cursor, cursor)
                self.assertEqual(context.first_cursor, (context.source_offset & 0xFF) + 1)
                self.assertEqual(context.payload[0], marker - 0x80)

    def test_dialogue_loaders_clear_the_upper_row_for_the_first_glyph(self):
        contexts, _ = build_contexts(
            self.source,
            *self.values,
            vertical_8=False,
            dialogue_loader_return_b=0xCD,
        )
        selected = tuple(
            context
            for context in contexts
            if context.record_id in ("noticeboard", "woman")
        )
        layout = build_context_bank_layout(selected)
        patch, _ = self.build(
            prefilter_pointer_highs=True,
            clear_dialogue_upper_tile=True,
        )
        target = apply_bps_patch(self.parent, patch)

        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "acb238df5ccb816f449767d204d868a01498ae606f084697dfa5e87f771723c2",
        )
        self.assertEqual(
            hashlib.sha256(target).hexdigest(),
            "9b457c1f0f352115cb9d666ac6f6897cdc92416c23b42adacb2d5487d51f938c",
        )
        self.assertEqual([context.loader_return_b for context in selected], [0xCD, 0xCD])
        self.assertEqual(len(layout.loaders), 2)
        self.assertTrue(all(loader.endswith(bytes.fromhex("06 CD C9")) for loader in layout.loaders))
        self.assertIn(bytes.fromhex("06 CD C9"), target)

    def test_v2_4_3_adds_garou_translation_with_safe_loader_and_mirrors(self):
        with self.assertRaisesRegex(ValueError, "requires pointer-high filtering"):
            self.build(include_garou=True)

        patch, target_digest = self.build(
            prefilter_pointer_highs=True,
            clear_dialogue_upper_tile=True,
            include_garou=True,
        )
        repeated_patch, repeated_digest = self.build(
            prefilter_pointer_highs=True,
            clear_dialogue_upper_tile=True,
            include_garou=True,
        )
        target = apply_bps_patch(self.parent, patch)
        contexts, _ = build_contexts(
            self.source,
            *self.values,
            vertical_8=False,
            dialogue_loader_return_b=0xCD,
        )
        selected_ids = ("noticeboard", "woman", "garou")
        selected = tuple(context for context in contexts if context.record_id in selected_ids)
        contexts_by_id = {context.record_id: context for context in contexts}
        layout = build_context_bank_layout(selected)

        self.assertEqual(len(layout.loaders), 3)
        self.assertTrue(
            all(loader.endswith(bytes.fromhex("06 CD C9")) for loader in layout.loaders)
        )
        self.assertEqual(patch, repeated_patch)
        self.assertEqual(target_digest, repeated_digest)
        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "3951c8e03df0f14f3e26ec1ba29cd8c22455d943b3361dc0f894ddb07d57e310",
        )
        self.assertEqual(
            target_digest,
            "8738ded706f0875c78505aa61074b10f628d862efb44c415977746a6f61e643c",
        )
        for context_id in selected_ids:
            context = contexts_by_id[context_id]
            start = context.source_offset
            end = start + len(context.payload)
            mirror_start = MBC1_MIRROR_OFFSET + start
            with self.subTest(context=context_id):
                self.assertEqual(target[start:end], context.payload)
                self.assertEqual(
                    target[mirror_start:mirror_start + len(context.payload)],
                    context.payload,
                )
        garou = contexts_by_id["garou"]
        self.assertEqual(len(garou.payload), 32)
        self.assertEqual(garou.payload[-1], 0x7F)
        self.assertEqual(
            target[0x1348F:0x134AA],
            self.parent[0x1348F:0x134AA],
        )
        self.assertEqual(target[0xF7:0x100], self.parent[0xF7:0x100])
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertTrue(verify_rom(target).passed)

    def test_v2_4_4_restores_dialogue_patterns_from_rom_not_wram(self):
        patch, target_digest = self.build(
            prefilter_pointer_highs=True,
            clear_dialogue_upper_tile=True,
            include_garou=True,
            restore_dialogue_patterns_from_rom=True,
        )
        repeated_patch, repeated_digest = self.build(
            prefilter_pointer_highs=True,
            clear_dialogue_upper_tile=True,
            include_garou=True,
            restore_dialogue_patterns_from_rom=True,
        )
        target = apply_bps_patch(self.parent, patch)
        contexts, _ = build_contexts(
            self.source,
            *self.values,
            vertical_8=False,
            dialogue_loader_return_b=0xCD,
            restore_dialogue_patterns_from_rom=True,
        )
        selected_ids = ("noticeboard", "woman", "garou")
        selected = tuple(context for context in contexts if context.record_id in selected_ids)
        layout = build_context_bank_layout(selected)

        self.assertEqual(patch, repeated_patch)
        self.assertEqual(target_digest, repeated_digest)
        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "1e4a2ae70f8b9dbb266b749dcfc5dd679c2197e6d2fcc85a3ea6ab919ca5d3f2",
        )
        self.assertEqual(
            target_digest,
            "51bbdbcd1f8729ac16c3ba7992bcff37aa66a471c80017c8f0b09f7e20cc1107",
        )
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertTrue(verify_rom(target).passed)
        self.assertTrue(all(context.restore_from_rom for context in selected))
        self.assertTrue(all(offset is not None for offset in layout.original_pattern_offsets))

        for context, loader, original_offset, original_patterns, restore_helper in zip(
            selected,
            layout.loaders,
            layout.original_pattern_offsets,
            layout.original_patterns,
            layout.restore_helpers,
        ):
            expected_backup = b"".join(
                build_copy_code(
                    tile_vram_address(glyph.tile),
                    BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
                )
                for index, glyph in enumerate(context.glyphs)
            )
            original_cpu = bank_cpu_address(original_offset)
            expected_restore = b"".join(
                build_copy_code(
                    original_cpu + index * TILE_PATTERN_SIZE,
                    tile_vram_address(glyph.tile),
                )
                for index, glyph in enumerate(context.glyphs)
            )
            with self.subTest(context=context.record_id):
                self.assertEqual(len(original_patterns), len(context.glyphs) * TILE_PATTERN_SIZE)
                self.assertNotIn(expected_backup, loader)
                self.assertIn(expected_restore, restore_helper)
                self.assertNotIn(expected_backup, restore_helper)

    def test_v2_4_5_restores_the_previous_return_tile_after_dialogue(self):
        flags = {
            "prefilter_pointer_highs": True,
            "clear_dialogue_upper_tile": True,
            "include_garou": True,
            "restore_dialogue_patterns_from_rom": True,
            "preserve_dialogue_return_code": True,
        }
        patch, target_digest = self.build(**flags)
        repeated_patch, repeated_digest = self.build(**flags)
        target = apply_bps_patch(self.parent, patch)
        contexts, _ = build_contexts(
            self.source,
            *self.values,
            vertical_8=False,
            dialogue_loader_return_b=0xCD,
            restore_dialogue_patterns_from_rom=True,
            preserve_dialogue_return_code=True,
        )
        selected = tuple(
            context
            for context in contexts
            if context.record_id in ("noticeboard", "woman", "garou")
        )
        layout = build_context_bank_layout(selected)

        self.assertEqual(patch, repeated_patch)
        self.assertEqual(target_digest, repeated_digest)
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertTrue(verify_rom(target).passed)
        for context, loader, restore_helper in zip(
            selected,
            layout.loaders,
            layout.restore_helpers,
        ):
            with self.subTest(context=context.record_id):
                self.assertTrue(context.preserve_return_code)
                self.assertIn(bytes.fromhex("FA F0 C4 EA F1 C4"), loader)
                self.assertIn(
                    bytes.fromhex("FA F1 C4 EA F0 C4 AF EA F1 C4"),
                    restore_helper,
                )

    def test_prefilter_excludes_battle_pointer_before_gateway(self):
        expected_entry = bytes.fromhex(
            "F5 FA AE FF FE 33 28 06 FE 0E 28 02 18 49 "
            "FA F2 C4 B7 20 43 18 2A B7 28 3E F1 FA F0 C4 C3 0C 18"
        )
        entry, return_handler = _build_v2_2_entry_code(
            (0x04, 0x0C),
            (0x33, 0x0E),
        )
        patch, target_digest = self.build(prefilter_pointer_highs=True)
        target = apply_bps_patch(self.parent, patch)
        legacy_target = apply_bps_patch(self.parent, self.build()[0])

        self.assertEqual(entry, expected_entry)
        self.assertEqual(return_handler, 0x00B6)
        self.assertEqual(entry[12:14], bytes.fromhex("18 49"))
        self.assertEqual(0xA0 + 14 + entry[13], 0x00F7)
        self.assertEqual(target[0xA0:0xC0], expected_entry)
        self.assertEqual(
            target[MBC1_MIRROR_OFFSET + 0xA0:MBC1_MIRROR_OFFSET + 0xC0],
            expected_entry,
        )
        self.assertEqual(
            [
                offset
                for offset, (old, new) in enumerate(zip(legacy_target, target))
                if old != new
            ],
            [0x00A2, 0x00A5, 0x00A9, 0x014E, 0x014F, 0x800A2, 0x800A5, 0x800A9],
        )
        self.assertTrue(verify_rom(target).passed)
        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "d61afcff98c521372b1d7119b6f19aee521f3b77a0dd9aa98dca3cbffa93ef34",
        )
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertEqual(
            target_digest,
            "90b3ab1851d0e2ef2a6f68add9b0c1834b1570971b1dfd6c64201c4e905bc2f4",
        )

    def test_default_build_remains_the_recorded_v2_4(self):
        patch, target_digest = self.build()

        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "15bf9e54ed4b6f8b0918f018908daaa0de677d087d8163dcf3e3c3358f1d4448",
        )
        self.assertEqual(
            target_digest,
            "f2f61a05971bcea719c14420ac88e0bdf1f9628ca36ca2d58bd1372f8f6f0895",
        )

    def test_wrong_parent_is_rejected(self):
        wrong_parent = self.parent[:-1] + bytes((self.parent[-1] ^ 1,))

        with self.assertRaisesRegex(ValueError, "immutable V1-opening-dialog"):
            build_v2_4_patch(wrong_parent, self.source, *self.values)


if __name__ == "__main__":
    unittest.main()
