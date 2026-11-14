"""Build a guarded three-context pilot with per-context glyph cache mappings."""
import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from .build_context_glyph_probe import (
        CONTEXT_FIRST_CHARACTER_CURSOR,
        CONTEXT_PATCH_BYTES,
        CONTEXT_RESTORE_CURSOR,
        CONTEXT_SOURCE_BYTES,
        CONTEXT_SOURCE_OFFSET,
        CONTEXT_SOURCE_SIZE,
        parse_context_inputs,
    )
    from .build_mbc1_expansion_probe import (
        BANK_SWITCH_HELPER,
        BANK_SWITCH_HELPER_OFFSET,
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
        RESTORE_HELPER,
        RESTORE_HELPER_OFFSET,
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
    from .build_two_text_pilot import (
        BANK_ALIGNMENT,
        EXPECTED_SOURCE_SHA256,
        ROM_BANK_WINDOW_CPU_START,
        ROM_BANK_WINDOW_FILE_END,
        WOMAN_FIRST_CURSOR,
        WOMAN_SOURCE_BYTES,
        WOMAN_SOURCE_OFFSET,
        WOMAN_PAYLOAD_SIZE,
        WOMAN_PATCH_BYTES,
        WOMAN_RESTORE_CURSOR,
        bank_cpu_address,
        create_patch_manifest,
    )
    from .build_woman_glyph_probe import TERMINATOR_CODE, parse_woman_inputs
    from .rom_checksums import update_checksums, verify_rom
else:
    from build_context_glyph_probe import (
        CONTEXT_FIRST_CHARACTER_CURSOR,
        CONTEXT_PATCH_BYTES,
        CONTEXT_RESTORE_CURSOR,
        CONTEXT_SOURCE_BYTES,
        CONTEXT_SOURCE_OFFSET,
        CONTEXT_SOURCE_SIZE,
        parse_context_inputs,
    )
    from build_mbc1_expansion_probe import (
        BANK_SWITCH_HELPER,
        BANK_SWITCH_HELPER_OFFSET,
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
        RESTORE_HELPER,
        RESTORE_HELPER_OFFSET,
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
    from build_two_text_pilot import (
        BANK_ALIGNMENT,
        EXPECTED_SOURCE_SHA256,
        ROM_BANK_WINDOW_CPU_START,
        ROM_BANK_WINDOW_FILE_END,
        WOMAN_FIRST_CURSOR,
        WOMAN_SOURCE_BYTES,
        WOMAN_SOURCE_OFFSET,
        WOMAN_PAYLOAD_SIZE,
        WOMAN_PATCH_BYTES,
        WOMAN_RESTORE_CURSOR,
        bank_cpu_address,
        create_patch_manifest,
    )
    from build_woman_glyph_probe import TERMINATOR_CODE, parse_woman_inputs
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
NOTICEBOARD_FIRST_CURSOR = 0x34
NOTICEBOARD_RESTORE_CURSOR = 0x3D
NOTICEBOARD_FIRST_TILE = 0xA5
WOMAN_FIRST_TILE = 0x94
CONTEXT_FIRST_TILE = 0x85
ENTRY_CONTEXT_HELPER_OFFSET = 0x77
ENTRY_CONTEXT_HELPER = bytes.fromhex("FE 8F 28 02 FE E9 C9")


@dataclass(frozen=True)
class PilotContext:
    record_id: str
    first_cursor: int
    restore_cursor: int
    source_offset: int
    original_source: bytes
    glyphs: list[CachedGlyph]
    payload: bytes


@dataclass(frozen=True)
class ContextBankLayout:
    load_dispatcher_offset: int
    load_dispatcher: bytes
    loader_offsets: tuple[int, ...]
    loaders: tuple[bytes, ...]
    pattern_offsets: tuple[int, ...]
    patterns: tuple[bytes, ...]
    restore_dispatcher_offset: int
    restore_dispatcher: bytes
    restore_offsets: tuple[int, ...]
    restore_helpers: tuple[bytes, ...]


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a positive power of two")
    return (value + alignment - 1) & ~(alignment - 1)


def build_three_context_entry_code() -> bytes:
    code = bytes.fromhex(
        "F5 FA AA FF FE 0C 20 4F "
        "FA AE FF FE 0E 20 48 "
        "FA AD FF FE 34 28 05 CD 77 00 20 3C 06 CD C3 E0 00"
    )
    if len(code) != ENTRY_AREA_SIZE:
        raise ValueError("three-context entry code must fill its reserved area")
    for branch_offset, target in (
        (6, 0x00F7),
        (13, 0x00F7),
        (20, 0x00BB),
        (25, 0x00F7),
    ):
        displacement = code[branch_offset + 1]
        if displacement >= 0x80:
            displacement -= 0x100
        actual_target = ENTRY_OFFSET + branch_offset + 2 + displacement
        if actual_target != target:
            raise ValueError("three-context entry branch target is invalid")
    if code[22:25] != bytes.fromhex("CD 77 00"):
        raise ValueError("three-context cursor helper call changed")
    return code


def build_load_dispatcher(
    contexts: tuple[PilotContext, ...],
    loader_offsets: tuple[int, ...],
) -> bytes:
    if len(contexts) != len(loader_offsets):
        raise ValueError("each text context must have one loader")
    code = bytearray.fromhex("FA AD FF")
    for context, loader_offset in zip(contexts, loader_offsets):
        code.extend(bytes((0xFE, context.first_cursor, 0xCA)))
        code.extend(bank_cpu_address(loader_offset).to_bytes(2, "little"))
    code.append(0xC9)
    return bytes(code)


def build_restore_dispatcher(
    contexts: tuple[PilotContext, ...],
    restore_offsets: tuple[int, ...],
) -> bytes:
    if len(contexts) != len(restore_offsets):
        raise ValueError("each text context must have one restore helper")
    code = bytearray.fromhex("FA F2 C4")
    for context, restore_offset in zip(contexts, restore_offsets):
        if not context.glyphs:
            raise ValueError(f"{context.record_id} has no custom glyph marker")
        code.extend(bytes((0xFE, context.glyphs[0].tile, 0xCA)))
        code.extend(bank_cpu_address(restore_offset).to_bytes(2, "little"))
    code.append(0xC9)
    return bytes(code)


def build_context_bank_layout(
    contexts: tuple[PilotContext, ...],
) -> ContextBankLayout:
    if len(contexts) != 3:
        raise ValueError("three-text pilot requires exactly three contexts")
    cursors = [context.first_cursor for context in contexts]
    markers = [context.glyphs[0].tile for context in contexts if context.glyphs]
    if len(set(cursors)) != len(contexts):
        raise ValueError("text contexts must have distinct first-character cursors")
    if len(markers) != len(contexts) or len(set(markers)) != len(contexts):
        raise ValueError("text contexts must have distinct restore marker tiles")
    for context in contexts:
        if not context.glyphs or any(len(glyph.pattern) != TILE_PATTERN_SIZE for glyph in context.glyphs):
            raise ValueError(f"{context.record_id} has invalid cached glyph patterns")
        if len({glyph.tile for glyph in context.glyphs}) != len(context.glyphs):
            raise ValueError(f"{context.record_id} has duplicate custom tile assignments")

    load_dispatcher_offset = BANK_SWITCH_HELPER_OFFSET
    load_dispatcher_size = len(build_load_dispatcher(
        contexts,
        (load_dispatcher_offset,) * len(contexts),
    ))
    cursor = load_dispatcher_offset + load_dispatcher_size
    loader_offsets = []
    loaders = []
    pattern_offsets = []
    patterns = []
    for context in contexts:
        loader_offset = cursor
        preliminary_loader = build_loader_helper(context.glyphs)
        pattern_offset = align_up(
            loader_offset + len(preliminary_loader),
            BANK_ALIGNMENT,
        )
        loader = build_loader_helper(
            context.glyphs,
            bank_cpu_address(pattern_offset),
        )
        pattern_data = b"".join(glyph.pattern for glyph in context.glyphs)
        if loader_offset + len(loader) > pattern_offset:
            raise ValueError(f"{context.record_id} loader overlaps glyph patterns")
        loader_offsets.append(loader_offset)
        loaders.append(loader)
        pattern_offsets.append(pattern_offset)
        patterns.append(pattern_data)
        cursor = pattern_offset + len(pattern_data)

    restore_dispatcher_offset = align_up(cursor, BANK_ALIGNMENT)
    restore_lengths = [
        len(
            build_restore_bank_helper(
                context.glyphs,
                context.restore_cursor,
                ROM_BANK_WINDOW_CPU_START,
            )
        )
        for context in contexts
    ]
    restore_offsets = []
    restore_helpers = []
    cursor = restore_dispatcher_offset + len(
        build_restore_dispatcher(
            contexts,
            (restore_dispatcher_offset,) * len(contexts),
        )
    )
    for context, expected_length in zip(contexts, restore_lengths):
        restore_offset = cursor
        helper = build_restore_bank_helper(
            context.glyphs,
            context.restore_cursor,
            bank_cpu_address(restore_offset),
        )
        if len(helper) != expected_length:
            raise ValueError(f"{context.record_id} restore helper size changed during layout")
        restore_offsets.append(restore_offset)
        restore_helpers.append(helper)
        cursor += len(helper)

    load_dispatcher = build_load_dispatcher(contexts, tuple(loader_offsets))
    restore_dispatcher = build_restore_dispatcher(contexts, tuple(restore_offsets))
    if len(load_dispatcher) != load_dispatcher_size:
        raise ValueError("three-context load dispatcher size changed")
    if restore_dispatcher_offset + len(restore_dispatcher) > restore_offsets[0]:
        raise ValueError("three-context restore dispatcher overlaps its helpers")
    if cursor > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("three-context helpers exceed the bank-10 ROM window")
    return ContextBankLayout(
        load_dispatcher_offset=load_dispatcher_offset,
        load_dispatcher=load_dispatcher,
        loader_offsets=tuple(loader_offsets),
        loaders=tuple(loaders),
        pattern_offsets=tuple(pattern_offsets),
        patterns=tuple(patterns),
        restore_dispatcher_offset=restore_dispatcher_offset,
        restore_dispatcher=restore_dispatcher,
        restore_offsets=tuple(restore_offsets),
        restore_helpers=tuple(restore_helpers),
    )


def build_three_text_pilot(
    source_rom: bytes,
    noticeboard_glyphs: list[CachedGlyph],
    noticeboard_payload: bytes,
    woman_glyphs: list[CachedGlyph],
    woman_payload: bytes,
    context_glyphs: list[CachedGlyph],
    context_payload: bytes,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    if hashlib.sha256(source_rom).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 does not match the verified original")
    if len(noticeboard_payload) != NOTICEBOARD_PAYLOAD_SIZE or noticeboard_payload[-1] != TERMINATOR_CODE:
        raise ValueError("noticeboard payload must contain 10 bytes and end with 0x7F")
    if len(woman_payload) != WOMAN_PATCH_BYTES or woman_payload[-1] != TERMINATOR_CODE:
        raise ValueError("woman payload must contain 38 bytes and end with 0x7F")
    if len(context_payload) != CONTEXT_PATCH_BYTES or context_payload[-1] != TERMINATOR_CODE:
        raise ValueError(
            f"context payload must contain {CONTEXT_PATCH_BYTES} bytes and end with 0x7F"
        )
    if source_rom[
        NOTICEBOARD_SOURCE_OFFSET:
        NOTICEBOARD_SOURCE_OFFSET + len(NOTICEBOARD_SOURCE_BYTES)
    ] != NOTICEBOARD_SOURCE_BYTES:
        raise ValueError("noticeboard source bytes do not match the verified original")
    if source_rom[
        WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + WOMAN_PAYLOAD_SIZE
    ] != WOMAN_SOURCE_BYTES:
        raise ValueError("woman source bytes do not match the verified original")
    if source_rom[
        CONTEXT_SOURCE_OFFSET:CONTEXT_SOURCE_OFFSET + CONTEXT_SOURCE_SIZE
    ] != CONTEXT_SOURCE_BYTES:
        raise ValueError("context source bytes do not match the verified original")
    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("tile restore hook bytes do not match the expected source")
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(RESTORE_HELPER)
    ] != bytes([0xFF]) * len(RESTORE_HELPER):
        raise ValueError("tile restore helper area is not entirely unused")
    if source_rom[
        ENTRY_CONTEXT_HELPER_OFFSET:
        ENTRY_CONTEXT_HELPER_OFFSET + len(ENTRY_CONTEXT_HELPER)
    ] != bytes([0xFF]) * len(ENTRY_CONTEXT_HELPER):
        raise ValueError("three-context cursor helper area is not entirely unused")

    contexts = (
        PilotContext(
            "oni5-bank0c-pointer-030e33",
            NOTICEBOARD_FIRST_CURSOR,
            NOTICEBOARD_RESTORE_CURSOR,
            NOTICEBOARD_SOURCE_OFFSET,
            NOTICEBOARD_SOURCE_BYTES,
            noticeboard_glyphs,
            noticeboard_payload,
        ),
        PilotContext(
            "oni5-bank0c-pointer-030e8e",
            WOMAN_FIRST_CURSOR,
            WOMAN_RESTORE_CURSOR,
            WOMAN_SOURCE_OFFSET,
            WOMAN_SOURCE_BYTES,
            woman_glyphs,
            woman_payload,
        ),
        PilotContext(
            "oni5-bank0c-pointer-030ee8",
            CONTEXT_FIRST_CHARACTER_CURSOR,
            CONTEXT_RESTORE_CURSOR,
            CONTEXT_SOURCE_OFFSET,
            CONTEXT_SOURCE_BYTES,
            context_glyphs,
            context_payload,
        ),
    )
    layout = build_context_bank_layout(contexts)
    expanded = bytearray(build_expansion_probe(source_rom))
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = bytes([0xFF]) * ENTRY_AREA_SIZE
    entry_code = build_three_context_entry_code()
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + len(entry_code)] = entry_code
    expanded[
        ENTRY_CONTEXT_HELPER_OFFSET:
        ENTRY_CONTEXT_HELPER_OFFSET + len(ENTRY_CONTEXT_HELPER)
    ] = ENTRY_CONTEXT_HELPER
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = bytes(
        [0xFF]
    ) * POSTLUDE_AREA_SIZE
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)] = POSTLUDE_CODE
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

    bank_components = [
        (layout.load_dispatcher_offset, layout.load_dispatcher),
    ]
    bank_components.extend(zip(layout.loader_offsets, layout.loaders))
    bank_components.extend(zip(layout.pattern_offsets, layout.patterns))
    bank_components.append((layout.restore_dispatcher_offset, layout.restore_dispatcher))
    bank_components.extend(zip(layout.restore_offsets, layout.restore_helpers))
    bank_baseline = bytearray([0xFF]) * (ROM_BANK_WINDOW_FILE_END - SOURCE_SIZE)
    bank_baseline[:len(BANK_SWITCH_HELPER)] = BANK_SWITCH_HELPER
    bank_baseline[BANK_SWITCH_MARKER_OFFSET - SOURCE_SIZE] = BANK_SWITCH_MARKER
    for offset, component in bank_components:
        relative_offset = offset - SOURCE_SIZE
        expected = bank_baseline[relative_offset:relative_offset + len(component)]
        if expanded[offset:offset + len(component)] != expected:
            raise ValueError(f"bank-10 area at 0x{offset:06X} is not unused")
        expanded[offset:offset + len(component)] = component

    for context in contexts:
        expanded[
            context.source_offset:context.source_offset + len(context.payload)
        ] = context.payload

    result = update_checksums(expanded)
    if len(result) != EXPANDED_SIZE or not verify_rom(result).passed:
        raise ValueError("three-text pilot failed ROM size or checksum verification")
    return result


def build_three_text_files(
    source_path: Path,
    tile_cache_plan_path: Path,
    encoding_candidate_path: Path,
    context_cache_plan_path: Path,
    context_encoding_path: Path,
    manifest_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, Path, int, str, int]:
    source = source_path.resolve(strict=True)
    plan_file = tile_cache_plan_path.resolve(strict=True)
    encoding_file = encoding_candidate_path.resolve(strict=True)
    context_plan_file = context_cache_plan_path.resolve(strict=True)
    context_encoding_file = context_encoding_path.resolve(strict=True)
    manifest_output = manifest_path.resolve()
    output = output_path.resolve()
    inputs = {source, plan_file, encoding_file, context_plan_file, context_encoding_file}
    if manifest_output in inputs or output in inputs or manifest_output == output:
        raise ValueError("manifest and output paths must differ from each other and all inputs")
    if any(not path.is_file() for path in inputs):
        raise ValueError("source ROM and all candidate inputs must be files")
    if not manifest_output.parent.is_dir() or not output.parent.is_dir():
        raise ValueError("manifest and ROM output directories must already exist")
    if not overwrite and (manifest_output.exists() or output.exists()):
        raise FileExistsError("manifest or ROM output already exists; pass --overwrite to replace")

    source_rom = source.read_bytes()
    if hashlib.sha256(source_rom).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 mismatch")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    encoding = json.loads(encoding_file.read_text(encoding="utf-8"))
    context_plan = json.loads(context_plan_file.read_text(encoding="utf-8"))
    context_encoding = json.loads(context_encoding_file.read_text(encoding="utf-8"))
    noticeboard_glyphs, noticeboard_payload = parse_noticeboard_inputs(plan, encoding)
    woman_glyphs, woman_payload = parse_woman_inputs(plan, encoding)
    context_glyphs, context_payload = parse_context_inputs(
        context_plan,
        context_encoding,
    )
    pilot_rom = build_three_text_pilot(
        source_rom,
        noticeboard_glyphs,
        noticeboard_payload,
        woman_glyphs,
        woman_payload,
        context_glyphs,
        context_payload,
    )
    manifest = create_patch_manifest(source_rom, pilot_rom)
    manifest["scope"] = (
        "confirmed noticeboard, woman, and context dialogue mappings only; "
        "pilot, not production"
    )
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
        description="Build a guarded pilot ROM for three context-scoped dialogue translations."
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
        help="noticeboard and woman glyph patterns and original-tile backups",
    )
    parser.add_argument(
        "encoding_candidate",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
        help="noticeboard and woman encodings",
    )
    parser.add_argument(
        "context_cache_plan",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json",
        help="context-specific glyph patterns and original-tile backups",
    )
    parser.add_argument(
        "context_encoding",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json",
        help="context-specific encoding",
    )
    parser.add_argument(
        "patch_manifest",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_t19_three_text_pilot_patches.json",
        help="new guarded patch manifest output",
    )
    parser.add_argument(
        "output_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_t19_three_text_pilot.gb",
        help="new three-context pilot ROM output",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    args = parser.parse_args()

    try:
        output, manifest, size, digest, patch_count = build_three_text_files(
            args.source_rom,
            args.tile_cache_plan,
            args.encoding_candidate,
            args.context_cache_plan,
            args.context_encoding,
            args.patch_manifest,
            args.output_rom,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote pilot ROM {output} ({size} bytes), {patch_count} guarded patch range(s)")
    print(f"Wrote patch manifest {manifest}")
    print(f"SHA-256: {digest}")
    print("Scope is limited to the three confirmed context-mapped dialogue texts.")


if __name__ == "__main__":
    main()
