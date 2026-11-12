"""Build a guarded pilot ROM containing both confirmed dialogue translations."""
import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from .build_mbc1_expansion_probe import (
        BANK_SWITCH_HELPER_OFFSET,
        BANK_SWITCH_HELPER,
        BANK_SWITCH_MARKER,
        BANK_SWITCH_MARKER_OFFSET,
        ENTRY_OFFSET,
        EXPANDED_SIZE,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
    )
    from .build_noticeboard_glyph_probe import (
        ENTRY_AREA_SIZE,
        NOTICEBOARD_PAYLOAD_SIZE,
        NOTICEBOARD_SOURCE_BYTES,
        NOTICEBOARD_SOURCE_OFFSET,
        POSTLUDE_AREA_SIZE,
        POSTLUDE_CODE,
        RESTORE_HELPER_OFFSET,
        RESTORE_HELPER,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        TILE_PATTERN_SIZE,
        CachedGlyph,
        build_loader_helper,
        build_restore_bank_helper,
        parse_noticeboard_inputs,
    )
    from .build_rom import apply_patch_manifest, build_rom, write_output
    from .build_woman_glyph_probe import (
        EXPECTED_SOURCE_SHA256,
        TERMINATOR_CODE,
        WOMAN_PATCH_BYTES,
        WOMAN_PAYLOAD_SIZE,
        WOMAN_RESTORE_CURSOR,
        WOMAN_SOURCE_BYTES,
        WOMAN_SOURCE_OFFSET,
        parse_woman_inputs,
    )
    from .rom_checksums import update_checksums, verify_rom
else:
    from build_mbc1_expansion_probe import (
        BANK_SWITCH_HELPER_OFFSET,
        BANK_SWITCH_HELPER,
        BANK_SWITCH_MARKER,
        BANK_SWITCH_MARKER_OFFSET,
        ENTRY_OFFSET,
        EXPANDED_SIZE,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
    )
    from build_noticeboard_glyph_probe import (
        ENTRY_AREA_SIZE,
        NOTICEBOARD_PAYLOAD_SIZE,
        NOTICEBOARD_SOURCE_BYTES,
        NOTICEBOARD_SOURCE_OFFSET,
        POSTLUDE_AREA_SIZE,
        POSTLUDE_CODE,
        RESTORE_HELPER_OFFSET,
        RESTORE_HELPER,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        TILE_PATTERN_SIZE,
        CachedGlyph,
        build_loader_helper,
        build_restore_bank_helper,
        parse_noticeboard_inputs,
    )
    from build_rom import apply_patch_manifest, build_rom, write_output
    from build_woman_glyph_probe import (
        EXPECTED_SOURCE_SHA256,
        TERMINATOR_CODE,
        WOMAN_PATCH_BYTES,
        WOMAN_PAYLOAD_SIZE,
        WOMAN_RESTORE_CURSOR,
        WOMAN_SOURCE_BYTES,
        WOMAN_SOURCE_OFFSET,
        parse_woman_inputs,
    )
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
PILOT_MANIFEST_SCHEMA_VERSION = 1
ROM_BANK_WINDOW_CPU_START = 0x4000
ROM_BANK_WINDOW_FILE_END = SOURCE_SIZE + 0x4000
BANK_ALIGNMENT = 0x100
NOTICEBOARD_FIRST_CURSOR = 0x34
NOTICEBOARD_RESTORE_CURSOR = 0x3D
WOMAN_FIRST_CURSOR = 0x8F
NOTICEBOARD_FIRST_TILE = 0xA5
WOMAN_FIRST_TILE = 0x94
NOTICEBOARD_SOURCE_EXPECTED_END = NOTICEBOARD_SOURCE_OFFSET + NOTICEBOARD_PAYLOAD_SIZE
WOMAN_SOURCE_EXPECTED_END = WOMAN_SOURCE_OFFSET + WOMAN_PAYLOAD_SIZE


@dataclass(frozen=True)
class PilotBankLayout:
    load_dispatcher_offset: int
    load_dispatcher: bytes
    noticeboard_loader_offset: int
    noticeboard_loader: bytes
    noticeboard_pattern_offset: int
    woman_loader_offset: int
    woman_loader: bytes
    woman_pattern_offset: int
    restore_dispatcher_offset: int
    restore_dispatcher: bytes
    noticeboard_restore_offset: int
    noticeboard_restore: bytes
    woman_restore_offset: int
    woman_restore: bytes


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a positive power of two")
    return (value + alignment - 1) & ~(alignment - 1)


def bank_cpu_address(file_offset: int) -> int:
    if not SOURCE_SIZE <= file_offset < ROM_BANK_WINDOW_FILE_END:
        raise ValueError(f"file offset 0x{file_offset:X} is outside bank 0x10")
    return ROM_BANK_WINDOW_CPU_START + file_offset - SOURCE_SIZE


def build_context_entry_code() -> bytes:
    code = bytes.fromhex(
        "F5 FA AA FF FE 0C 20 4F "
        "FA AE FF FE 0E 20 48 "
        "FA AD FF FE 34 28 04 "
        "FE 8F 20 3D 06 CD C3 E0 00"
    )
    if len(code) > ENTRY_AREA_SIZE:
        raise ValueError("combined context entry code exceeds its reserved area")
    for branch_offset, target in ((6, 0x00F7), (13, 0x00F7), (20, 0x00BA), (24, 0x00F7)):
        displacement = code[branch_offset + 1]
        if displacement >= 0x80:
            displacement -= 0x100
        actual_target = ENTRY_OFFSET + branch_offset + 2 + displacement
        if actual_target != target:
            raise ValueError("combined context entry branch target is invalid")
    return code


def build_load_dispatcher(noticeboard_loader_cpu: int, woman_loader_cpu: int) -> bytes:
    return (
        bytes.fromhex("FA AD FF FE")
        + bytes((NOTICEBOARD_FIRST_CURSOR, 0xCA))
        + noticeboard_loader_cpu.to_bytes(2, "little")
        + bytes((0xFE, WOMAN_FIRST_CURSOR, 0xCA))
        + woman_loader_cpu.to_bytes(2, "little")
        + bytes((0xC9,))
    )


def build_restore_dispatcher(noticeboard_restore_cpu: int, woman_restore_cpu: int) -> bytes:
    return (
        bytes.fromhex("FA F2 C4 FE")
        + bytes((NOTICEBOARD_FIRST_TILE, 0xCA))
        + noticeboard_restore_cpu.to_bytes(2, "little")
        + bytes((0xFE, WOMAN_FIRST_TILE, 0xCA))
        + woman_restore_cpu.to_bytes(2, "little")
        + bytes((0xC9,))
    )


def build_pilot_bank_layout(
    noticeboard_glyphs: list[CachedGlyph],
    woman_glyphs: list[CachedGlyph],
) -> PilotBankLayout:
    if not noticeboard_glyphs or not woman_glyphs:
        raise ValueError("both pilot contexts must have at least one custom glyph")
    if noticeboard_glyphs[0].tile != NOTICEBOARD_FIRST_TILE:
        raise ValueError("noticeboard first tile changed; review its restore marker")
    if woman_glyphs[0].tile != WOMAN_FIRST_TILE:
        raise ValueError("woman first tile changed; review its restore marker")
    all_tiles = [glyph.tile for glyph in noticeboard_glyphs + woman_glyphs]
    if len(set(all_tiles)) != len(all_tiles):
        raise ValueError("pilot dialogue contexts must use distinct custom tile IDs")

    load_dispatcher_offset = BANK_SWITCH_HELPER_OFFSET
    load_dispatcher_size = 14
    noticeboard_loader_offset = load_dispatcher_offset + load_dispatcher_size
    noticeboard_loader_size = len(build_loader_helper(noticeboard_glyphs))
    noticeboard_pattern_offset = align_up(
        noticeboard_loader_offset + noticeboard_loader_size,
        BANK_ALIGNMENT,
    )
    noticeboard_loader = build_loader_helper(
        noticeboard_glyphs,
        bank_cpu_address(noticeboard_pattern_offset),
    )

    woman_loader_offset = align_up(
        noticeboard_pattern_offset + len(noticeboard_glyphs) * TILE_PATTERN_SIZE,
        BANK_ALIGNMENT,
    )
    woman_loader_size = len(build_loader_helper(woman_glyphs))
    woman_pattern_offset = align_up(
        woman_loader_offset + woman_loader_size,
        BANK_ALIGNMENT,
    )
    woman_loader = build_loader_helper(
        woman_glyphs,
        bank_cpu_address(woman_pattern_offset),
    )

    restore_dispatcher_offset = align_up(
        woman_pattern_offset + len(woman_glyphs) * TILE_PATTERN_SIZE,
        BANK_ALIGNMENT,
    )
    restore_dispatcher_size = 14
    noticeboard_restore_offset = restore_dispatcher_offset + restore_dispatcher_size
    noticeboard_restore_size = len(
        build_restore_bank_helper(
            noticeboard_glyphs,
            NOTICEBOARD_RESTORE_CURSOR,
            ROM_BANK_WINDOW_CPU_START,
        )
    )
    woman_restore_offset = noticeboard_restore_offset + noticeboard_restore_size

    noticeboard_restore = build_restore_bank_helper(
        noticeboard_glyphs,
        NOTICEBOARD_RESTORE_CURSOR,
        bank_cpu_address(noticeboard_restore_offset),
    )
    woman_restore = build_restore_bank_helper(
        woman_glyphs,
        WOMAN_RESTORE_CURSOR,
        bank_cpu_address(woman_restore_offset),
    )
    load_dispatcher = build_load_dispatcher(
        bank_cpu_address(noticeboard_loader_offset),
        bank_cpu_address(woman_loader_offset),
    )
    restore_dispatcher = build_restore_dispatcher(
        bank_cpu_address(noticeboard_restore_offset),
        bank_cpu_address(woman_restore_offset),
    )

    if len(load_dispatcher) != load_dispatcher_size:
        raise ValueError("combined loader dispatcher size changed")
    if len(restore_dispatcher) != restore_dispatcher_size:
        raise ValueError("combined restore dispatcher size changed")
    if len(noticeboard_loader) != noticeboard_loader_size:
        raise ValueError("noticeboard loader size changed during layout")
    if len(woman_loader) != woman_loader_size:
        raise ValueError("woman loader size changed during layout")
    if woman_restore_offset + len(woman_restore) > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("combined pilot helpers exceed the bank-10 ROM window")

    return PilotBankLayout(
        load_dispatcher_offset=load_dispatcher_offset,
        load_dispatcher=load_dispatcher,
        noticeboard_loader_offset=noticeboard_loader_offset,
        noticeboard_loader=noticeboard_loader,
        noticeboard_pattern_offset=noticeboard_pattern_offset,
        woman_loader_offset=woman_loader_offset,
        woman_loader=woman_loader,
        woman_pattern_offset=woman_pattern_offset,
        restore_dispatcher_offset=restore_dispatcher_offset,
        restore_dispatcher=restore_dispatcher,
        noticeboard_restore_offset=noticeboard_restore_offset,
        noticeboard_restore=noticeboard_restore,
        woman_restore_offset=woman_restore_offset,
        woman_restore=woman_restore,
    )


def build_two_text_pilot(
    source_rom: bytes,
    noticeboard_glyphs: list[CachedGlyph],
    noticeboard_payload: bytes,
    woman_glyphs: list[CachedGlyph],
    woman_payload: bytes,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    if hashlib.sha256(source_rom).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 does not match the verified original")
    if len(noticeboard_payload) != NOTICEBOARD_PAYLOAD_SIZE:
        raise ValueError("noticeboard payload must contain exactly 10 bytes")
    if noticeboard_payload[-1] != TERMINATOR_CODE:
        raise ValueError("noticeboard payload must end with 0x7F")
    if len(woman_payload) != WOMAN_PATCH_BYTES or woman_payload[-1] != TERMINATOR_CODE:
        raise ValueError("woman payload must contain 37 text bytes and one 0x7F")
    if source_rom[
        NOTICEBOARD_SOURCE_OFFSET:NOTICEBOARD_SOURCE_EXPECTED_END
    ] != NOTICEBOARD_SOURCE_BYTES:
        raise ValueError("noticeboard source bytes do not match the verified original")
    if source_rom[WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_EXPECTED_END] != WOMAN_SOURCE_BYTES:
        raise ValueError("woman source bytes do not match the verified original")
    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("tile restore hook bytes do not match the expected source")
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(RESTORE_HELPER)
    ] != bytes([0xFF]) * len(RESTORE_HELPER):
        raise ValueError("tile restore helper area is not entirely unused")

    layout = build_pilot_bank_layout(noticeboard_glyphs, woman_glyphs)
    entry_code = build_context_entry_code()
    postlude_code = POSTLUDE_CODE
    if len(postlude_code) > POSTLUDE_AREA_SIZE:
        raise ValueError("combined postlude exceeds its reserved area")

    expanded = bytearray(build_expansion_probe(source_rom))
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = bytes([0xFF]) * ENTRY_AREA_SIZE
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + len(entry_code)] = entry_code
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = bytes([0xFF]) * POSTLUDE_AREA_SIZE
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(postlude_code)] = postlude_code
    expanded[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)] = (
        RESTORE_HOOK_PATCH
    )

    restore_helper = (
        bytes.fromhex("F5 FA AA FF F5 3E 10 EA 00 20")
        + bytes((0xCD,))
        + bank_cpu_address(layout.restore_dispatcher_offset).to_bytes(2, "little")
        + bytes.fromhex("F1 EA 00 20 F1 21 03 00 C9")
    )
    expanded[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_helper)] = (
        restore_helper
    )

    bank_components = (
        (layout.load_dispatcher_offset, layout.load_dispatcher),
        (layout.noticeboard_loader_offset, layout.noticeboard_loader),
        (layout.noticeboard_pattern_offset, b"".join(glyph.pattern for glyph in noticeboard_glyphs)),
        (layout.woman_loader_offset, layout.woman_loader),
        (layout.woman_pattern_offset, b"".join(glyph.pattern for glyph in woman_glyphs)),
        (layout.restore_dispatcher_offset, layout.restore_dispatcher),
        (layout.noticeboard_restore_offset, layout.noticeboard_restore),
        (layout.woman_restore_offset, layout.woman_restore),
    )
    bank_baseline = bytearray([0xFF]) * (ROM_BANK_WINDOW_FILE_END - SOURCE_SIZE)
    bank_baseline[:len(BANK_SWITCH_HELPER)] = BANK_SWITCH_HELPER
    bank_baseline[BANK_SWITCH_MARKER_OFFSET - SOURCE_SIZE] = BANK_SWITCH_MARKER
    for offset, component in bank_components:
        relative_offset = offset - SOURCE_SIZE
        expected = bank_baseline[relative_offset:relative_offset + len(component)]
        if expanded[offset:offset + len(component)] != expected:
            raise ValueError(f"bank-10 area at 0x{offset:06X} is not unused")
        expanded[offset:offset + len(component)] = component

    expanded[
        NOTICEBOARD_SOURCE_OFFSET:NOTICEBOARD_SOURCE_EXPECTED_END
    ] = noticeboard_payload
    expanded[WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + len(woman_payload)] = woman_payload
    result = update_checksums(expanded)
    if len(result) != EXPANDED_SIZE or not verify_rom(result).passed:
        raise ValueError("two-text pilot failed ROM size or checksum verification")
    return result


def create_patch_manifest(source_rom: bytes, target_rom: bytes) -> dict[str, Any]:
    if len(target_rom) < len(source_rom):
        raise ValueError("target ROM must not be smaller than the source ROM")
    baseline = bytearray(source_rom)
    baseline.extend(bytes([0xFF]) * (len(target_rom) - len(source_rom)))
    patches = []
    offset = 0
    while offset < len(target_rom):
        if baseline[offset] == target_rom[offset]:
            offset += 1
            continue
        start = offset
        while offset < len(target_rom) and baseline[offset] != target_rom[offset]:
            offset += 1
        patches.append(
            {
                "id": f"pilot-range-{len(patches) + 1:03d}",
                "offset": f"0x{start:06X}",
                "expected_hex": bytes(baseline[start:offset]).hex(" ").upper(),
                "replacement_hex": target_rom[start:offset].hex(" ").upper(),
            }
        )
    return {
        "schema_version": PILOT_MANIFEST_SCHEMA_VERSION,
        "source_rom_sha256": hashlib.sha256(source_rom).hexdigest(),
        "target_size": f"0x{len(target_rom):X}",
        "extension_fill_byte": "0xFF",
        "scope": "confirmed noticeboard and woman dialogue contexts only; pilot, not production",
        "patches": patches,
    }


def build_pilot_files(
    source_path: Path,
    tile_cache_plan_path: Path,
    encoding_candidate_path: Path,
    manifest_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, Path, int, str, int]:
    source = source_path.resolve(strict=True)
    plan_file = tile_cache_plan_path.resolve(strict=True)
    encoding_file = encoding_candidate_path.resolve(strict=True)
    manifest_output = manifest_path.resolve()
    output = output_path.resolve()
    inputs = {source, plan_file, encoding_file}
    if manifest_output in inputs or output in inputs or manifest_output == output:
        raise ValueError("manifest and output paths must differ from each other and all inputs")
    if not source.is_file() or not plan_file.is_file() or not encoding_file.is_file():
        raise ValueError("source ROM, tile cache plan, and encoding candidate must be files")
    if not manifest_output.parent.is_dir() or not output.parent.is_dir():
        raise ValueError("manifest and ROM output directories must already exist")
    if not overwrite and (manifest_output.exists() or output.exists()):
        raise FileExistsError("manifest or ROM output already exists; pass --overwrite to replace")

    source_rom = source.read_bytes()
    if hashlib.sha256(source_rom).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 mismatch")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    encoding = json.loads(encoding_file.read_text(encoding="utf-8"))
    noticeboard_glyphs, noticeboard_payload = parse_noticeboard_inputs(plan, encoding)
    woman_glyphs, woman_payload = parse_woman_inputs(plan, encoding)
    pilot_rom = build_two_text_pilot(
        source_rom,
        noticeboard_glyphs,
        noticeboard_payload,
        woman_glyphs,
        woman_payload,
    )
    manifest = create_patch_manifest(source_rom, pilot_rom)
    rebuilt = update_checksums(apply_patch_manifest(source_rom, manifest))
    if rebuilt != pilot_rom:
        raise ValueError("patch manifest does not reproduce the generated pilot ROM")

    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_output(manifest_output, manifest_bytes, overwrite)
    built_path, size, digest, patch_count = build_rom(
        source,
        manifest_output,
        output,
        overwrite,
    )
    if built_path.read_bytes() != pilot_rom:
        raise OSError("manifest-built ROM differs from the directly generated pilot")
    return built_path, manifest_output, size, digest, patch_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a guarded two-dialogue pilot ROM and its reproducible patch manifest."
    )
    parser.add_argument(
        "source_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
        help="verified original ROM",
    )
    parser.add_argument(
        "tile_cache_plan",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_candidate.json",
        help="validated glyph patterns and original-tile backups",
    )
    parser.add_argument(
        "encoding_candidate",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
        help="confirmed noticeboard and woman encodings",
    )
    parser.add_argument(
        "patch_manifest",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_t14c7_two_text_pilot_patches.json",
        help="new guarded patch manifest output",
    )
    parser.add_argument(
        "output_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_t14c7_two_text_pilot.gb",
        help="new two-dialogue pilot ROM output",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    args = parser.parse_args()

    try:
        output, manifest, size, digest, patch_count = build_pilot_files(
            args.source_rom,
            args.tile_cache_plan,
            args.encoding_candidate,
            args.patch_manifest,
            args.output_rom,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote pilot ROM {output} ({size} bytes), {patch_count} guarded patch range(s)")
    print(f"Wrote patch manifest {manifest}")
    print(f"SHA-256: {digest}")
    print("Scope is limited to the confirmed noticeboard and woman dialogue contexts.")


if __name__ == "__main__":
    main()
