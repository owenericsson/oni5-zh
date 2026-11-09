"""Build a separate ROM image from a guarded byte-patch manifest."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

if __package__:
    from .rom_checksums import update_checksums, verify_rom
else:
    from rom_checksums import update_checksums, verify_rom


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def parse_offset(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.lower().startswith("0x"):
        raise ValueError(f"{field} must be a hexadecimal string such as 0x1234")
    try:
        offset = int(value[2:], 16)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid hexadecimal: {value!r}") from exc
    if offset < 0:
        raise ValueError(f"{field} must not be negative")
    return offset


def parse_hex_bytes(value: Any, field: str) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty hexadecimal string")
    try:
        data = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid hexadecimal: {value!r}") from exc
    if not data:
        raise ValueError(f"{field} must contain at least one byte")
    return data


def parse_sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return value.lower()


def apply_patch_manifest(rom: bytes, manifest: Any) -> bytes:
    root = require_object(manifest, "patch manifest")
    if root.get("schema_version") != 1:
        raise ValueError("patch manifest schema_version must be 1")

    expected_hash = parse_sha256(root.get("source_rom_sha256"), "source_rom_sha256")
    actual_hash = hashlib.sha256(rom).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(
            "source ROM SHA-256 mismatch: "
            f"expected {expected_hash}, found {actual_hash}"
        )

    patch_entries = root.get("patches")
    if not isinstance(patch_entries, list) or not patch_entries:
        raise ValueError("patches must be a non-empty list")

    patches: list[tuple[int, bytes, bytes, str]] = []
    patch_ids: set[str] = set()
    for index, value in enumerate(patch_entries):
        field = f"patches[{index}]"
        patch = require_object(value, field)
        patch_id = patch.get("id")
        if not isinstance(patch_id, str) or not patch_id:
            raise ValueError(f"{field}.id must be a non-empty string")
        if patch_id in patch_ids:
            raise ValueError(f"duplicate patch id: {patch_id!r}")
        patch_ids.add(patch_id)

        offset = parse_offset(patch.get("offset"), f"{field}.offset")
        expected = parse_hex_bytes(patch.get("expected_hex"), f"{field}.expected_hex")
        replacement = parse_hex_bytes(
            patch.get("replacement_hex"),
            f"{field}.replacement_hex",
        )
        if len(expected) != len(replacement):
            raise ValueError(
                f"{patch_id}: expected_hex and replacement_hex must have equal lengths"
            )
        if offset + len(expected) > len(rom):
            raise ValueError(f"{patch_id}: patch range exceeds source ROM size")
        if rom[offset:offset + len(expected)] != expected:
            raise ValueError(f"{patch_id}: source bytes do not match expected_hex")
        patches.append((offset, expected, replacement, patch_id))

    patches.sort(key=lambda patch: patch[0])
    for previous, current in zip(patches, patches[1:]):
        previous_end = previous[0] + len(previous[1])
        if current[0] < previous_end:
            raise ValueError(f"patches overlap: {previous[3]!r} and {current[3]!r}")

    output = bytearray(rom)
    for offset, expected, replacement, _ in patches:
        output[offset:offset + len(expected)] = replacement
    return bytes(output)


def write_output(path: Path, data: bytes, overwrite: bool) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        if overwrite:
            os.replace(temporary_path, path)
        else:
            try:
                os.link(temporary_path, path)
            except FileExistsError as exc:
                raise FileExistsError(
                    f"output already exists: {path}; pass --overwrite to replace it"
                ) from exc
            temporary_path.unlink()
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def build_rom(
    source_path: Path,
    manifest_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, int, str, int]:
    source = source_path.resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"source ROM is not a file: {source}")
    output = output_path.resolve()
    if output == source:
        raise ValueError("output ROM path must differ from the source ROM path")
    if not output.parent.is_dir():
        raise ValueError(f"output directory does not exist: {output.parent}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output}; pass --overwrite to replace it")

    source_rom = source.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_rom = update_checksums(apply_patch_manifest(source_rom, manifest))
    verification = verify_rom(output_rom)
    if not verification.passed:
        raise ValueError("generated ROM failed size or checksum verification")
    write_output(output, output_rom, overwrite)

    written = output.read_bytes()
    if written != output_rom:
        raise OSError(f"written output does not match generated ROM: {output}")
    return output, len(output_rom), hashlib.sha256(output_rom).hexdigest(), len(manifest["patches"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a separate ROM from an expected-bytes-checked patch manifest."
    )
    parser.add_argument("source_rom", type=Path, help="unchanged base ROM")
    parser.add_argument("patch_manifest", type=Path, help="JSON byte-patch manifest")
    parser.add_argument("output_rom", type=Path, help="new ROM output path")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output ROM (never overwrites the source ROM)",
    )
    args = parser.parse_args()

    try:
        output, size, digest, patch_count = build_rom(
            args.source_rom,
            args.patch_manifest,
            args.output_rom,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {output} ({size} bytes), {patch_count} patch(es)")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
