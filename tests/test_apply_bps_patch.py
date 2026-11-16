import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.apply_bps_patch import (
    apply_bps_patch,
    apply_bps_patch_file,
    create_bps_patch,
)


def encode_number(value):
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            encoded.append(byte | 0x80)
            return bytes(encoded)
        encoded.append(byte)
        value -= 1


def encode_signed_number(value):
    encoded_value = -value * 2 + 1 if value < 0 else value * 2
    return encode_number(encoded_value)


def encode_action(action_type, length):
    return encode_number(((length - 1) << 2) | action_type)


def build_patch(source, target, actions):
    body = bytearray(b"BPS1")
    body.extend(encode_number(len(source)))
    body.extend(encode_number(len(target)))
    body.extend(encode_number(0))
    body.extend(actions)
    body.extend(struct.pack("<II", zlib.crc32(source), zlib.crc32(target)))
    body.extend(struct.pack("<I", zlib.crc32(body)))
    return bytes(body)


class ApplyBpsPatchTests(unittest.TestCase):
    def test_created_patch_round_trips_changed_and_expanded_target(self):
        source = b"original source"
        target = b"translated target" + b"\xFF" * 300

        patch = create_bps_patch(source, target)

        self.assertEqual(apply_bps_patch(source, patch), target)

    def test_created_patch_uses_target_copy_for_repeated_target_data(self):
        source = b"abc"
        target = b"abcXXabc"

        patch = create_bps_patch(source, target, ((5, 0, 3),))

        self.assertEqual(apply_bps_patch(source, patch), target)

    def test_decodes_multi_byte_lengths_and_sizes(self):
        source = bytes(range(256))
        target = source[:128] + b"Z" * 128
        actions = (
            encode_action(0, 128)
            + encode_action(1, 128)
            + b"Z" * 128
        )

        self.assertEqual(apply_bps_patch(source, build_patch(source, target, actions)), target)

    def test_supports_negative_source_copy_offsets(self):
        source = b"ABCDEF"
        target = b"DEFABC"
        actions = (
            encode_action(2, 3)
            + encode_signed_number(3)
            + encode_action(2, 3)
            + encode_signed_number(-6)
        )

        self.assertEqual(apply_bps_patch(source, build_patch(source, target, actions)), target)

    def test_applies_source_read_target_read_source_copy_and_overlapping_target_copy(self):
        source = b"abcabc"
        target = b"abcXabcXabcXabc"
        actions = bytearray()
        actions.extend(encode_action(0, 3))
        actions.extend(encode_action(1, 1))
        actions.extend(b"X")
        actions.extend(encode_action(2, 3))
        actions.extend(encode_signed_number(3))
        actions.extend(encode_action(3, 8))
        actions.extend(encode_signed_number(3))
        patch = build_patch(source, target, actions)

        self.assertEqual(apply_bps_patch(source, patch), target)

    def test_rejects_source_checksum_mismatch(self):
        patch = build_patch(b"abc", b"xyz", encode_action(1, 3) + b"xyz")

        with self.assertRaisesRegex(ValueError, "source ROM checksum"):
            apply_bps_patch(b"abd", patch)

    def test_rejects_patch_checksum_mismatch(self):
        patch = bytearray(build_patch(b"abc", b"xyz", encode_action(1, 3) + b"xyz"))
        patch[-1] ^= 0x01

        with self.assertRaisesRegex(ValueError, "BPS patch checksum"):
            apply_bps_patch(b"abc", bytes(patch))

    def test_rejects_target_copy_before_any_target_data_exists(self):
        actions = encode_action(3, 1) + encode_signed_number(0)
        patch = build_patch(b"abc", b"x", actions)

        with self.assertRaisesRegex(ValueError, "TargetCopy"):
            apply_bps_patch(b"abc", patch)

    def test_rejects_non_bps_input(self):
        with self.assertRaisesRegex(ValueError, "BPS1"):
            apply_bps_patch(b"abc", b"not a patch")

    def test_file_wrapper_preserves_source_and_writes_separate_output(self):
        source = b"abc"
        target = b"xyz"
        patch_data = build_patch(source, target, encode_action(1, 3) + target)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source.gb"
            patch_path = root / "change.bps"
            output_path = root / "output.gb"
            source_path.write_bytes(source)
            patch_path.write_bytes(patch_data)

            with patch(
                "scripts.apply_bps_patch.verify_rom",
                return_value=SimpleNamespace(passed=True),
            ):
                apply_bps_patch_file(source_path, patch_path, output_path)

            self.assertEqual(source_path.read_bytes(), source)
            self.assertEqual(output_path.read_bytes(), target)


if __name__ == "__main__":
    unittest.main()
