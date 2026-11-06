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


if __name__ == "__main__":
    unittest.main()
