import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_menu_pilot as menu_pilot
from scripts.build_mbc1_expansion_probe import (
    GATEWAY_EXPECTED,
    GATEWAY_OFFSET,
    SOURCE_SIZE,
)
from scripts.build_rom import apply_patch_manifest
from scripts.compile_translation_encoding import create_glyph_map
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]


class BuildMenuPilotTests(unittest.TestCase):
    def setUp(self):
        source = bytearray([0xFF]) * SOURCE_SIZE
        source[0x147] = 0x03
        source[0x148] = 0x03
        source[0x00C0:0x00E0] = bytes(range(0x20))
        source[GATEWAY_OFFSET:GATEWAY_OFFSET + len(GATEWAY_EXPECTED)] = GATEWAY_EXPECTED
        source[
            menu_pilot.GLYPH_LOAD_HOOK_OFFSET:
            menu_pilot.GLYPH_LOAD_HOOK_OFFSET
            + len(menu_pilot.GLYPH_LOAD_HOOK_EXPECTED)
        ] = menu_pilot.GLYPH_LOAD_HOOK_EXPECTED
        source[
            menu_pilot.RESTORE_HOOK_OFFSET:
            menu_pilot.RESTORE_HOOK_OFFSET + len(menu_pilot.RESTORE_HOOK_EXPECTED)
        ] = menu_pilot.RESTORE_HOOK_EXPECTED
        self.menu_manifest = json.loads(
            (ROOT / "data" / "menu_text_manifest.json").read_text(encoding="utf-8")
        )
        self.glyph_asset = json.loads(
            (ROOT / "data" / "menu_chinese_glyphs.json").read_text(encoding="utf-8")
        )
        for _, offset, source_bytes, _ in menu_pilot.MENU_ITEMS:
            source[offset:offset + len(source_bytes)] = source_bytes
        self.source = update_checksums(source)
        self.source_hash = hashlib.sha256(self.source).hexdigest()
        self.menu_manifest["source_rom_sha256"] = self.source_hash

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
                }
            )
        return {"entries": entries}

    def build_pilot(self):
        with (
            patch.object(menu_pilot, "EXPECTED_SOURCE_SHA256", self.source_hash),
            patch.object(
                menu_pilot,
                "compile_tile_cache_plan",
                side_effect=self.cache_plan_for_asset,
            ),
        ):
            return menu_pilot.build_menu_pilot(
                self.source,
                self.menu_manifest,
                self.glyph_asset,
            )

    def test_builds_checked_menu_rom_and_preserves_original(self):
        original = self.source
        pilot = self.build_pilot()

        self.assertEqual(self.source, original)
        self.assertEqual(len(pilot), menu_pilot.MENU_EXPANDED_SIZE)
        self.assertEqual(pilot[0x148], menu_pilot.MENU_ROM_SIZE_CODE)
        self.assertEqual(pilot[0x00C0:0x00E0], self.source[0x00C0:0x00E0])
        self.assertTrue(verify_rom(pilot).passed)
        mirror_start = menu_pilot.MBC1_MIRROR_OFFSET
        mirror_end = mirror_start + SOURCE_SIZE
        self.assertEqual(pilot[mirror_start:mirror_start + 0x0134], pilot[:0x0134])
        self.assertEqual(
            pilot[mirror_start + 0x0134:mirror_start + 0x0150],
            self.source[0x0134:0x0150],
        )
        self.assertEqual(pilot[mirror_start + 0x0150:mirror_end], pilot[0x0150:SOURCE_SIZE])
        alias_start = menu_pilot.MENU_EXTENSION_ALIAS_OFFSET
        self.assertEqual(
            pilot[alias_start:alias_start + menu_pilot.ROM_BANK_SIZE],
            pilot[SOURCE_SIZE:SOURCE_SIZE + menu_pilot.ROM_BANK_SIZE],
        )
        self.assertEqual(pilot[GATEWAY_OFFSET:GATEWAY_OFFSET + 4], GATEWAY_EXPECTED)
        self.assertEqual(
            pilot[
                menu_pilot.GLYPH_LOAD_HOOK_OFFSET:
                menu_pilot.GLYPH_LOAD_HOOK_OFFSET
                + len(menu_pilot.GLYPH_LOAD_HOOK_PATCH)
            ],
            menu_pilot.GLYPH_LOAD_HOOK_PATCH,
        )
        self.assertEqual(
            pilot[
                menu_pilot.RESTORE_HOOK_OFFSET:
                menu_pilot.RESTORE_HOOK_OFFSET + len(menu_pilot.RESTORE_HOOK_PATCH)
            ],
            menu_pilot.RESTORE_HOOK_PATCH,
        )

    def test_encodes_confirmed_labels_in_fixed_original_slots(self):
        pilot = self.build_pilot()
        _, codes = create_glyph_map(self.glyph_asset)

        for record_id, offset, original, text in menu_pilot.MENU_ITEMS:
            body = bytes(codes[character] for character in text)
            padding_count = len(original) - 1 - len(body)
            expected = body + bytes([menu_pilot.MENU_PADDING_CODE]) * padding_count
            expected += bytes([menu_pilot.MENU_TERMINATOR])
            self.assertEqual(pilot[offset:offset + len(original)], expected, record_id)
            self.assertEqual(len(expected), len(original))

    def test_installs_loader_patterns_and_restore_helpers(self):
        pilot = self.build_pilot()
        candidate = menu_pilot.build_menu_candidate(self.glyph_asset)
        token_map, _ = create_glyph_map(self.glyph_asset)
        glyph_by_character = {
            glyph["character"]: bytes.fromhex(glyph["tile_2bpp_hex"])
            for glyph in self.glyph_asset["glyphs"]
        }
        cached_glyphs = [
            menu_pilot.CachedGlyph(
                mapping["character"],
                int(mapping["tile"], 16),
                glyph_by_character[mapping["character"]],
            )
            for mapping in token_map
        ]

        open_helper = menu_pilot.build_open_helper()
        dispatcher = menu_pilot.build_menu_context_dispatcher()
        loader = menu_pilot.build_loader_helper(
            cached_glyphs,
            0x4200,
            return_a_value=0x01,
        )
        restore_wrapper = menu_pilot.build_restore_hook_helper()
        self.assertEqual(
            pilot[
                menu_pilot.OPEN_HELPER_OFFSET:
                menu_pilot.OPEN_HELPER_OFFSET + len(open_helper)
            ],
            open_helper,
        )
        self.assertEqual(
            pilot[
                menu_pilot.RESTORE_HELPER_OFFSET:
                menu_pilot.RESTORE_HELPER_OFFSET + len(restore_wrapper)
            ],
            restore_wrapper,
        )
        self.assertEqual(
            pilot[
                menu_pilot.MENU_CONTEXT_DISPATCHER_OFFSET:
                menu_pilot.MENU_CONTEXT_DISPATCHER_OFFSET + len(dispatcher)
            ],
            dispatcher,
        )
        self.assertEqual(
            pilot[
                menu_pilot.LOADER_CODE_OFFSET:
                menu_pilot.LOADER_CODE_OFFSET + len(loader)
            ],
            loader,
        )
        self.assertIn(bytes.fromhex("7C FE 66"), open_helper)
        self.assertIn(bytes.fromhex("7D FE 9C"), open_helper)
        self.assertIn(bytes.fromhex("F3 3E 10 EA 00 20"), open_helper)
        self.assertIn(bytes.fromhex("EA 00 20 FB"), open_helper)
        self.assertIn(bytes.fromhex("CD 00 40"), open_helper)
        self.assertLessEqual(len(open_helper), menu_pilot.OPEN_HELPER_SIZE)
        self.assertEqual(open_helper[-7:], bytes.fromhex("F1 E5 D5 F5 C3 E8 19"))
        self.assertIn(bytes.fromhex("F3 3E 10 EA 00 20"), restore_wrapper)
        self.assertIn(bytes.fromhex("3E FF EA 39 D2"), restore_wrapper)
        self.assertIn(bytes.fromhex("3E 02 EA 00 20 FB"), restore_wrapper)
        self.assertLessEqual(len(restore_wrapper), menu_pilot.RESTORE_HELPER_SIZE)
        self.assertNotIn(bytes.fromhex("FA AA FF"), restore_wrapper)
        self.assertEqual(
            dispatcher,
            bytes.fromhex("FA F2 C4 B7 28 03 3E 01 C9 C3 40 40"),
        )
        self.assertEqual(
            loader[-9:],
            bytes.fromhex("EA F2 C4 3E 01 E1 D1 C1 C9"),
        )
        self.assertEqual(
            candidate["provisional_custom_tile_pool"]["count"],
            menu_pilot.MENU_GLYPH_COUNT,
        )
        for index, mapping in enumerate(token_map):
            tile = int(mapping["tile"], 16)
            pattern_offset = menu_pilot.GLYPH_PATTERN_OFFSET + index * 16
            self.assertEqual(
                pilot[pattern_offset:pattern_offset + 16],
                glyph_by_character[mapping["character"]],
            )
            self.assertGreaterEqual(tile, 0x80)
            self.assertLess(tile, 0xC0)
        self.assertIn(
            bytes.fromhex("AF EA F2 C4"),
            pilot[
                menu_pilot.RESTORE_BANK_HELPER_OFFSET:
                menu_pilot.RESTORE_BANK_HELPER_OFFSET + 0x200
            ],
        )

    def test_patch_manifest_recreates_the_verified_pilot(self):
        pilot = self.build_pilot()
        patch_manifest = menu_pilot.create_patch_manifest(self.source, pilot)

        self.assertEqual(
            patch_manifest["source_rom_sha256"],
            self.source_hash,
        )
        self.assertEqual(
            patch_manifest["scope"],
            (
                "confirmed main-command menu labels, temporary glyph cache, "
                "and MBC1 bank mirrors"
            ),
        )
        rebuilt = update_checksums(apply_patch_manifest(self.source, patch_manifest))
        self.assertEqual(rebuilt, pilot)

    def test_rejects_unexpected_menu_source_bytes(self):
        bad_source = bytearray(self.source)
        bad_source[menu_pilot.MENU_ITEMS[0][1]] ^= 0x01
        bad_source = update_checksums(bad_source)
        bad_hash = hashlib.sha256(bad_source).hexdigest()
        manifest = dict(self.menu_manifest)
        manifest["source_rom_sha256"] = bad_hash
        with (
            patch.object(menu_pilot, "EXPECTED_SOURCE_SHA256", bad_hash),
            patch.object(
                menu_pilot,
                "compile_tile_cache_plan",
                side_effect=self.cache_plan_for_asset,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "original ROM bytes"):
                menu_pilot.build_menu_pilot(bad_source, manifest, self.glyph_asset)


if __name__ == "__main__":
    unittest.main()
