import unittest

from scripts.extract_text import extract_record


class ExtractRecordTests(unittest.TestCase):
    def setUp(self):
        self.rom = bytearray(0x8000)
        self.rom[0x4000:0x4004] = bytes((0x57, 0x12, 0xAA, 0x7F))
        self.template = {
            "id": "test-bank01-004001",
            "source": {
                "bank": {
                    "logical": "0x01",
                    "physical": "0x01",
                    "size": "0x4000",
                },
                "event_command": {
                    "opcode": "0x57",
                    "rom_offset": "0x004000",
                    "cpu_address": "0x4000",
                },
                "payload": {
                    "start": "0x004001",
                    "end_exclusive": "0x004004",
                    "terminator": "0x7F",
                },
            },
            "token_annotations": [
                {"offset": "0x004001", "code": "0x12", "kind": "glyph_code"},
                {"offset": "0x004003", "code": "0x7F", "kind": "terminator"},
            ],
        }

    def test_extracts_bytes_and_reports_unannotated_codes(self):
        record = extract_record(bytes(self.rom), self.template, "test-hash")

        self.assertEqual(record["raw_hex"], "12 AA 7F")
        self.assertEqual(
            [token["offset"] for token in record["tokens"]],
            ["0x004001", "0x004002", "0x004003"],
        )
        self.assertEqual(record["tokens"][1]["kind"], "unknown")
        self.assertEqual(
            record["diagnostics"]["unknown_tokens"],
            [{"offset": "0x004002", "raw_hex": "AA"}],
        )

    def test_rejects_mismatched_event_opcode(self):
        self.rom[0x4000] = 0x56

        with self.assertRaisesRegex(ValueError, "event opcode mismatch"):
            extract_record(bytes(self.rom), self.template, "test-hash")

    def test_rejects_mismatched_terminator(self):
        self.rom[0x4003] = 0x00

        with self.assertRaisesRegex(ValueError, "terminator mismatch"):
            extract_record(bytes(self.rom), self.template, "test-hash")

    def test_extracts_text_from_a_banked_lower_window_pointer(self):
        rom = bytearray(0x40000)
        payload_start = 0x0C * 0x4000 + 0x0E8E
        rom[payload_start:payload_start + 4] = bytes((0xB9, 0x7D, 0x3B, 0x7F))
        template = {
            "id": "test-bank0c-pointer-00e8e",
            "source": {
                "bank": {
                    "logical": "0x0C",
                    "physical": "0x0C",
                    "size": "0x4000",
                },
                "pointer": {
                    "window": "lower",
                    "cpu_address": "0x0E8E",
                },
                "payload": {
                    "start": "0x030E8E",
                    "end_exclusive": "0x030E92",
                    "terminator": "0x7F",
                },
            },
            "token_annotations": [
                {"offset": "0x030E8E", "code": "0xB9", "kind": "macro_ref"},
                {"offset": "0x030E8F", "code": "0x7D", "kind": "control"},
                {"offset": "0x030E90", "code": "0x3B", "kind": "glyph_code"},
            ],
        }

        record = extract_record(bytes(rom), template, "test-hash")

        self.assertEqual(record["raw_hex"], "B9 7D 3B 7F")
        self.assertEqual(record["source"]["pointer"]["cpu_address"], "0x0E8E")
        self.assertEqual(
            [token["offset"] for token in record["tokens"]],
            ["0x030E8E", "0x030E8F", "0x030E90", "0x030E91"],
        )

    def test_rejects_pointer_that_does_not_map_to_payload_start(self):
        rom = bytearray(0x40000)
        payload_start = 0x0C * 0x4000 + 0x0E8E
        rom[payload_start:payload_start + 2] = bytes((0x12, 0x7F))
        template = {
            "id": "test-pointer-mismatch",
            "source": {
                "bank": {
                    "logical": "0x0C",
                    "physical": "0x0C",
                    "size": "0x4000",
                },
                "pointer": {
                    "window": "lower",
                    "cpu_address": "0x0E8E",
                },
                "payload": {
                    "start": "0x030E8F",
                    "end_exclusive": "0x030E91",
                    "terminator": "0x7F",
                },
            },
        }

        with self.assertRaisesRegex(ValueError, "pointer maps to ROM offset"):
            extract_record(bytes(rom), template, "test-hash")


if __name__ == "__main__":
    unittest.main()
