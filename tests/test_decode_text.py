import unittest
from pathlib import Path

from scripts.decode_text import decode_record, load_code_map, read_records


ROOT = Path(__file__).resolve().parents[1]


class DecodeRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code_map = load_code_map(ROOT / "data" / "text_decode_map.json")

    def test_decodes_known_tokens_and_preserves_unresolved_values(self):
        record = {
            "id": "test-record",
            "tokens": [
                {"offset": "0x0000", "raw_hex": "1D", "kind": "glyph_code"},
                {"offset": "0x0001", "raw_hex": "4D", "kind": "special_glyph"},
                {"offset": "0x0002", "raw_hex": "7D", "kind": "control"},
                {"offset": "0x0003", "raw_hex": "FE", "kind": "unknown"},
            ],
        }

        decoded = decode_record(record, self.code_map)

        self.assertEqual(decoded["decoded_text"], "な[空白图块$4D]\n[UNKNOWN $FE]")
        self.assertEqual(
            decoded["decode_diagnostics"]["unknown_tokens"],
            [{"offset": "0x0003", "raw_hex": "FE", "kind": "unknown"}],
        )
        self.assertEqual(
            decoded["decode_diagnostics"]["unresolved_tokens"][0]["raw_hex"],
            "4D",
        )
        self.assertEqual(record["tokens"][0]["raw_hex"], "1D")

    def test_reads_jsonl_records(self):
        records = read_records('{"id":"one"}\n\n{"id":"two"}\n', "test")

        self.assertEqual([record["id"] for record in records], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
