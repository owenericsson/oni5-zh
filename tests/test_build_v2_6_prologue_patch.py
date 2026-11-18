import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_v2_6_prologue_patch as v2_6
from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_mbc1_expansion_probe import SOURCE_SIZE
from scripts.build_menu_pilot import (
    MENU_EXPANDED_SIZE,
    MENU_EXTENSION_ALIAS_OFFSET,
    MENU_ROM_SIZE_CODE,
    MBC1_MIRROR_OFFSET,
    ROM_BANK_SIZE,
)
from scripts.build_rom import update_checksums
from scripts.rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildV26ProloguePatchTests(unittest.TestCase):
    def setUp(self):
        source = bytearray([0xFF]) * SOURCE_SIZE
        source[0x147] = 0x03
        source[0x148] = 0x03
        source[
            v2_6.FIRST_EVENT_OFFSET:
            v2_6.FIRST_EVENT_END
        ] = v2_6.FIRST_EVENT_BYTES
        source[
            v2_6.THIRD_EVENT_OFFSET:
            v2_6.THIRD_EVENT_END
        ] = v2_6.THIRD_EVENT_BYTES
        source[
            v2_6.NEXT_DIALOGUE_EVENT_OFFSET:
            v2_6.NEXT_DIALOGUE_EVENT_END
        ] = v2_6.NEXT_DIALOGUE_EVENT_BYTES
        for offset, end, event_bytes in (
            (
                v2_6.ADDITIONAL_DIALOGUE_EVENT_OFFSET,
                v2_6.ADDITIONAL_DIALOGUE_EVENT_END,
                v2_6.ADDITIONAL_DIALOGUE_EVENT_BYTES,
            ),
            (
                v2_6.PRACTICE_DIALOGUE_EVENT_OFFSET,
                v2_6.PRACTICE_DIALOGUE_EVENT_END,
                v2_6.PRACTICE_DIALOGUE_EVENT_BYTES,
            ),
            (
                v2_6.LATER_DIALOGUE_EVENT_OFFSET,
                v2_6.LATER_DIALOGUE_EVENT_END,
                v2_6.LATER_DIALOGUE_EVENT_BYTES,
            ),
        ):
            source[offset:end] = event_bytes
        self.source = update_checksums(source)
        self.source_hash = hashlib.sha256(self.source).hexdigest()

        parent = bytearray([0xFF]) * MENU_EXPANDED_SIZE
        parent[0x147] = 0x03
        parent[0x148] = MENU_ROM_SIZE_CODE
        parent[
            v2_6.LEGACY_ENTRY_OFFSET:
            v2_6.LEGACY_ENTRY_END
        ] = bytes.fromhex(
            "FA F2 C4 B7 20 24 FA AA FF FE 04 20 19 FA AE FF FE 33 "
            "20 12 FA AD FF FE 1D 20 0B CD 00 4B 3E BB EA F0 C4 "
            "3E 01 C9 CD 00 4E C9 AF C9"
        )
        parent[SOURCE_SIZE:SOURCE_SIZE + 4] = bytes.fromhex("CD 40 65 C9")
        parent[
            v2_6.RESTORE_ROUTER_CALL_OFFSET:
            v2_6.RESTORE_ROUTER_CALL_OFFSET + 3
        ] = v2_6.RESTORE_ROUTER_CALL_EXPECTED
        parent[
            v2_6.FIRST_EVENT_OFFSET:
            v2_6.FIRST_EVENT_END
        ] = self.source[
            v2_6.FIRST_EVENT_OFFSET:
            v2_6.FIRST_EVENT_END
        ]
        parent[
            v2_6.THIRD_EVENT_OFFSET:
            v2_6.THIRD_EVENT_END
        ] = self.source[
            v2_6.THIRD_EVENT_OFFSET:
            v2_6.THIRD_EVENT_END
        ]
        parent[
            v2_6.NEXT_DIALOGUE_EVENT_OFFSET:
            v2_6.NEXT_DIALOGUE_EVENT_END
        ] = self.source[
            v2_6.NEXT_DIALOGUE_EVENT_OFFSET:
            v2_6.NEXT_DIALOGUE_EVENT_END
        ]
        for offset, end in (
            (
                v2_6.ADDITIONAL_DIALOGUE_EVENT_OFFSET,
                v2_6.ADDITIONAL_DIALOGUE_EVENT_END,
            ),
            (
                v2_6.PRACTICE_DIALOGUE_EVENT_OFFSET,
                v2_6.PRACTICE_DIALOGUE_EVENT_END,
            ),
            (
                v2_6.LATER_DIALOGUE_EVENT_OFFSET,
                v2_6.LATER_DIALOGUE_EVENT_END,
            ),
        ):
            parent[offset:end] = self.source[offset:end]
        for offset, end in (
            (v2_6.FIRST_EVENT_OFFSET, v2_6.FIRST_EVENT_END),
            (v2_6.THIRD_EVENT_OFFSET, v2_6.THIRD_EVENT_END),
            (v2_6.NEXT_DIALOGUE_EVENT_OFFSET, v2_6.NEXT_DIALOGUE_EVENT_END),
            (
                v2_6.ADDITIONAL_DIALOGUE_EVENT_OFFSET,
                v2_6.ADDITIONAL_DIALOGUE_EVENT_END,
            ),
            (
                v2_6.PRACTICE_DIALOGUE_EVENT_OFFSET,
                v2_6.PRACTICE_DIALOGUE_EVENT_END,
            ),
            (
                v2_6.LATER_DIALOGUE_EVENT_OFFSET,
                v2_6.LATER_DIALOGUE_EVENT_END,
            ),
        ):
            parent[MBC1_MIRROR_OFFSET + offset:MBC1_MIRROR_OFFSET + end] = (
                parent[offset:end]
            )
        parent[0x1803:0x1807] = bytes.fromhex("C3 E0 00 00")
        parent[0x19E5:0x19E8] = bytes.fromhex("C3 A0 00")
        parent[0x8946:0x894B] = bytes.fromhex("E5 CD E0 00 E1")
        parent[0x1BE8:0x1BEB] = bytes.fromhex("CD E0 00")
        parent[
            MENU_EXTENSION_ALIAS_OFFSET:
            MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE
        ] = parent[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]
        self.parent = update_checksums(parent)
        self.parent_hash = hashlib.sha256(self.parent).hexdigest()

        self.manifest = json.loads(
            (ROOT / "data" / "text_manifest.json").read_text(encoding="utf-8")
        )
        self.glyph_asset = json.loads(
            (
                ROOT / "data" / "chinese_glyphs_oni5_bank04_prologue_v26.json"
            ).read_text(encoding="utf-8")
        )
        self.next_glyph_asset = json.loads(
            (
                ROOT / "data" / "chinese_glyphs_oni5_bank04_prologue_v261.json"
            ).read_text(encoding="utf-8")
        )
        self.tile_candidate = json.loads(
            (ROOT / "data" / "tile_cache_plan_candidate.json").read_text(
                encoding="utf-8"
            )
        )
        self.practice_glyph_asset = json.loads(
            (
                ROOT / "data" / "chinese_glyphs_oni5_bank24_01348f.json"
            ).read_text(encoding="utf-8")
        )
        self.additional_dialogue_glyph_asset = json.loads(
            (
                ROOT / "data" / "chinese_glyphs_oni5_v261_remaining_dialogues.json"
            ).read_text(encoding="utf-8")
        )

    def build_target(self):
        with (
            patch.object(v2_6, "EXPECTED_V2_5_SHA256", self.parent_hash),
            patch.object(v2_6, "EXPECTED_SOURCE_SHA256", self.source_hash),
            patch.object(v2_6, "decode_resource", return_value=bytes(0x800)),
        ):
            return v2_6.build_v2_6_patch(
                self.parent,
                self.source,
                self.manifest,
                self.glyph_asset,
                self.tile_candidate,
                self.next_glyph_asset,
                self.practice_glyph_asset,
                self.additional_dialogue_glyph_asset,
            )

    def test_builds_bps_with_fixed_text_spans_and_preserved_v25_hooks(self):
        patch_data, target, target_hash = self.build_target()

        self.assertEqual(len(target), MENU_EXPANDED_SIZE)
        self.assertTrue(verify_rom(target).passed)
        self.assertEqual(hashlib.sha256(target).hexdigest(), target_hash)
        self.assertEqual(apply_bps_patch(self.parent, patch_data), target)
        self.assertEqual(target[0x40000:0x40004], bytes.fromhex("CD 40 65 C9"))
        self.assertEqual(target[0x1803:0x1807], self.parent[0x1803:0x1807])
        self.assertEqual(target[0x19E5:0x19E8], self.parent[0x19E5:0x19E8])
        self.assertEqual(target[0x8946:0x894B], self.parent[0x8946:0x894B])
        self.assertEqual(target[0x1BE8:0x1BEB], self.parent[0x1BE8:0x1BEB])

        self.assertEqual(target[0x0133C8], 0x7E)
        self.assertEqual(target[0x0133C9], 0x7C)
        self.assertEqual(target[0x0133D3], 0x7F)
        self.assertEqual(target[0x0133D7], 0x7C)
        self.assertEqual(target[0x0133E8], 0x7F)
        self.assertEqual(target[v2_6.ADDITIONAL_DIALOGUE_SPAN[1]], 0x7F)
        self.assertEqual(target[v2_6.PRACTICE_DIALOGUE_SPAN[1]], 0x7E)
        self.assertEqual(target[v2_6.LATER_DIALOGUE_SPAN[1]], 0x7F)
        self.assertEqual(target[0x013459], 0x01)
        self.assertEqual(target[0x01346D], 0x7E)
        self.assertEqual(target[0x01347B], 0x7F)
        self.assertEqual(
            target[0x013459:0x01346D],
            target[MBC1_MIRROR_OFFSET + 0x013459:MBC1_MIRROR_OFFSET + 0x01346D],
        )
        self.assertEqual(
            target[0x013396:0x0133C8],
            target[MBC1_MIRROR_OFFSET + 0x013396:MBC1_MIRROR_OFFSET + 0x0133C8],
        )
        self.assertEqual(
            target[MENU_EXTENSION_ALIAS_OFFSET:MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE],
            target[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE],
        )
        self.assertEqual(
            target[
                v2_6.RESTORE_ROUTER_CALL_OFFSET:
                v2_6.RESTORE_ROUTER_CALL_OFFSET + 3
            ],
            bytes.fromhex("CD 60 40"),
        )
        self.assertEqual(target[v2_6.LEGACY_ENTRY_OFFSET:v2_6.LEGACY_ENTRY_OFFSET + 3],
                         bytes((0xC3,)) + v2_6.bank_cpu_address(v2_6.NEW_LOAD_GATE_OFFSET).to_bytes(2, "little"))

    def test_added_dialogues_keep_macros_fixed_spans_and_bank_mirrors(self):
        _, target, _ = self.build_target()

        for start, end in (
            v2_6.ADDITIONAL_DIALOGUE_SPAN,
            v2_6.PRACTICE_DIALOGUE_SPAN,
            v2_6.LATER_DIALOGUE_SPAN,
        ):
            self.assertEqual(
                target[start:end],
                target[
                    MBC1_MIRROR_OFFSET + start:
                    MBC1_MIRROR_OFFSET + end
                ],
            )

        additional_text = target[
            v2_6.ADDITIONAL_DIALOGUE_SPAN[0]:
            v2_6.ADDITIONAL_DIALOGUE_SPAN[1]
        ]
        practice_text = target[
            v2_6.PRACTICE_DIALOGUE_SPAN[0]:
            v2_6.PRACTICE_DIALOGUE_SPAN[1]
        ]
        later_text = target[
            v2_6.LATER_DIALOGUE_SPAN[0]:
            v2_6.LATER_DIALOGUE_SPAN[1]
        ]
        self.assertEqual(len(additional_text), 25)
        self.assertEqual(additional_text.count(0xAD), 1)
        self.assertEqual(len(practice_text), 27)
        self.assertIn(0x7D, practice_text)
        self.assertEqual(len(later_text), 13)
        self.assertEqual(later_text[3:5], bytes.fromhex("7D 3B"))
        self.assertEqual(later_text[-1], 0xCC)

        deferred_text_start = 0x013411
        self.assertEqual(
            target[deferred_text_start:deferred_text_start + 7],
            self.parent[deferred_text_start:deferred_text_start + 7],
        )

    def test_v261_patch_uses_the_accepted_v26_rom_as_its_parent(self):
        _, target, _ = self.build_target()
        with patch.object(v2_6, "EXPECTED_V2_6_SHA256", self.parent_hash):
            patch_data = v2_6.build_v2_6_1_patch(self.parent, target)

        self.assertEqual(apply_bps_patch(self.parent, patch_data), target)

    def test_translation_spans_preserve_line_and_ellipsis_codes(self):
        teacher = v2_6._find_record(self.manifest, v2_6.PROLOGUE_RECORD_IDS[0])
        third = v2_6._find_record(self.manifest, v2_6.PROLOGUE_RECORD_IDS[1])
        teacher_text = v2_6._translation_text(teacher, *v2_6.FIRST_TEXT_SPAN)
        student_text = v2_6._translation_text(teacher, *v2_6.STUDENT_TEXT_SPAN)
        third_text = v2_6._translation_text(third, *v2_6.THIRD_TEXT_SPAN)
        filtered_candidate = v2_6._candidate_without_reserved_tiles(
            self.tile_candidate
        )
        glyph_text = "\n".join((teacher_text, student_text, third_text))
        glyph_text = glyph_text.replace("！", "").replace("？", "")
        _, codes = v2_6.create_glyph_mapping(
            glyph_text,
            (self.glyph_asset,),
            filtered_candidate,
        )

        teacher_bytes = v2_6.encode_translation_span(
            teacher_text,
            codes,
            50,
            expected_ellipsis_codes=1,
        )
        student_bytes = v2_6.encode_translation_span(
            student_text,
            codes,
            9,
            expected_ellipsis_codes=0,
        )
        third_bytes = v2_6.encode_translation_span(
            third_text,
            codes,
            16,
            expected_ellipsis_codes=2,
        )
        self.assertEqual(
            (len(teacher_bytes), len(student_bytes), len(third_bytes)),
            (50, 9, 16),
        )
        self.assertEqual(
            (
                teacher_bytes.count(0x7D),
                student_bytes.count(0x7D),
                third_bytes.count(0x7D),
            ),
            (3, 1, 1),
        )
        self.assertEqual(
            (
                teacher_bytes.count(0xD5),
                student_bytes.count(0xD5),
                third_bytes.count(0xD5),
            ),
            (1, 0, 2),
        )
        self.assertEqual(student_bytes[-2:], bytes.fromhex("3C 4D"))

    def test_existing_v26_prologue_text_encoding_is_preserved(self):
        _, target, _ = self.build_target()

        self.assertEqual(
            target[v2_6.FIRST_TEXT_SPAN[0]:v2_6.FIRST_TEXT_SPAN[1]],
            bytes.fromhex(
                "01 02 7D 3B D5 03 04 06 09 0C 0F 11 13 7D 16 17 19 1A "
                "13 1B 1E 1F 20 4D 4D 4D 4D 4D 4D 4D 4D 7D 22 23 24 26 "
                "27 13 28 29 2A 2C 4A 3C 4D 4D 4D 4D 4D 4D"
            ),
        )
        self.assertEqual(
            target[v2_6.STUDENT_TEXT_SPAN[0]:v2_6.STUDENT_TEXT_SPAN[1]],
            bytes.fromhex("2D 2E 7D 3B 2F 4B 4B 3C 4D"),
        )
        self.assertEqual(
            target[v2_6.THIRD_TEXT_SPAN[0]:v2_6.THIRD_TEXT_SPAN[1]],
            bytes.fromhex(
                "01 02 7D 3B 30 2F 13 02 34 35 37 39 D5 D5 3C 4D"
            ),
        )

    def test_first_glyph_loader_sets_blank_upper_row(self):
        real_loader_builder = v2_6.build_loader_helper
        generated_loaders = []

        def capture_loader(context, pattern_cpu_address):
            loader = real_loader_builder(context, pattern_cpu_address)
            generated_loaders.append((context, loader))
            return loader

        with (
            patch.object(v2_6, "EXPECTED_V2_5_SHA256", self.parent_hash),
            patch.object(v2_6, "EXPECTED_SOURCE_SHA256", self.source_hash),
            patch.object(v2_6, "decode_resource", return_value=bytes(0x800)),
            patch.object(v2_6, "build_loader_helper", side_effect=capture_loader),
        ):
            _, target, _ = v2_6.build_v2_6_patch(
                self.parent,
                self.source,
                self.manifest,
                self.glyph_asset,
                self.tile_candidate,
                self.next_glyph_asset,
                self.practice_glyph_asset,
                self.additional_dialogue_glyph_asset,
            )

        context, loader = [
            item for item in generated_loaders
            if item[0].marker == v2_6.PROLOGUE_MARKER
        ][-1]
        self.assertEqual(context.loader_return_b, 0xCD)
        self.assertTrue(loader.endswith(bytes.fromhex("06 CD C9")))
        first_glyph_tile = context.glyphs[0].tile
        self.assertEqual(first_glyph_tile, 0x81)
        self.assertEqual(
            target[v2_6.FIRST_TEXT_SPAN[0]] + 0x80,
            first_glyph_tile,
        )
        self.assertEqual(
            context.return_code,
            first_glyph_tile,
        )
        self.assertIn(
            bytes((0x3E, first_glyph_tile, 0xEA, 0xF0, 0xC4)),
            loader,
        )
        self.assertEqual(
            target[v2_6.PROLOGUE_BANK10_START:
                   v2_6.PROLOGUE_BANK10_START + len(loader)],
            loader,
        )

    def test_shizuna_name_is_encoded_as_custom_glyphs_before_open_quote(self):
        _, target, _ = self.build_target()
        start = v2_6.FIRST_TEXT_SPAN[0]

        self.assertEqual(target[start:start + 4], bytes.fromhex("01 02 7D 3B"))
        self.assertNotEqual(target[start], 0x3B)

    def test_later_dialogue_uses_its_own_load_and_restore_context(self):
        _, target, _ = self.build_target()
        translated = target[
            v2_6.NEXT_DIALOGUE_SPAN[0]:
            v2_6.NEXT_DIALOGUE_SPAN[1]
        ]
        dispatcher = target[
            v2_6.LOAD_DISPATCHER_OFFSET:
            v2_6.LOAD_DISPATCHER_OFFSET + 96
        ]
        allocated_helpers = target[
            v2_6.PROLOGUE_BANK10_START:
            v2_6.PROLOGUE_BANK10_END
        ]

        self.assertIn(0x7D, translated)
        self.assertIn(0x3B, translated)
        self.assertIn(0x3C, translated)
        self.assertIn(0x3E, translated)
        self.assertEqual(target[v2_6.NEXT_DIALOGUE_SPAN[1]], 0x7E)
        self.assertEqual(target[0x01347B], 0x7F)
        self.assertIn(bytes.fromhex("FA AE FF FE 34"), dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE 96 38"), dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE E9 30"), dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE 59 38"), dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE 7C 30"), dispatcher)
        self.assertIn(bytes.fromhex("FE 86"), allocated_helpers)
        self.assertIn(bytes.fromhex("FA AD FF FE 7C"), allocated_helpers)

    def test_added_dialogue_contexts_use_exact_or_wrapped_cursor_gates(self):
        _, target, _ = self.build_target()
        dispatcher = target[
            v2_6.LOAD_DISPATCHER_OFFSET:
            v2_6.LOAD_DISPATCHER_OFFSET + 256
        ]
        allocated_helpers = target[
            v2_6.PROLOGUE_BANK10_START:
            v2_6.PROLOGUE_BANK10_END
        ]

        self.assertIn(bytes.fromhex("FA AD FF FE F0 20"), dispatcher)
        self.assertIn(
            bytes.fromhex("FA AA FF FE 24 20 23 FA AE FF FE 74"),
            dispatcher,
        )
        self.assertIn(bytes.fromhex("FA AD FF FE 90 38"), dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE AB 30"), dispatcher)
        self.assertIn(
            bytes.fromhex("FA AA FF FE 24 20 23 FA AE FF FE 75"),
            dispatcher,
        )
        self.assertIn(bytes.fromhex("FA AD FF FE 46 38"), dispatcher)
        self.assertIn(bytes.fromhex("FA AD FF FE 53 30"), dispatcher)
        self.assertIn(bytes.fromhex("FE 85"), allocated_helpers)
        self.assertIn(bytes.fromhex("FE 84"), allocated_helpers)
        self.assertIn(bytes.fromhex("FE 83"), allocated_helpers)

    def test_dialogue_macro_tokens_keep_display_width_but_encode_one_byte(self):
        additional_codes = {
            character: index
            for index, character in enumerate("常叶丸哦你继承了道场啊，真厉害")
        }
        additional = v2_6.encode_translation_span(
            "常叶丸\n「哦，你继承了道场啊？\n真厉害啊，{静那}！」",
            additional_codes,
            25,
            expected_ellipsis_codes=0,
            macro_tokens=v2_6.ADDITIONAL_DIALOGUE_MACROS,
        )
        later_codes = {
            character: index
            for index, character in enumerate("常叶丸什么情况这气息")
        }
        later = v2_6.encode_translation_span(
            "常叶丸\n「什么情况这气息！？」",
            later_codes,
            13,
            expected_ellipsis_codes=0,
            macro_tokens=v2_6.LATER_DIALOGUE_MACROS,
        )

        self.assertEqual(len(additional), 25)
        self.assertIn(0xAD, additional)
        self.assertEqual(len(later), 13)
        self.assertEqual(later[-1], 0xCC)

    def test_new_glyph_tiles_do_not_overwrite_the_following_japanese_dialogue(self):
        candidate = v2_6._candidate_avoiding_next_japanese_text(self.tile_candidate)
        text = "常叶丸\n「突然想见你了。」"
        glyphs, _ = v2_6.create_glyph_mapping(
            text.replace("「", "").replace("」", "").replace("。", ""),
            (self.next_glyph_asset,),
            candidate,
        )

        self.assertTrue(
            {glyph.tile for glyph in glyphs}.isdisjoint(
                v2_6.NEXT_DIALOGUE_NATIVE_TILES
            )
        )

    def test_rejects_non_v25_parent(self):
        changed_parent = bytearray(self.parent)
        changed_parent[0x40004] ^= 0x01
        changed_parent = update_checksums(changed_parent)
        with (
            patch.object(v2_6, "EXPECTED_V2_5_SHA256", self.parent_hash),
            patch.object(v2_6, "EXPECTED_SOURCE_SHA256", self.source_hash),
            self.assertRaisesRegex(ValueError, "V2.6 parent ROM"),
        ):
            v2_6.build_v2_6_rom(
                bytes(changed_parent),
                self.source,
                self.manifest,
                self.glyph_asset,
                self.tile_candidate,
            )

    def test_rejects_changed_source_event_bytes(self):
        changed_source = bytearray(self.source)
        changed_source[0x0133D3] ^= 0x01
        changed_source = update_checksums(changed_source)
        changed_source_hash = hashlib.sha256(changed_source).hexdigest()
        with (
            patch.object(v2_6, "EXPECTED_V2_5_SHA256", self.parent_hash),
            patch.object(v2_6, "EXPECTED_SOURCE_SHA256", changed_source_hash),
            patch.object(v2_6, "decode_resource", return_value=bytes(0x800)),
            self.assertRaisesRegex(ValueError, "first prologue event"),
        ):
            v2_6.build_v2_6_rom(
                self.parent,
                bytes(changed_source),
                self.manifest,
                self.glyph_asset,
                self.tile_candidate,
            )


if __name__ == "__main__":
    unittest.main()
