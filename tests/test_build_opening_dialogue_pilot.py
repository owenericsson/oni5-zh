import json
import unittest
from pathlib import Path

from scripts.build_mbc1_expansion_probe import POSTLUDE_OFFSET, SOURCE_SIZE
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, MENU_EXPANDED_SIZE
from scripts.build_opening_text_preview_patch import (
    OPENING_GATE_MISS_CODE,
    SOURCE_END as OPENING_SOURCE_END,
    SOURCE_OFFSET as OPENING_SOURCE_OFFSET,
)
from scripts.build_text_comparison_pilot import (
    OPENING_SOURCE_END as COMPARISON_OPENING_SOURCE_END,
    OPENING_SOURCE_OFFSET as COMPARISON_OPENING_SOURCE_OFFSET,
    PRACTICE_RUNTIME_SIGNATURE_V2_3,
    RESTORE_HOOK_OFFSET,
    RESTORE_HOOK_PATCH,
    align_up,
    bank_cpu_address,
    build_context_bank_layout,
    build_contexts,
    build_entry_code,
)
from scripts.build_opening_dialogue_pilot import (
    _build_bank10_gateway,
    _build_fixed_gateway_completion,
    _build_fixed_gateway_stub,
    _build_unified_load_dispatcher,
    _opening_bank_layout,
    build_opening_dialogue_pilot,
)
from scripts.rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildOpeningDialoguePilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "roms" / "oni5_original.gb").read_bytes()
        cls.opening = (ROOT / "roms" / "oni5_opening_preview.gb").read_bytes()
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
        return build_opening_dialogue_pilot(self.opening, self.source, *self.values)

    def test_builds_on_verified_opening_base_and_preserves_opening_payload(self):
        rom = self.build()

        self.assertEqual(len(rom), MENU_EXPANDED_SIZE)
        self.assertTrue(verify_rom(rom).passed)
        self.assertEqual(
            rom[OPENING_SOURCE_OFFSET:OPENING_SOURCE_END],
            self.opening[OPENING_SOURCE_OFFSET:OPENING_SOURCE_END],
        )
        self.assertEqual(
            rom[COMPARISON_OPENING_SOURCE_OFFSET:COMPARISON_OPENING_SOURCE_END],
            self.opening[COMPARISON_OPENING_SOURCE_OFFSET:COMPARISON_OPENING_SOURCE_END],
        )
        self.assertEqual(rom[0x148], 0x05)

    def test_dialogue_payloads_are_patched_in_both_mbc1_mirrors(self):
        rom = self.build()
        contexts, _ = build_contexts(self.source, *self.values, vertical_8=False)

        for context in contexts[1:]:
            start = context.source_offset
            end = start + len(context.payload)
            self.assertEqual(rom[start:end], context.payload, context.record_id)
            mirror_start = MBC1_MIRROR_OFFSET + start
            self.assertEqual(
                rom[mirror_start:mirror_start + len(context.payload)],
                context.payload,
                context.record_id,
            )

    def test_opening_hooks_and_resources_are_reused(self):
        contexts, _ = build_contexts(self.source, *self.values, vertical_8=False)
        opening_layout = _opening_bank_layout(contexts[0], self.opening)
        relocated_loader = align_up(opening_layout.used_end, 0x100)
        dialogue_start = align_up(
            relocated_loader + len(opening_layout.loader),
            0x100,
        )
        dialogue_layout = build_context_bank_layout(contexts[1:], dialogue_start)
        rom = self.build()

        gateway_template = _build_bank10_gateway(0x4000)
        dispatcher_offset = SOURCE_SIZE + len(gateway_template)
        gateway = _build_bank10_gateway(bank_cpu_address(dispatcher_offset))
        unified_dispatcher = _build_unified_load_dispatcher(
            relocated_loader,
            dialogue_layout.load_dispatcher_offset,
        )
        self.assertEqual(
            rom[SOURCE_SIZE:SOURCE_SIZE + len(gateway)],
            gateway,
        )
        self.assertEqual(
            rom[dispatcher_offset:dispatcher_offset + len(unified_dispatcher)],
            unified_dispatcher,
        )
        self.assertEqual(
            rom[relocated_loader:relocated_loader + len(opening_layout.loader)],
            opening_layout.loader,
        )
        self.assertEqual(
            rom[opening_layout.pattern_offset:
                opening_layout.pattern_offset + len(contexts[0].glyphs) * 16],
            self.opening[
                opening_layout.pattern_offset:
                opening_layout.pattern_offset + len(contexts[0].glyphs) * 16
            ],
        )
        self.assertEqual(
            rom[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)],
            self.opening[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)],
        )
        self.assertEqual(rom[0xA0:0xC0], build_entry_code())
        self.assertEqual(
            rom[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(_build_fixed_gateway_stub())],
            _build_fixed_gateway_stub(),
        )
        completion_offset = POSTLUDE_OFFSET + len(_build_fixed_gateway_stub())
        self.assertEqual(
            rom[completion_offset:completion_offset + len(_build_fixed_gateway_completion())],
            _build_fixed_gateway_completion(),
        )
        self.assertEqual(rom[0xF7:0x100], OPENING_GATE_MISS_CODE)
        self.assertEqual(
            rom[MBC1_MIRROR_OFFSET + 0xA0:MBC1_MIRROR_OFFSET + 0xC0],
            build_entry_code(),
        )
        self.assertEqual(
            rom[0xC0000:0xC4000],
            rom[SOURCE_SIZE:SOURCE_SIZE + 0x4000],
        )
        self.assertEqual(
            dialogue_layout.load_dispatcher_offset,
            dialogue_start,
        )

    def test_v2_2_gateway_restores_the_bank_from_fixed_code(self):
        rom = build_opening_dialogue_pilot(
            self.opening,
            self.source,
            *self.values,
            dialogue_context_ids=("practice",),
            gateway_layout="v2.2",
        )
        expected_entry = bytes.fromhex(
            "F5 FA AA FF FE 04 28 06 FE 24 28 02 18 49 "
            "FA F2 C4 B7 20 43 18 2A B7 28 3E F1 FA F0 C4 C3 0C 18"
        )
        gateway = bytes.fromhex("CD 04 40 C9")
        completion = bytes.fromhex("F5 FA AA FF EA 00 20 FB F1 C3 B6 00")

        self.assertTrue(verify_rom(rom).passed)
        self.assertEqual(rom[0xA0:0xC0], expected_entry)
        self.assertEqual(
            rom[MBC1_MIRROR_OFFSET + 0xA0:MBC1_MIRROR_OFFSET + 0xC0],
            expected_entry,
        )
        self.assertEqual(rom[POSTLUDE_OFFSET:POSTLUDE_OFFSET + 9],
                         bytes.fromhex("F3 3E 10 EA 00 20 CD 00 40"))
        self.assertEqual(rom[POSTLUDE_OFFSET + 9:POSTLUDE_OFFSET + 21], completion)
        self.assertEqual(rom[SOURCE_SIZE:SOURCE_SIZE + len(gateway)], gateway)
        self.assertEqual(
            rom[MBC1_MIRROR_OFFSET + SOURCE_SIZE:
                MBC1_MIRROR_OFFSET + SOURCE_SIZE + len(gateway)],
            gateway,
        )
        self.assertEqual(rom[0xF7:0x100], OPENING_GATE_MISS_CODE)
        self.assertEqual(
            rom[MBC1_MIRROR_OFFSET + 0xF7:MBC1_MIRROR_OFFSET + 0x100],
            OPENING_GATE_MISS_CODE,
        )

    def test_v2_3_embeds_the_inferred_practice_runtime_signature(self):
        contexts, _ = build_contexts(
            self.source,
            *self.values,
            vertical_8=False,
            practice_runtime_signature=PRACTICE_RUNTIME_SIGNATURE_V2_3,
        )
        opening_layout = _opening_bank_layout(contexts[0], self.opening)
        relocated_loader = align_up(opening_layout.used_end, 0x100)
        dialogue_start = align_up(
            relocated_loader + len(opening_layout.loader),
            0x100,
        )
        dialogue_layout = build_context_bank_layout((contexts[1],), dialogue_start)
        rom = build_opening_dialogue_pilot(
            self.opening,
            self.source,
            *self.values,
            dialogue_context_ids=("practice",),
            gateway_layout="v2.3",
        )

        self.assertEqual(
            (contexts[1].bank, contexts[1].pointer_high, contexts[1].first_cursor),
            (0x04, 0x34, 0x8F),
        )
        self.assertEqual(
            rom[
                dialogue_layout.load_dispatcher_offset:
                dialogue_layout.load_dispatcher_offset + len(dialogue_layout.load_dispatcher)
            ],
            dialogue_layout.load_dispatcher,
        )
        self.assertEqual(
            dialogue_layout.load_dispatcher[:21],
            bytes.fromhex(
                "FA AA FF FE 04 20 14 FA AE FF FE 34 20 0D "
                "FA AD FF FE 8F 20 06"
            ),
        )

    def test_unverified_opening_base_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "opening base SHA-256"):
            build_opening_dialogue_pilot(
                self.opening[:-1] + bytes((self.opening[-1] ^ 1,)),
                self.source,
                *self.values,
            )


if __name__ == "__main__":
    unittest.main()
