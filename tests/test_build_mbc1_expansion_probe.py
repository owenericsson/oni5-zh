import unittest

from scripts.build_mbc1_expansion_probe import (
    BANK_SWITCH_HELPER,
    BANK_SWITCH_HELPER_OFFSET,
    BANK_SWITCH_MARKER,
    BANK_SWITCH_MARKER_OFFSET,
    BANK_RESTORE_STUB,
    BANK_RESTORE_STUB_OFFSET,
    BANK_RESTORED_READBACK,
    BANK_RESTORED_READBACK_OFFSET,
    ENTRY_CODE,
    ENTRY_OFFSET,
    EXPANDED_SIZE,
    GATEWAY_OFFSET,
    GATEWAY_PATCH,
    POSTLUDE_CODE,
    POSTLUDE_OFFSET,
    SOURCE_SIZE,
    build_expansion_probe,
)
from scripts.rom_checksums import update_checksums, verify_rom


class BuildMbc1ExpansionProbeTests(unittest.TestCase):
    def setUp(self):
        source = bytearray(SOURCE_SIZE)
        source[0x147] = 0x03
        source[0x148] = 0x03
        source[0xA0:0xC0] = bytes([0xFF]) * 0x20
        source[0xE0:0x100] = bytes([0xFF]) * 0x20
        source[GATEWAY_OFFSET:GATEWAY_OFFSET + 4] = bytes.fromhex("FE 60 30 0E")
        self.source = update_checksums(source)

    def test_expands_to_declared_512_kib_and_updates_checksums(self):
        probe = build_expansion_probe(self.source)

        self.assertEqual(len(probe), EXPANDED_SIZE)
        self.assertEqual(probe[0x147], 0x03)
        self.assertEqual(probe[0x148], 0x04)
        self.assertTrue(verify_rom(probe).passed)
        self.assertEqual(len(self.source), SOURCE_SIZE)
        self.assertEqual(self.source[0x148], 0x03)

    def test_installs_gateway_helper_marker_and_result_code(self):
        probe = build_expansion_probe(self.source)

        self.assertEqual(probe[GATEWAY_OFFSET:GATEWAY_OFFSET + 4], GATEWAY_PATCH)
        self.assertEqual(probe[ENTRY_OFFSET:ENTRY_OFFSET + len(ENTRY_CODE)], ENTRY_CODE)
        self.assertEqual(
            probe[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)],
            POSTLUDE_CODE,
        )
        self.assertEqual(
            probe[BANK_SWITCH_HELPER_OFFSET:BANK_SWITCH_HELPER_OFFSET + len(BANK_SWITCH_HELPER)],
            BANK_SWITCH_HELPER,
        )
        self.assertEqual(
            probe[BANK_RESTORE_STUB_OFFSET:BANK_RESTORE_STUB_OFFSET + len(BANK_RESTORE_STUB)],
            BANK_RESTORE_STUB,
        )
        self.assertEqual(
            probe[
                BANK_RESTORED_READBACK_OFFSET:
                BANK_RESTORED_READBACK_OFFSET + len(BANK_RESTORED_READBACK)
            ],
            BANK_RESTORED_READBACK,
        )
        self.assertEqual(probe[BANK_SWITCH_MARKER_OFFSET], BANK_SWITCH_MARKER)

    def test_gateway_only_switches_for_noticeboard_first_character(self):
        self.assertEqual(GATEWAY_PATCH, bytes.fromhex("C3 A0 00 00"))
        self.assertEqual(
            ENTRY_CODE[:8],
            bytes.fromhex("F5 FA AA FF FE 0C 20 46"),
        )
        self.assertEqual(
            ENTRY_CODE[8:15],
            bytes.fromhex("FA AE FF FE 0E 20 3F"),
        )
        self.assertEqual(
            ENTRY_CODE[15:22],
            bytes.fromhex("FA AD FF FE 34 20 38"),
        )
        self.assertEqual(ENTRY_CODE[22:25], bytes.fromhex("C3 E0 00"))
        skip_target = POSTLUDE_OFFSET + 14
        for branch_offset in (6, 13, 20):
            branch_target = (
                ENTRY_OFFSET + branch_offset + 2 + ENTRY_CODE[branch_offset + 1]
            )
            self.assertEqual(branch_target, skip_target)
        self.assertEqual(BANK_SWITCH_HELPER[-3:], bytes.fromhex("C3 F7 00"))
        self.assertEqual(BANK_RESTORE_STUB, bytes.fromhex("FA F1 C4 EA 00 20 C3 B9 00"))
        self.assertEqual(BANK_RESTORED_READBACK, bytes.fromhex("FA 33 4E EA F2 C4 C9"))

    def test_rejects_bad_source_header(self):
        invalid = bytearray(self.source)
        invalid[0x147] = 0x01
        invalid_source = update_checksums(invalid)

        with self.assertRaisesRegex(ValueError, "MBC1"):
            build_expansion_probe(invalid_source)

    def test_rejects_occupied_probe_code_area(self):
        invalid = bytearray(self.source)
        invalid[ENTRY_OFFSET] = 0x00
        invalid_source = update_checksums(invalid)

        with self.assertRaisesRegex(ValueError, "entry area"):
            build_expansion_probe(invalid_source)

    def test_rejects_wrong_gateway_bytes(self):
        invalid = bytearray(self.source)
        invalid[GATEWAY_OFFSET] = 0x00
        invalid_source = update_checksums(invalid)

        with self.assertRaisesRegex(ValueError, "gateway bytes"):
            build_expansion_probe(invalid_source)


if __name__ == "__main__":
    unittest.main()
