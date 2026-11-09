import unittest

from scripts.rom_checksums import update_checksums, verify_rom


def make_rom(size_code=0x00, size=0x8000):
    rom = bytearray(size)
    rom[0x148] = size_code
    return update_checksums(rom)


class RomChecksumsTests(unittest.TestCase):
    def test_accepts_matching_size_and_checksums(self):
        verification = verify_rom(make_rom())

        self.assertTrue(verification.passed)
        self.assertEqual(verification.expected_size, 0x8000)

    def test_detects_rom_size_mismatch(self):
        verification = verify_rom(make_rom(size_code=0x01))

        self.assertFalse(verification.size_matches)
        self.assertTrue(verification.header_checksum_matches)
        self.assertTrue(verification.global_checksum_matches)
        self.assertFalse(verification.passed)

    def test_detects_header_checksum_mismatch(self):
        rom = bytearray(make_rom())
        rom[0x14D] ^= 0x01

        verification = verify_rom(rom)

        self.assertFalse(verification.header_checksum_matches)
        self.assertFalse(verification.global_checksum_matches)
        self.assertFalse(verification.passed)

    def test_detects_global_checksum_mismatch(self):
        rom = bytearray(make_rom())
        rom[0x14E] ^= 0x01

        verification = verify_rom(rom)

        self.assertTrue(verification.header_checksum_matches)
        self.assertFalse(verification.global_checksum_matches)
        self.assertFalse(verification.passed)

    def test_detects_unknown_rom_size_code(self):
        verification = verify_rom(make_rom(size_code=0x40))

        self.assertIsNone(verification.expected_size)
        self.assertFalse(verification.size_matches)
        self.assertFalse(verification.passed)

    def test_rejects_rom_without_complete_header(self):
        with self.assertRaisesRegex(ValueError, "too small"):
            verify_rom(bytes(0x14F))


if __name__ == "__main__":
    unittest.main()
