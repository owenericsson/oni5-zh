import hashlib
import json
import unittest
from pathlib import Path

from scripts.apply_bps_patch import apply_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, MENU_EXPANDED_SIZE
from scripts.build_opening_dialogue_pilot import build_opening_dialogue_pilot
from scripts.build_text_comparison_pilot import (
    PRACTICE_BANK,
    PRACTICE_FIRST_CURSOR,
    PRACTICE_POINTER_HIGH,
    PRACTICE_RUNTIME_SIGNATURE_V2_3,
    PRACTICE_SOURCE_BYTES,
    PRACTICE_SOURCE_OFFSET,
    PRACTICE_TEXT,
    bank_cpu_address,
    build_context_bank_layout,
    build_contexts,
)
from scripts.build_v2_opening_practice_patch import build_v2_practice_patch
from scripts.rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildV2OpeningPracticePatchTests(unittest.TestCase):
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

    def build(self):
        return build_v2_practice_patch(self.parent, self.source, *self.values)

    def test_legacy_practice_signature_matches_v2_2_build_layout(self):
        contexts, _ = build_contexts(self.source, *self.values, vertical_8=False)
        practice = next(context for context in contexts if context.record_id == "practice")

        self.assertEqual(PRACTICE_TEXT, "「今日的修行\n就到此为止」")
        self.assertEqual(
            (practice.bank, practice.pointer_high, practice.first_cursor),
            (PRACTICE_BANK, PRACTICE_POINTER_HIGH, PRACTICE_FIRST_CURSOR),
        )
        self.assertEqual(
            (PRACTICE_BANK, PRACTICE_POINTER_HIGH, PRACTICE_FIRST_CURSOR),
            (0x24, 0x74, 0x8F),
        )
        self.assertEqual(practice.source_offset, PRACTICE_SOURCE_OFFSET)
        self.assertEqual(
            self.source[
                PRACTICE_SOURCE_OFFSET:
                PRACTICE_SOURCE_OFFSET + len(PRACTICE_SOURCE_BYTES)
            ],
            PRACTICE_SOURCE_BYTES,
        )
        self.assertEqual(len(practice.payload), len(PRACTICE_SOURCE_BYTES))
        self.assertNotEqual(practice.payload, PRACTICE_SOURCE_BYTES)

        layout = build_context_bank_layout((practice,))
        expected_dispatch_checks = bytes.fromhex(
            "FA AA FF FE 24 20 14 FA AE FF FE 74 20 0D "
            "FA AD FF FE 8F 20 06"
        )
        self.assertEqual(layout.load_dispatcher[:21], expected_dispatch_checks)
        loader_address = bank_cpu_address(layout.loader_offsets[0])
        self.assertEqual(
            layout.load_dispatcher[21:24],
            b"\xCD" + loader_address.to_bytes(2, "little"),
        )
        self.assertEqual(layout.load_dispatcher[24:], bytes.fromhex("3E 01 C9 AF C9"))

    def test_v2_3_practice_signature_uses_the_inferred_initial_registers(self):
        contexts, _ = build_contexts(
            self.source,
            *self.values,
            vertical_8=False,
            practice_runtime_signature=PRACTICE_RUNTIME_SIGNATURE_V2_3,
        )
        practice = next(context for context in contexts if context.record_id == "practice")

        self.assertEqual(
            (practice.bank, practice.pointer_high, practice.first_cursor),
            (0x04, 0x34, 0x8F),
        )
        self.assertEqual(practice.source_offset, PRACTICE_SOURCE_OFFSET)
        self.assertEqual(
            self.source[practice.source_offset:practice.source_offset + 2],
            bytes.fromhex("3B 0F"),
        )
        layout = build_context_bank_layout((practice,))
        self.assertEqual(
            layout.load_dispatcher[:21],
            bytes.fromhex(
                "FA AA FF FE 04 20 14 FA AE FF FE 34 20 0D "
                "FA AD FF FE 8F 20 06"
            ),
        )

    def test_patch_applies_to_exact_v1_and_changes_only_practice_text_context(self):
        patch, target_digest = self.build()
        target = apply_bps_patch(self.parent, patch)
        contexts, _ = build_contexts(self.source, *self.values, vertical_8=False)

        self.assertEqual(len(target), MENU_EXPANDED_SIZE)
        self.assertTrue(verify_rom(target).passed)
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertEqual(
            target_digest,
            "d7f557e9a9f918d507b3952882be88213644dcb8129fa81a8ac9df9c4723adf9",
        )
        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "5252a190258c7119bf7c259f89c817b8641c3347ac2fb81f75733a4a5d708223",
        )
        self.assertEqual(
            target[0x1330D:0x13368],
            self.parent[0x1330D:0x13368],
        )
        self.assertEqual(target[0xF7:0x100], self.parent[0xF7:0x100])

        practice = contexts[1]
        start = practice.source_offset
        end = start + len(practice.payload)
        self.assertEqual(target[start:end], practice.payload)
        mirror_start = MBC1_MIRROR_OFFSET + start
        self.assertEqual(
            target[mirror_start:mirror_start + len(practice.payload)],
            practice.payload,
        )
        self.assertEqual(target[0xE0:0xE9], bytes.fromhex("F3 3E 10 EA 00 20 C3 00 40"))
        self.assertEqual(
            target[0xE9:0xF6],
            bytes.fromhex("B7 20 03 C3 F7 00 F1 FA F0 C4 C3 0C 18"),
        )
        self.assertEqual(target[0xF7:0x100], bytes.fromhex("F1 FE 60 D2 15 18 C3 07 18"))

        for context in contexts[2:]:
            start = context.source_offset
            end = start + len(context.payload)
            self.assertEqual(target[start:end], self.parent[start:end], context.record_id)
            mirror_start = MBC1_MIRROR_OFFSET + start
            self.assertEqual(
                target[mirror_start:mirror_start + len(context.payload)],
                self.parent[mirror_start:mirror_start + len(context.payload)],
                context.record_id,
            )

    def test_rebuild_is_deterministic(self):
        first_patch, first_target_digest = self.build()
        second_patch, second_target_digest = self.build()

        self.assertEqual(first_patch, second_patch)
        self.assertEqual(first_target_digest, second_target_digest)

    def test_wrong_parent_is_rejected(self):
        wrong_parent = self.parent[:-1] + bytes((self.parent[-1] ^ 1,))

        with self.assertRaisesRegex(ValueError, "immutable V1-opening-dialog"):
            build_v2_practice_patch(wrong_parent, self.source, *self.values)

    def test_only_practice_dialogue_payload_changes_among_known_text_spans(self):
        patch, _ = self.build()
        target = apply_bps_patch(self.parent, patch)
        contexts, _ = build_contexts(self.source, *self.values, vertical_8=False)

        changed_primary_spans = [
            context.record_id
            for context in contexts[1:]
            if target[
                context.source_offset:context.source_offset + len(context.payload)
            ] != self.parent[
                context.source_offset:context.source_offset + len(context.payload)
            ]
        ]
        self.assertEqual(changed_primary_spans, ["practice"])
        self.assertEqual(
            target[0x148],
            self.parent[0x148],
        )

    def test_v2_2_keeps_bank_restore_execution_in_the_fixed_window(self):
        patch, target_digest = build_v2_practice_patch(
            self.parent,
            self.source,
            *self.values,
            gateway_layout="v2.2",
        )
        target = apply_bps_patch(self.parent, patch)

        self.assertTrue(verify_rom(target).passed)
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "41e984c5b4a1ab7531746bedaa9793fcab39a22fcf74be6466198bd000014172",
        )
        self.assertEqual(
            target_digest,
            "6fe654dc63b8867e2744729c81d95d2afc2539c26b342ccd9503944fc6b2d634",
        )
        self.assertEqual(
            target[0xE0:0xE9],
            bytes.fromhex("F3 3E 10 EA 00 20 CD 00 40"),
        )
        self.assertEqual(
            target[0xE9:0xF5],
            bytes.fromhex("F5 FA AA FF EA 00 20 FB F1 C3 B6 00"),
        )
        self.assertEqual(
            target[0xB6:0xC0],
            bytes.fromhex("B7 28 3E F1 FA F0 C4 C3 0C 18"),
        )
        self.assertEqual(target[0x40000:0x40004], bytes.fromhex("CD 04 40 C9"))
        self.assertEqual(target[0xC0000:0xC0004], bytes.fromhex("CD 04 40 C9"))
        self.assertEqual(target[0xF7:0x100], self.parent[0xF7:0x100])

        rebuilt_patch, rebuilt_digest = build_v2_practice_patch(
            self.parent,
            self.source,
            *self.values,
            gateway_layout="v2.2",
        )
        self.assertEqual(rebuilt_patch, patch)
        self.assertEqual(rebuilt_digest, target_digest)

    def test_v2_3_dispatches_the_practice_line_using_inferred_hram_values(self):
        patch, target_digest = build_v2_practice_patch(
            self.parent,
            self.source,
            *self.values,
            gateway_layout="v2.3",
        )
        target = apply_bps_patch(self.parent, patch)
        contexts, _ = build_contexts(
            self.source,
            *self.values,
            vertical_8=False,
            practice_runtime_signature=PRACTICE_RUNTIME_SIGNATURE_V2_3,
        )
        practice = next(context for context in contexts if context.record_id == "practice")

        self.assertTrue(verify_rom(target).passed)
        self.assertEqual(target_digest, hashlib.sha256(target).hexdigest())
        self.assertEqual(
            hashlib.sha256(patch).hexdigest(),
            "a7e853dd16ad7998c89aa388371488be355aafd85b9520cf11b2830d3251cc6b",
        )
        self.assertEqual(
            target_digest,
            "f74fe255cd67fcaa71de5e5187b229823b1574d0a3334b571bcff70650401529",
        )
        self.assertEqual(
            (practice.bank, practice.pointer_high, practice.first_cursor),
            (0x04, 0x34, 0x8F),
        )
        self.assertEqual(
            target[
                practice.source_offset:
                practice.source_offset + len(practice.payload)
            ],
            practice.payload,
        )
        mirror_start = MBC1_MIRROR_OFFSET + practice.source_offset
        self.assertEqual(
            target[mirror_start:mirror_start + len(practice.payload)],
            practice.payload,
        )
        self.assertEqual(
            target[0xE0:0xE9],
            bytes.fromhex("F3 3E 10 EA 00 20 CD 00 40"),
        )
        self.assertEqual(target[0x40000:0x40004], bytes.fromhex("CD 04 40 C9"))

if __name__ == "__main__":
    unittest.main()
