import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_rom import apply_patch_manifest, build_rom
from scripts.rom_checksums import update_checksums, verify_rom


class ApplyPatchManifestTests(unittest.TestCase):
    def setUp(self):
        self.rom = bytes((0x00, 0x10, 0x20, 0x30, 0x40, 0x50))
        self.manifest = {
            "schema_version": 1,
            "source_rom_sha256": hashlib.sha256(self.rom).hexdigest(),
            "patches": [
                {
                    "id": "first-edit",
                    "offset": "0x1",
                    "expected_hex": "10 20",
                    "replacement_hex": "AA BB",
                },
                {
                    "id": "second-edit",
                    "offset": "0x5",
                    "expected_hex": "50",
                    "replacement_hex": "FF",
                },
            ],
        }

    def test_applies_edits_without_changing_rom_size(self):
        patched = apply_patch_manifest(self.rom, self.manifest)

        self.assertEqual(patched, bytes((0x00, 0xAA, 0xBB, 0x30, 0x40, 0xFF)))
        self.assertEqual(len(patched), len(self.rom))
        self.assertEqual(self.rom, bytes((0x00, 0x10, 0x20, 0x30, 0x40, 0x50)))

    def test_rejects_source_hash_mismatch(self):
        self.manifest["source_rom_sha256"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            apply_patch_manifest(self.rom, self.manifest)

    def test_rejects_expected_bytes_mismatch(self):
        self.manifest["patches"][0]["expected_hex"] = "11 20"

        with self.assertRaisesRegex(ValueError, "do not match expected_hex"):
            apply_patch_manifest(self.rom, self.manifest)

    def test_rejects_overlapping_patches(self):
        self.manifest["patches"][1]["offset"] = "0x2"
        self.manifest["patches"][1]["expected_hex"] = "20"
        self.manifest["patches"][1]["replacement_hex"] = "EE"

        with self.assertRaisesRegex(ValueError, "patches overlap"):
            apply_patch_manifest(self.rom, self.manifest)

    def test_rejects_different_replacement_length(self):
        self.manifest["patches"][0]["replacement_hex"] = "AA"

        with self.assertRaisesRegex(ValueError, "must have equal lengths"):
            apply_patch_manifest(self.rom, self.manifest)

    def test_rejects_empty_patch_list(self):
        self.manifest["patches"] = []

        with self.assertRaisesRegex(ValueError, "non-empty list"):
            apply_patch_manifest(self.rom, self.manifest)


class BuildRomTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.source_path = self.directory / "source.gb"
        self.manifest_path = self.directory / "patches.json"
        self.output_path = self.directory / "output.gb"
        source_rom = bytearray(0x8000)
        source_rom[0x148] = 0x00
        self.source_rom = update_checksums(source_rom)
        self.source_path.write_bytes(self.source_rom)
        manifest = {
            "schema_version": 1,
            "source_rom_sha256": hashlib.sha256(self.source_rom).hexdigest(),
            "patches": [
                {
                    "id": "sample",
                    "offset": "0x200",
                    "expected_hex": f"{self.source_rom[0x200]:02X}",
                    "replacement_hex": "FE",
                }
            ],
        }
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_writes_separate_output_and_preserves_source(self):
        output, size, digest, patch_count = build_rom(
            self.source_path,
            self.manifest_path,
            self.output_path,
        )

        self.assertEqual(output, self.output_path.resolve())
        self.assertEqual(self.source_path.read_bytes(), self.source_rom)
        self.assertEqual(self.output_path.read_bytes()[0x200], 0xFE)
        self.assertEqual(size, len(self.source_rom))
        self.assertEqual(digest, hashlib.sha256(self.output_path.read_bytes()).hexdigest())
        self.assertEqual(patch_count, 1)
        self.assertTrue(verify_rom(self.output_path.read_bytes()).passed)

    def test_refuses_to_overwrite_existing_output(self):
        self.output_path.write_bytes(b"existing")

        with self.assertRaisesRegex(FileExistsError, "pass --overwrite"):
            build_rom(self.source_path, self.manifest_path, self.output_path)

        self.assertEqual(self.output_path.read_bytes(), b"existing")

    def test_allows_explicit_output_overwrite(self):
        self.output_path.write_bytes(b"existing")

        build_rom(
            self.source_path,
            self.manifest_path,
            self.output_path,
            overwrite=True,
        )

        output_rom = self.output_path.read_bytes()
        self.assertEqual(output_rom[0x200], 0xFE)
        self.assertTrue(verify_rom(output_rom).passed)

    def test_refuses_source_as_output(self):
        with self.assertRaisesRegex(ValueError, "must differ from the source"):
            build_rom(self.source_path, self.manifest_path, self.source_path)


if __name__ == "__main__":
    unittest.main()
