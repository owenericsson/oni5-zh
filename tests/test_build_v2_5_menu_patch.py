import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_v2_5_menu_patch as v2_5
from scripts import build_menu_pilot as menu_pilot
from scripts.build_mbc1_expansion_probe import SOURCE_SIZE
from scripts.build_menu_pilot import MENU_ITEMS
from scripts.build_rom import update_checksums
from scripts.compile_translation_encoding import SPACE_CODE, create_glyph_map
from scripts.rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildV25MenuPatchTests(unittest.TestCase):
    def setUp(self):
        source = bytearray([0xFF]) * SOURCE_SIZE
        source[0x147] = 0x03
        source[0x148] = 0x03
        for _, offset, payload, _ in MENU_ITEMS:
            source[offset:offset + len(payload)] = payload
        self.source = update_checksums(source)
        self.source_hash = hashlib.sha256(self.source).hexdigest()

        base = bytearray([0xFF]) * v2_5.MENU_EXPANDED_SIZE
        base[0x147] = 0x03
        base[0x148] = v2_5.MENU_ROM_SIZE_CODE
        base[v2_5.GATEWAY_OFFSET:v2_5.GATEWAY_OFFSET + 4] = (
            v2_5.MAIN_GATEWAY_EXPECTED
        )
        base[v2_5.ENTRY_OFFSET:v2_5.ENTRY_OFFSET + 0x20] = bytes.fromhex(
            "F5 FA AE FF FE 33 28 06 FE 0E 28 02 18 49 FA F2 C4 "
            "B7 20 43 18 2A B7 28 3E F1 FA F0 C4 C3 0C 18"
        )
        base[
            v2_5.MENU_OPEN_HOOK_OFFSET:
            v2_5.MENU_OPEN_HOOK_OFFSET + len(v2_5.MENU_OPEN_HOOK_EXPECTED)
        ] = v2_5.MENU_OPEN_HOOK_EXPECTED
        base[
            v2_5.MENU_CLOSE_HOOK_OFFSET:
            v2_5.MENU_CLOSE_HOOK_OFFSET + len(v2_5.MENU_CLOSE_HOOK_EXPECTED)
        ] = v2_5.MENU_CLOSE_HOOK_EXPECTED
        base[
            v2_5.DIALOGUE_RESTORE_HOOK_OFFSET:
            v2_5.DIALOGUE_RESTORE_HOOK_OFFSET
            + len(v2_5.DIALOGUE_RESTORE_HOOK_EXPECTED)
        ] = v2_5.DIALOGUE_RESTORE_HOOK_EXPECTED
        base[0xE0:0xE0 + len(v2_5.FIXED_GATEWAY_EXPECTED)] = (
            v2_5.FIXED_GATEWAY_EXPECTED
        )
        base[
            v2_5.BANK10_GATEWAY_OFFSET:
            v2_5.BANK10_GATEWAY_OFFSET + len(v2_5.BANK10_GATEWAY_EXPECTED)
        ] = v2_5.BANK10_GATEWAY_EXPECTED
        restore_wrapper = (
            bytes.fromhex("F5 FA AA FF F5 F3 3E 10 EA 00 20 CD")
            + bytes.fromhex("B0 48")
            + bytes.fromhex("F1 EA 00 20 FB F1 21 03 00 C9")
        )
        base[
            v2_5.RESTORE_HELPER_OFFSET:
            v2_5.RESTORE_HELPER_OFFSET + len(restore_wrapper)
        ] = restore_wrapper
        base[SOURCE_SIZE + 0x08B0:SOURCE_SIZE + 0x08B3] = bytes.fromhex(
            "FA F2 C4"
        )
        base[
            v2_5.MBC1_MIRROR_OFFSET:
            v2_5.MBC1_MIRROR_OFFSET + SOURCE_SIZE
        ] = base[:SOURCE_SIZE]
        base[
            v2_5.MENU_EXTENSION_ALIAS_OFFSET:
            v2_5.MENU_EXTENSION_ALIAS_OFFSET + v2_5.ROM_BANK_SIZE
        ] = base[SOURCE_SIZE:SOURCE_SIZE + v2_5.ROM_BANK_SIZE]
        self.base = update_checksums(base)
        self.base_hash = hashlib.sha256(self.base).hexdigest()
        self.menu_manifest = json.loads(
            (ROOT / "data" / "menu_text_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.menu_manifest["source_rom_sha256"] = self.source_hash
        self.glyph_asset = json.loads(
            (ROOT / "data" / "menu_chinese_glyphs.json").read_text(
                encoding="utf-8"
            )
        )

    def cache_plan_for_asset(self, rom, candidate, glyph_asset):
        self.assertEqual(len(rom), SOURCE_SIZE)
        glyph_by_character = {
            glyph["character"]: glyph for glyph in glyph_asset["glyphs"]
        }
        entries = []
        for mapping in candidate["custom_glyphs"]:
            glyph = glyph_by_character[mapping["character"]]
            entries.append(
                {
                    "character": mapping["character"],
                    "tile": mapping["tile"],
                    "tile_source": "custom",
                    "glyph_pattern_2bpp_hex": glyph["tile_2bpp_hex"],
                    "restore_pattern_2bpp_hex": "00 " * 15 + "00",
                }
            )
        return {"entries": entries}

    def build_integrated(self):
        with (
            patch.object(v2_5, "EXPECTED_SOURCE_SHA256", self.source_hash),
            patch.object(v2_5, "EXPECTED_V2_4_5_SHA256", self.base_hash),
            patch.object(menu_pilot, "EXPECTED_SOURCE_SHA256", self.source_hash),
            patch.object(
                v2_5,
                "compile_tile_cache_plan",
                side_effect=self.cache_plan_for_asset,
            ),
            patch.object(
                menu_pilot,
                "compile_tile_cache_plan",
                side_effect=self.cache_plan_for_asset,
            ),
        ):
            return v2_5.build_integrated_menu(
                self.base,
                self.source,
                self.menu_manifest,
                self.glyph_asset,
            )

    def test_gateway_router_branches_to_menu_dialogue_and_normal_paths(self):
        router = v2_5._build_gateway_router(0x5C00, 0x4B00)
        self.assertEqual(
            router,
            bytes.fromhex(
                "C5 D5 E5 F5 F8 0E 2A FE EB 28 13 FE 4A 20 1E "
                "7E FE 49 20 19 F1 E1 D1 C1 CD 00 5C 3E 03 C9 "
                "7E FE 1B 20 0A F1 E1 D1 C1 CD 00 4B 3E 02 C9 "
                "F1 E1 D1 C1 C3 04 40"
            ),
        )

    def test_fixed_gateway_restores_bank_from_ff_a9(self):
        self.assertEqual(
            v2_5.FIXED_GATEWAY_PATCH,
            bytes.fromhex(
                "F5 F3 3E 10 EA 00 20 CD 00 40 F5 FA A9 FF "
                "EA 00 20 FB F1 C3 61 00"
            ),
        )

    def test_menu_restore_helper_uses_menu_marker_without_cursor_gate(self):
        helper = v2_5._build_menu_restore_helper(
            [v2_5.CachedGlyph("中", 0x80, bytes(16))],
            original_patterns_cpu_address=0x5000,
            helper_cpu_address=0x6400,
        )

        self.assertEqual(
            helper[:12],
            bytes.fromhex("C5 D5 E5 F5 FA F2 C4 FE 80 C2 1C 64"),
        )
        self.assertNotIn(bytes.fromhex("FA AD FF FE 3D"), helper)

    def test_builds_deterministic_rom_and_preserves_v2_4_5_features(self):
        target = self.build_integrated()
        self.assertEqual(target, self.build_integrated())
        self.assertEqual(len(target), v2_5.MENU_EXPANDED_SIZE)
        self.assertTrue(verify_rom(target).passed)

        self.assertEqual(
            target[
                v2_5.GATEWAY_OFFSET:
                v2_5.GATEWAY_OFFSET + len(v2_5.MAIN_GATEWAY_PATCH)
            ],
            v2_5.MAIN_GATEWAY_PATCH,
        )
        self.assertEqual(
            target[
                v2_5.MENU_OPEN_HOOK_OFFSET:
                v2_5.MENU_OPEN_HOOK_OFFSET
                + len(v2_5.MENU_OPEN_HOOK_PATCH)
            ],
            v2_5.MENU_OPEN_HOOK_PATCH,
        )
        self.assertEqual(
            target[
                v2_5.MENU_CLOSE_HOOK_OFFSET:
                v2_5.MENU_CLOSE_HOOK_OFFSET
                + len(v2_5.MENU_CLOSE_HOOK_PATCH)
            ],
            v2_5.MENU_CLOSE_HOOK_PATCH,
        )
        self.assertEqual(
            target[
                v2_5.DIALOGUE_RESTORE_HOOK_OFFSET:
                v2_5.DIALOGUE_RESTORE_HOOK_OFFSET
                + len(v2_5.DIALOGUE_RESTORE_HOOK_PATCH)
            ],
            v2_5.DIALOGUE_RESTORE_HOOK_PATCH,
        )
        self.assertEqual(
            target[0xE0:0xE0 + len(v2_5.FIXED_GATEWAY_PATCH)],
            v2_5.FIXED_GATEWAY_PATCH,
        )
        self.assertEqual(
            target[
                v2_5.RESTORE_HELPER_OFFSET:
                v2_5.RESTORE_HELPER_OFFSET
                + len(v2_5.ENTRY_RETURN_HANDLER)
            ],
            v2_5.ENTRY_RETURN_HANDLER,
        )

        _, codes = create_glyph_map(self.glyph_asset)
        for _, offset, source_payload, text in MENU_ITEMS:
            expected_text = bytes(codes[character] for character in text)
            body_length = len(source_payload) - 1
            expected = expected_text + bytes(
                [SPACE_CODE]
                * (body_length - len(expected_text))
            ) + bytes((0x7F,))
            self.assertEqual(target[offset:offset + len(source_payload)], expected)

        for offset in (
            v2_5.GATEWAY_OFFSET,
            v2_5.ENTRY_OFFSET,
            v2_5.MENU_OPEN_HOOK_OFFSET,
            v2_5.MENU_CLOSE_HOOK_OFFSET,
            v2_5.DIALOGUE_RESTORE_HOOK_OFFSET,
            0x61,
            0xE0,
        ):
            length = (
                len(v2_5.ENTRY_RETURN_HANDLER)
                if offset == 0x61
                else len(v2_5.FIXED_GATEWAY_PATCH)
                if offset == 0xE0
                else len(v2_5.MAIN_GATEWAY_PATCH)
                if offset == v2_5.GATEWAY_OFFSET
                else len(v2_5.MENU_CLOSE_HOOK_PATCH)
                if offset == v2_5.MENU_CLOSE_HOOK_OFFSET
                else len(v2_5.MENU_OPEN_HOOK_PATCH)
                if offset == v2_5.MENU_OPEN_HOOK_OFFSET
                else len(v2_5.DIALOGUE_RESTORE_HOOK_PATCH)
                if offset == v2_5.DIALOGUE_RESTORE_HOOK_OFFSET
                else len(v2_5.build_open_helper())
            )
            self.assertEqual(
                target[offset:offset + length],
                target[
                    v2_5.MBC1_MIRROR_OFFSET + offset:
                    v2_5.MBC1_MIRROR_OFFSET + offset + length
                ],
            )
        self.assertEqual(
            target[
                v2_5.MENU_EXTENSION_ALIAS_OFFSET:
                v2_5.MENU_EXTENSION_ALIAS_OFFSET + v2_5.ROM_BANK_SIZE
            ],
            target[
                SOURCE_SIZE:SOURCE_SIZE + v2_5.ROM_BANK_SIZE
            ],
        )

    def test_rejects_modified_v2_4_5_gateway_before_overwriting(self):
        bad_base = bytearray(self.base)
        bad_base[v2_5.GATEWAY_OFFSET] ^= 0x01
        bad_base = update_checksums(bad_base)
        bad_hash = hashlib.sha256(bad_base).hexdigest()
        with (
            patch.object(v2_5, "EXPECTED_SOURCE_SHA256", self.source_hash),
            patch.object(v2_5, "EXPECTED_V2_4_5_SHA256", bad_hash),
        ):
            with self.assertRaisesRegex(ValueError, "main gateway"):
                v2_5.build_integrated_menu(
                    bad_base,
                    self.source,
                    self.menu_manifest,
                    self.glyph_asset,
                )


if __name__ == "__main__":
    unittest.main()
