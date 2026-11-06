import unittest

from scripts.decode_gb_resource import decode_resource


ROM_SIZE = 16 * 0x4000
BANK_SIZE = 0x4000


def make_rom(bank: int, descriptor: int, header: bytes, payload_offset: int, payload: bytes):
    rom = bytearray(ROM_SIZE)
    base = bank * BANK_SIZE
    descriptor_offset = base + descriptor - 0x4000
    payload_address = base + payload_offset - 0x4000
    rom[descriptor_offset:descriptor_offset + len(header)] = header
    rom[payload_address:payload_address + len(payload)] = payload
    return bytes(rom)


class DecodeResourceTests(unittest.TestCase):
    def test_decodes_literal_run_with_one_byte_descriptor(self):
        descriptor = 0x4100
        rom = make_rom(
            bank=1,
            descriptor=descriptor,
            header=bytes.fromhex("00 C0"),
            payload_offset=descriptor + 2,
            payload=b"Z",
        )

        decoded = decode_resource(rom, 1, descriptor, 1)

        self.assertEqual(decoded, b"Z")

    def test_decodes_literal_run_and_short_backreference(self):
        descriptor = 0x4200
        rom = make_rom(
            bank=2,
            descriptor=descriptor,
            header=bytes.fromhex("00 C8"),
            payload_offset=descriptor + 2,
            payload=b"A",
        )

        decoded = decode_resource(rom, 2, descriptor, 3)

        self.assertEqual(decoded, b"AAA")

    def test_decodes_overlapping_long_backreference(self):
        descriptor = 0x4300
        rom = make_rom(
            bank=3,
            descriptor=descriptor,
            header=bytes.fromhex("00 C0"),
            payload_offset=descriptor + 2,
            payload=b"A",
        )

        decoded = decode_resource(rom, 3, descriptor, 4)

        self.assertEqual(decoded, b"AAAA")

    def test_rejects_backreference_before_output_start(self):
        descriptor = 0x4400
        rom = make_rom(
            bank=4,
            descriptor=descriptor,
            header=bytes.fromhex("00 00 00 00"),
            payload_offset=descriptor + 4,
            payload=b"",
        )

        with self.assertRaisesRegex(ValueError, "before the decoded output"):
            decode_resource(rom, 4, descriptor, 3)

    def test_decodes_two_byte_relative_descriptor(self):
        descriptor = 0x55D3
        payload_address = 0x5849
        relative = payload_address - (descriptor + 2) - 1
        header = bytes((0x80 | (relative >> 8), relative & 0xFF, 0xD4))
        rom = make_rom(
            bank=5,
            descriptor=descriptor,
            header=header,
            payload_offset=payload_address,
            payload=b"ABC",
        )

        decoded = decode_resource(rom, 5, descriptor, 3)

        self.assertEqual(decoded, b"ABC")

    def test_rejects_invalid_bank_and_output_length(self):
        rom = bytes(ROM_SIZE)

        with self.assertRaisesRegex(ValueError, "ROM bank"):
            decode_resource(rom, 16, 0x4000, 1)
        with self.assertRaisesRegex(ValueError, "output length"):
            decode_resource(rom, 0, 0x4000, 0)


if __name__ == "__main__":
    unittest.main()
