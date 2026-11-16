"""Apply a BPS patch to a local Game Boy ROM without modifying the source."""
import argparse
import hashlib
import struct
import zlib
from pathlib import Path

if __package__:
    from .build_rom import write_output
    from .rom_checksums import verify_rom
else:
    from build_rom import write_output
    from rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]
PATCH_MAGIC = b"BPS1"
FOOTER_SIZE = 12
MAX_ROM_SIZE = 8 * 1024 * 1024
MAX_BPS_INTEGER = (1 << 63) - 1


def read_number(data: bytes, position: int, limit: int) -> tuple[int, int]:
    value = 0
    shift = 1
    for _ in range(10):
        if position >= limit:
            raise ValueError("truncated BPS variable-length integer")
        byte = data[position]
        position += 1
        increment = (byte & 0x7F) * shift
        if increment > MAX_BPS_INTEGER - value:
            raise ValueError("BPS variable-length integer exceeds the supported range")
        value += increment
        if byte & 0x80:
            return value, position
        if shift > MAX_BPS_INTEGER >> 7:
            raise ValueError("BPS variable-length integer exceeds the supported range")
        shift <<= 7
        if shift > MAX_BPS_INTEGER - value:
            raise ValueError("BPS variable-length integer exceeds the supported range")
        value += shift
    raise ValueError("BPS variable-length integer is too long")


def read_signed_number(data: bytes, position: int, limit: int) -> tuple[int, int]:
    value, position = read_number(data, position, limit)
    magnitude = value >> 1
    return (-magnitude if value & 1 else magnitude), position


def write_number(value: int) -> bytes:
    if not 0 <= value <= MAX_BPS_INTEGER:
        raise ValueError("BPS integer is outside the supported range")
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            encoded.append(byte | 0x80)
            return bytes(encoded)
        encoded.append(byte)
        value -= 1


def write_signed_number(value: int) -> bytes:
    encoded = -value * 2 + 1 if value < 0 else value * 2
    return write_number(encoded)


def encode_action(action_type: int, length: int) -> bytes:
    if action_type not in {0, 1, 2, 3} or length <= 0:
        raise ValueError("BPS action type must be 0-3 and length must be positive")
    return write_number(((length - 1) << 2) | action_type)


def create_bps_patch(
    source: bytes,
    target: bytes,
    target_copy_spans: tuple[tuple[int, int, int], ...] = (),
) -> bytes:
    if len(target) > MAX_ROM_SIZE:
        raise ValueError(f"target size exceeds the {MAX_ROM_SIZE}-byte ROM limit")

    copy_spans = sorted(target_copy_spans)
    previous_end = 0
    for target_start, source_start, length in copy_spans:
        if length <= 0:
            raise ValueError("BPS target-copy spans must have positive lengths")
        if target_start < previous_end or target_start + length > len(target):
            raise ValueError("BPS target-copy spans overlap or exceed the target")
        if source_start < 0 or source_start + length > target_start:
            raise ValueError("BPS target-copy spans must reference earlier target data")
        if target[target_start:target_start + length] != target[source_start:source_start + length]:
            raise ValueError("BPS target-copy span does not match its earlier target data")
        previous_end = target_start + length

    patch = bytearray(PATCH_MAGIC)
    patch.extend(write_number(len(source)))
    patch.extend(write_number(len(target)))
    patch.extend(write_number(0))

    position = 0
    copy_index = 0
    target_relative = 0
    while position < len(target):
        if copy_index < len(copy_spans) and position == copy_spans[copy_index][0]:
            target_start, source_start, length = copy_spans[copy_index]
            patch.extend(encode_action(3, length))
            patch.extend(write_signed_number(source_start - target_relative))
            target_relative = source_start + length
            position = target_start + length
            copy_index += 1
        else:
            limit = (
                copy_spans[copy_index][0]
                if copy_index < len(copy_spans)
                else len(target)
            )
            if position > limit:
                raise ValueError("BPS target-copy span starts before the current target position")
            if position < len(source) and source[position] == target[position]:
                start = position
                position += 1
                while (
                    position < limit
                    and position < len(source)
                    and source[position] == target[position]
                ):
                    position += 1
                patch.extend(encode_action(0, position - start))
            else:
                start = position
                position += 1
                while position < limit and not (
                    position < len(source) and source[position] == target[position]
                ):
                    position += 1
                patch.extend(encode_action(1, position - start))
                patch.extend(target[start:position])

    patch.extend(struct.pack("<II", zlib.crc32(source), zlib.crc32(target)))
    patch.extend(struct.pack("<I", zlib.crc32(patch)))
    return bytes(patch)


def apply_bps_patch(source: bytes, patch: bytes) -> bytes:
    if len(patch) < len(PATCH_MAGIC):
        raise ValueError("BPS patch is too short")
    if patch[:4] != PATCH_MAGIC:
        raise ValueError("input patch does not have a BPS1 header")
    if len(patch) < len(PATCH_MAGIC) + FOOTER_SIZE:
        raise ValueError("BPS patch is too short")

    footer_start = len(patch) - FOOTER_SIZE
    source_crc, target_crc, patch_crc = struct.unpack_from("<III", patch, footer_start)
    if (zlib.crc32(patch[:-4]) & 0xFFFFFFFF) != patch_crc:
        raise ValueError("BPS patch checksum mismatch")
    if (zlib.crc32(source) & 0xFFFFFFFF) != source_crc:
        raise ValueError("source ROM checksum does not match the BPS patch")

    position = 4
    source_size, position = read_number(patch, position, footer_start)
    target_size, position = read_number(patch, position, footer_start)
    metadata_size, position = read_number(patch, position, footer_start)
    if source_size != len(source):
        raise ValueError(
            f"BPS source size mismatch: expected {source_size}, found {len(source)}"
        )
    if target_size > MAX_ROM_SIZE:
        raise ValueError(f"BPS target size exceeds the {MAX_ROM_SIZE}-byte ROM limit")
    if metadata_size > footer_start - position:
        raise ValueError("BPS metadata extends beyond the patch commands")
    position += metadata_size

    target = bytearray()
    source_relative = 0
    target_relative = 0
    while len(target) < target_size:
        action, position = read_number(patch, position, footer_start)
        action_type = action & 0x03
        length = (action >> 2) + 1
        if length > target_size - len(target):
            raise ValueError("BPS action exceeds the declared target size")

        if action_type == 0:
            end = len(target) + length
            if end > len(source):
                raise ValueError("BPS SourceRead action exceeds the source ROM")
            target.extend(source[len(target):end])
        elif action_type == 1:
            end = position + length
            if end > footer_start:
                raise ValueError("truncated BPS TargetRead action")
            target.extend(patch[position:end])
            position = end
        elif action_type == 2:
            delta, position = read_signed_number(patch, position, footer_start)
            source_relative += delta
            end = source_relative + length
            if source_relative < 0 or end > len(source):
                raise ValueError("BPS SourceCopy action exceeds the source ROM")
            target.extend(source[source_relative:end])
            source_relative = end
        else:
            delta, position = read_signed_number(patch, position, footer_start)
            target_relative += delta
            if target_relative < 0 or target_relative >= len(target):
                raise ValueError("BPS TargetCopy action refers to unavailable target data")
            for _ in range(length):
                if target_relative >= len(target):
                    raise ValueError("BPS TargetCopy action refers beyond produced data")
                target.append(target[target_relative])
                target_relative += 1

    if position != footer_start:
        raise ValueError("unexpected data remains after the BPS target is complete")
    if (zlib.crc32(target) & 0xFFFFFFFF) != target_crc:
        raise ValueError("patched ROM checksum does not match the BPS patch")
    return bytes(target)


def apply_bps_patch_file(
    source_path: Path,
    patch_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, int, str]:
    source = source_path.resolve(strict=True)
    patch = patch_path.resolve(strict=True)
    output = output_path.resolve()
    if not source.is_file() or not patch.is_file():
        raise ValueError("source ROM and BPS patch must be files")
    if output in {source, patch}:
        raise ValueError("output path must differ from the source ROM and BPS patch")
    if not output.parent.is_dir():
        raise ValueError(f"output directory does not exist: {output.parent}")
    if output.exists() and not overwrite:
        raise FileExistsError(
            f"output already exists: {output}; pass --overwrite to replace it"
        )

    result = apply_bps_patch(source.read_bytes(), patch.read_bytes())
    verification = verify_rom(result)
    if not verification.passed:
        raise ValueError("patched output failed Game Boy ROM size or checksum verification")

    write_output(output, result, overwrite)
    if output.read_bytes() != result:
        raise OSError(f"written output does not match patched ROM: {output}")
    return output, len(result), hashlib.sha256(result).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply a BPS patch to a local ROM, keeping the source unchanged."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
        help="source ROM (default: roms/oni5_original.gb)",
    )
    parser.add_argument(
        "--patch",
        type=Path,
        default=ROOT / "roms" / "oni5_opening_preview.bps",
        help="BPS patch (default: roms/oni5_opening_preview.bps)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "roms" / "oni5_opening_preview.gb",
        help="patched ROM output (default: roms/oni5_opening_preview.gb)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output ROM without touching the source ROM",
    )
    args = parser.parse_args()

    try:
        output, size, digest = apply_bps_patch_file(
            args.source,
            args.patch,
            args.output,
            args.overwrite,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {output} ({size} bytes)")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
