"""Extend the verified opening ROM with the translated dialogue contexts."""
import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

if __package__:
    from .build_mbc1_expansion_probe import (
        BANK_RESTORE_STUB_OFFSET,
        ENTRY_OFFSET,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
    )
    from .build_menu_pilot import (
        MBC1_MIRROR_OFFSET,
        MENU_EXPANDED_SIZE,
        MENU_EXTENSION_ALIAS_OFFSET,
        MENU_ROM_SIZE_CODE,
        ROM_BANK_SIZE,
    )
    from .build_noticeboard_glyph_probe import (
        ENTRY_AREA_SIZE,
        RESTORE_HELPER_OFFSET,
        TILE_PATTERN_SIZE,
    )
    from .build_opening_text_preview_patch import (
        OPENING_GATE_MISS_CODE,
        RESTORE_CURSOR_VALUE,
        ROM_BANK_WINDOW_CPU_START,
        ROM_BANK_WINDOW_FILE_END,
        SOURCE_END as OPENING_SOURCE_END,
        SOURCE_OFFSET as OPENING_SOURCE_OFFSET,
        build_loader as build_opening_loader,
        build_opening_restore_helper,
        build_rom_restore_bank_helper,
    )
    from .build_rom import write_output
    from .build_text_comparison_pilot import (
        OPENING_BANK,
        OPENING_LOAD_CURSOR,
        OPENING_POINTER_HIGH,
        PRACTICE_RUNTIME_SIGNATURE_V2_3,
        align_up,
        bank_cpu_address,
        build_context_bank_layout,
        build_contexts,
        build_entry_code,
        build_restore_dispatcher,
    )
    from .rom_checksums import update_checksums, verify_rom
else:
    from build_mbc1_expansion_probe import (
        BANK_RESTORE_STUB_OFFSET,
        ENTRY_OFFSET,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
    )
    from build_menu_pilot import (
        MBC1_MIRROR_OFFSET,
        MENU_EXPANDED_SIZE,
        MENU_EXTENSION_ALIAS_OFFSET,
        MENU_ROM_SIZE_CODE,
        ROM_BANK_SIZE,
    )
    from build_noticeboard_glyph_probe import (
        ENTRY_AREA_SIZE,
        RESTORE_HELPER_OFFSET,
        TILE_PATTERN_SIZE,
    )
    from build_opening_text_preview_patch import (
        OPENING_GATE_MISS_CODE,
        RESTORE_CURSOR_VALUE,
        ROM_BANK_WINDOW_CPU_START,
        ROM_BANK_WINDOW_FILE_END,
        SOURCE_END as OPENING_SOURCE_END,
        SOURCE_OFFSET as OPENING_SOURCE_OFFSET,
        build_loader as build_opening_loader,
        build_opening_restore_helper,
        build_rom_restore_bank_helper,
    )
    from build_rom import write_output
    from build_text_comparison_pilot import (
        OPENING_BANK,
        OPENING_LOAD_CURSOR,
        OPENING_POINTER_HIGH,
        PRACTICE_RUNTIME_SIGNATURE_V2_3,
        align_up,
        bank_cpu_address,
        build_context_bank_layout,
        build_contexts,
        build_entry_code,
        build_restore_dispatcher,
    )
    from rom_checksums import update_checksums, verify_rom


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
EXPECTED_OPENING_BASE_SHA256 = (
    "5682522e20fade44c457725a66430bae13e3d6695dcc18e04d058e4ce2e910ab"
)


@dataclass(frozen=True)
class OpeningBankLayout:
    loader: bytes
    loader_offset: int
    pattern_offset: int
    original_patterns_offset: int
    restore_offset: int
    restore_helper: bytes
    used_end: int


def _opening_bank_layout(opening_context: Any, opening_rom: bytes) -> OpeningBankLayout:
    glyphs = list(opening_context.glyphs)
    if not glyphs:
        raise ValueError("opening context has no glyphs")

    loader_offset = SOURCE_SIZE
    preliminary = build_opening_loader(glyphs, 0x4100)
    pattern_offset = align_up(loader_offset + len(preliminary), 0x100)
    loader = build_opening_loader(glyphs, bank_cpu_address(pattern_offset))
    pattern_end = pattern_offset + len(glyphs) * TILE_PATTERN_SIZE
    original_patterns_offset = align_up(pattern_end, 0x100)
    original_patterns = b"".join(opening_context.original_patterns)
    if len(original_patterns) != len(glyphs) * TILE_PATTERN_SIZE:
        raise ValueError("opening base has an incomplete original-pattern backup")
    original_patterns_end = original_patterns_offset + len(original_patterns)
    restore_offset = align_up(original_patterns_end, 0x10)
    restore_cpu_address = bank_cpu_address(restore_offset)
    restore_helper = build_rom_restore_bank_helper(
        glyphs,
        bank_cpu_address(original_patterns_offset),
        RESTORE_CURSOR_VALUE,
        restore_cpu_address,
    )

    if opening_rom[loader_offset:loader_offset + len(loader)] != loader:
        raise ValueError("opening base loader differs from the verified source build")
    if opening_rom[pattern_offset:pattern_end] != b"".join(
        glyph.pattern for glyph in glyphs
    ):
        raise ValueError("opening base glyph patterns differ from the verified assets")
    if opening_rom[
        original_patterns_offset:original_patterns_end
    ] != original_patterns:
        raise ValueError("opening base original-pattern backup differs from the source")
    if opening_rom[restore_offset:restore_offset + len(restore_helper)] != restore_helper:
        raise ValueError("opening base restore helper differs from the verified source build")
    fixed_restore_stub = build_opening_restore_helper(restore_cpu_address)
    if opening_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(fixed_restore_stub)
    ] != fixed_restore_stub:
        raise ValueError("opening base fixed-bank restore stub has an unexpected target")
    if restore_offset + len(restore_helper) > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("opening base helpers exceed the bank-10 window")

    return OpeningBankLayout(
        loader=loader,
        loader_offset=loader_offset,
        pattern_offset=pattern_offset,
        original_patterns_offset=original_patterns_offset,
        restore_offset=restore_offset,
        restore_helper=restore_helper,
        used_end=restore_offset + len(restore_helper),
    )


def _dispatcher_end(layout: Any) -> int:
    spans = [
        (layout.load_dispatcher_offset, len(layout.load_dispatcher)),
        (layout.restore_dispatcher_offset, len(layout.restore_dispatcher)),
    ]
    spans.extend(zip(layout.loader_offsets, (len(code) for code in layout.loaders)))
    spans.extend(zip(layout.pattern_offsets, (len(data) for data in layout.patterns)))
    spans.extend(
        (offset, len(data))
        for offset, data in zip(layout.original_pattern_offsets, layout.original_patterns)
        if offset is not None
    )
    spans.extend(
        zip(layout.restore_offsets, (len(code) for code in layout.restore_helpers))
    )
    return max(offset + size for offset, size in spans)


def _write_component(target: bytearray, offset: int, data: bytes, base: bytes) -> None:
    if base[offset:offset + len(data)] != bytes([0xFF]) * len(data):
        raise ValueError(f"dialogue extension overlaps occupied bank-10 bytes at 0x{offset:X}")
    target[offset:offset + len(data)] = data


def _build_unified_load_dispatcher(
    opening_loader_offset: int,
    dialogue_dispatcher_offset: int,
) -> bytes:
    code = bytearray()
    branch_sites: list[tuple[int, str]] = []

    code.extend(bytes.fromhex("FA F2 C4 B7 20 00"))
    branch_sites.append((len(code) - 1, "miss"))

    for address, value in (
        (0xFFAA, OPENING_BANK),
        (0xFFAE, OPENING_POINTER_HIGH),
        (0xFFAD, OPENING_LOAD_CURSOR),
    ):
        code.extend((0xFA, address & 0xFF, address >> 8, 0xFE, value, 0x20, 0))
        branch_sites.append((len(code) - 1, "dialogue"))

    code.append(0xCD)
    code.extend(bank_cpu_address(opening_loader_offset).to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E BB EA F0 C4 3E 01 C9"))

    labels = {"dialogue": len(code)}
    code.append(0xCD)
    code.extend(bank_cpu_address(dialogue_dispatcher_offset).to_bytes(2, "little"))
    code.append(0xC9)
    labels["miss"] = len(code)
    code.extend(bytes.fromhex("AF C9"))

    for operand_offset, label in branch_sites:
        displacement = labels[label] - (operand_offset + 1)
        if not -128 <= displacement <= 127:
            raise ValueError("opening/dialogue dispatcher branch is out of range")
        code[operand_offset] = displacement & 0xFF
    return bytes(code)


GatewayLayout = Literal["v2.1", "v2.2", "v2.3"]


def _build_bank10_gateway(
    dispatcher_cpu_address: int,
    gateway_layout: GatewayLayout = "v2.1",
) -> bytes:
    if not 0x4000 <= dispatcher_cpu_address < 0x8000:
        raise ValueError("load dispatcher must be inside the bank-10 CPU window")
    if gateway_layout in ("v2.2", "v2.3"):
        return bytes(
            (0xCD, dispatcher_cpu_address & 0xFF, dispatcher_cpu_address >> 8, 0xC9)
        )
    return (
        bytes((0xCD, dispatcher_cpu_address & 0xFF, dispatcher_cpu_address >> 8))
        + bytes.fromhex("F5 FA AA FF EA 00 20 FB F1 C3")
        + (POSTLUDE_OFFSET + 8).to_bytes(2, "little")
    )


def _build_fixed_gateway_stub(gateway_layout: GatewayLayout = "v2.1") -> bytes:
    if gateway_layout in ("v2.2", "v2.3"):
        return bytes.fromhex("F3 3E 10 EA 00 20 CD 00 40")
    return bytes.fromhex("F3 3E 10 EA 00 20 C3 00 40")


def _build_fixed_gateway_completion(
    return_handler_address: int | None = None,
) -> bytes:
    if return_handler_address is not None:
        if not 0 <= return_handler_address <= 0xFFFF:
            raise ValueError("gateway return handler must fit in the 16-bit address space")
        return (
            bytes.fromhex("F5 FA AA FF EA 00 20 FB F1 C3")
            + return_handler_address.to_bytes(2, "little")
        )
    return bytes.fromhex("B7 20 03 C3 F7 00 F1 FA F0 C4 C3 0C 18")


def _build_v2_2_entry_code(
    entry_banks: tuple[int, ...],
    entry_pointer_highs: tuple[int, ...] | None = None,
) -> tuple[bytes, int]:
    if not entry_banks or len(set(entry_banks)) != len(entry_banks):
        raise ValueError("entry banks must be a non-empty sequence of unique banks")
    if entry_pointer_highs is not None and (
        not entry_pointer_highs
        or len(set(entry_pointer_highs)) != len(entry_pointer_highs)
        or any(not 0 <= pointer_high <= 0xFF for pointer_high in entry_pointer_highs)
    ):
        raise ValueError("entry pointer highs must be a non-empty sequence of unique bytes")

    code = bytearray.fromhex(
        "F5 FA AE FF" if entry_pointer_highs is not None else "F5 FA AA FF"
    )
    eligible_branches: list[int] = []
    for value in entry_pointer_highs if entry_pointer_highs is not None else entry_banks:
        code.extend((0xFE, value, 0x28, 0))
        eligible_branches.append(len(code) - 1)

    fallback_branch = len(code) + 1
    code.extend((0x18, 0))
    eligible_offset = len(code)
    code.extend(bytes.fromhex("FA F2 C4 B7 20 00"))
    cached_branch = len(code) - 1
    postlude_branch = len(code) + 1
    code.extend((0x18, 0))

    return_handler_offset = ENTRY_OFFSET + len(code)
    code.extend(bytes.fromhex("B7 28 00 F1 FA F0 C4 C3 0C 18"))

    fallback_offset = BANK_RESTORE_STUB_OFFSET - ENTRY_OFFSET
    postlude_offset = POSTLUDE_OFFSET - ENTRY_OFFSET
    branch_targets = [
        *((operand, eligible_offset) for operand in eligible_branches),
        (fallback_branch, fallback_offset),
        (cached_branch, fallback_offset),
        (postlude_branch, postlude_offset),
        (return_handler_offset - ENTRY_OFFSET + 2, fallback_offset),
    ]
    for operand_offset, target_offset in branch_targets:
        displacement = target_offset - (operand_offset + 1)
        if not -128 <= displacement <= 127:
            raise ValueError("V2.2 gateway branch exceeds the signed relative-jump range")
        code[operand_offset] = displacement & 0xFF

    if len(code) > ENTRY_AREA_SIZE:
        raise ValueError("V2.2 entry gateway and return handler exceed the reserved area")
    code.extend(bytes([0xFF]) * (ENTRY_AREA_SIZE - len(code)))
    return bytes(code), return_handler_offset


def build_opening_dialogue_pilot(
    opening_rom: bytes,
    source_rom: bytes,
    manifest: Any,
    opening_glyph_asset: Any,
    shared_glyph_asset: Any,
    practice_glyph_asset: Any,
    tile_candidate: Any,
    encoding_candidate: Any,
    context_plan: Any,
    context_encoding: Any,
    dialogue_context_ids: tuple[str, ...] | None = None,
    gateway_layout: GatewayLayout = "v2.1",
    prefilter_pointer_highs: bool = False,
    dialogue_loader_return_b: int | None = None,
    restore_dialogue_patterns_from_rom: bool = False,
    preserve_dialogue_return_code: bool = False,
) -> bytes:
    if gateway_layout not in ("v2.1", "v2.2", "v2.3"):
        raise ValueError(f"unsupported gateway layout: {gateway_layout}")
    if prefilter_pointer_highs and gateway_layout not in ("v2.2", "v2.3"):
        raise ValueError("pointer-high prefilter requires the V2.2 or V2.3 gateway layout")
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    if hashlib.sha256(source_rom).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 does not match the verified original")
    if not verify_rom(source_rom).passed:
        raise ValueError("source ROM failed checksum verification")
    if len(opening_rom) != MENU_EXPANDED_SIZE:
        raise ValueError(f"opening base must be exactly {MENU_EXPANDED_SIZE} bytes")
    if hashlib.sha256(opening_rom).hexdigest() != EXPECTED_OPENING_BASE_SHA256:
        raise ValueError("opening base SHA-256 does not match the SameBoy-verified ROM")
    if not verify_rom(opening_rom).passed:
        raise ValueError("opening base failed checksum verification")

    contexts, opening_payload = build_contexts(
        source_rom,
        manifest,
        opening_glyph_asset,
        shared_glyph_asset,
        practice_glyph_asset,
        tile_candidate,
        encoding_candidate,
        context_plan,
        context_encoding,
        vertical_8=False,
        practice_runtime_signature=(
            PRACTICE_RUNTIME_SIGNATURE_V2_3 if gateway_layout == "v2.3" else None
        ),
        dialogue_loader_return_b=dialogue_loader_return_b,
        restore_dialogue_patterns_from_rom=restore_dialogue_patterns_from_rom,
        preserve_dialogue_return_code=preserve_dialogue_return_code,
    )
    if opening_rom[OPENING_SOURCE_OFFSET:OPENING_SOURCE_END] != opening_payload:
        raise ValueError("opening base text differs from the confirmed translation")
    opening_context, *available_dialogue_contexts = contexts
    if dialogue_context_ids is None:
        dialogue_contexts = available_dialogue_contexts
    else:
        if not dialogue_context_ids or len(set(dialogue_context_ids)) != len(dialogue_context_ids):
            raise ValueError("dialogue context IDs must be a non-empty unique sequence")
        requested_contexts = set(dialogue_context_ids)
        known_contexts = {context.record_id for context in available_dialogue_contexts}
        unknown_contexts = requested_contexts - known_contexts
        if unknown_contexts:
            raise ValueError(
                f"unknown dialogue context IDs: {', '.join(sorted(unknown_contexts))}"
            )
        dialogue_contexts = [
            context
            for context in available_dialogue_contexts
            if context.record_id in requested_contexts
        ]
    for context in dialogue_contexts:
        if context.source_offset + len(context.payload) > SOURCE_SIZE:
            raise ValueError(f"{context.record_id} payload is outside mirrored source banks")
        if source_rom[
            context.source_offset:context.source_offset + len(context.payload)
        ] != opening_rom[
            context.source_offset:context.source_offset + len(context.payload)
        ]:
            raise ValueError(f"opening base already modifies the {context.record_id} text span")

    opening_layout = _opening_bank_layout(opening_context, opening_rom)
    opening_loader_offset = align_up(opening_layout.used_end, 0x100)
    dialogue_layout_start = align_up(
        opening_loader_offset + len(opening_layout.loader),
        0x100,
    )
    dialogue_layout = build_context_bank_layout(
        tuple(dialogue_contexts),
        dialogue_layout_start,
    )
    opening_restore_copy_offset = align_up(_dispatcher_end(dialogue_layout), 0x10)
    opening_restore_copy = build_rom_restore_bank_helper(
        list(opening_context.glyphs),
        bank_cpu_address(opening_layout.original_patterns_offset),
        opening_context.restore_cursor,
        bank_cpu_address(opening_restore_copy_offset),
    )
    if opening_restore_copy_offset + len(opening_restore_copy) > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("opening restore helper exceeds the bank-10 window")
    all_contexts = (opening_context, *dialogue_contexts)
    all_restore_offsets = (
        opening_restore_copy_offset,
        *dialogue_layout.restore_offsets,
    )
    restore_dispatcher = build_restore_dispatcher(all_contexts, all_restore_offsets)
    if len(restore_dispatcher) > len(opening_layout.restore_helper):
        raise ValueError("unified restore dispatcher does not fit the opening helper area")

    gateway_template = _build_bank10_gateway(0x4000, gateway_layout)
    unified_dispatcher_offset = SOURCE_SIZE + len(gateway_template)
    unified_dispatcher = _build_unified_load_dispatcher(
        opening_loader_offset,
        dialogue_layout.load_dispatcher_offset,
    )
    bank10_gateway = _build_bank10_gateway(
        bank_cpu_address(unified_dispatcher_offset),
        gateway_layout,
    )
    if len(bank10_gateway) != len(gateway_template):
        raise ValueError("bank-10 gateway size changed during layout")
    if unified_dispatcher_offset + len(unified_dispatcher) > opening_layout.pattern_offset:
        raise ValueError("unified dispatcher does not fit the original opening-loader area")

    result = bytearray(opening_rom)
    entry_banks = tuple(dict.fromkeys(
        (opening_context.bank, *(context.bank for context in dialogue_contexts))
    ))
    if gateway_layout in ("v2.2", "v2.3"):
        entry_pointer_highs = (
            tuple(dict.fromkeys(
                (opening_context.pointer_high, *(context.pointer_high for context in dialogue_contexts))
            ))
            if prefilter_pointer_highs
            else None
        )
        entry_code, return_handler_address = _build_v2_2_entry_code(
            entry_banks,
            entry_pointer_highs,
        )
        fixed_gateway_stub = _build_fixed_gateway_stub(gateway_layout)
        gateway_completion = _build_fixed_gateway_completion(return_handler_address)
    else:
        entry_code = build_entry_code(entry_banks)
        fixed_gateway_stub = _build_fixed_gateway_stub()
        gateway_completion = _build_fixed_gateway_completion()
    completion_offset = POSTLUDE_OFFSET + len(fixed_gateway_stub)
    fallback_end = BANK_RESTORE_STUB_OFFSET + len(OPENING_GATE_MISS_CODE)
    if (
        len(entry_code) != ENTRY_AREA_SIZE
        or completion_offset + len(gateway_completion) > BANK_RESTORE_STUB_OFFSET
        or opening_rom[
            BANK_RESTORE_STUB_OFFSET:fallback_end
        ] != OPENING_GATE_MISS_CODE
    ):
        raise ValueError("opening gateway or fallback layout is invalid")
    result[ENTRY_OFFSET:ENTRY_OFFSET + len(entry_code)] = entry_code
    result[
        MBC1_MIRROR_OFFSET + ENTRY_OFFSET:
        MBC1_MIRROR_OFFSET + ENTRY_OFFSET + len(entry_code)
    ] = entry_code

    result[POSTLUDE_OFFSET:BANK_RESTORE_STUB_OFFSET] = bytes(
        [0xFF]
    ) * (BANK_RESTORE_STUB_OFFSET - POSTLUDE_OFFSET)
    result[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(fixed_gateway_stub)] = (
        fixed_gateway_stub
    )
    result[completion_offset:completion_offset + len(gateway_completion)] = (
        gateway_completion
    )
    mirror_postlude_offset = MBC1_MIRROR_OFFSET + POSTLUDE_OFFSET
    result[
        mirror_postlude_offset:
        mirror_postlude_offset + BANK_RESTORE_STUB_OFFSET - POSTLUDE_OFFSET
    ] = bytes([0xFF]) * (BANK_RESTORE_STUB_OFFSET - POSTLUDE_OFFSET)
    result[
        mirror_postlude_offset:
        mirror_postlude_offset + len(fixed_gateway_stub)
    ] = fixed_gateway_stub
    mirror_completion_offset = mirror_postlude_offset + len(fixed_gateway_stub)
    result[
        mirror_completion_offset:
        mirror_completion_offset + len(gateway_completion)
    ] = gateway_completion

    if (
        result[BANK_RESTORE_STUB_OFFSET:fallback_end] != OPENING_GATE_MISS_CODE
        or result[
            MBC1_MIRROR_OFFSET + BANK_RESTORE_STUB_OFFSET:
            MBC1_MIRROR_OFFSET + fallback_end
        ] != OPENING_GATE_MISS_CODE
    ):
        raise ValueError("opening fallback must remain byte-identical in both fixed banks")

    result[SOURCE_SIZE:opening_layout.pattern_offset] = bytes(
        [0xFF]
    ) * (opening_layout.pattern_offset - SOURCE_SIZE)
    result[SOURCE_SIZE:SOURCE_SIZE + len(bank10_gateway)] = bank10_gateway
    result[
        unified_dispatcher_offset:
        unified_dispatcher_offset + len(unified_dispatcher)
    ] = unified_dispatcher

    _write_component(
        result,
        opening_loader_offset,
        opening_layout.loader,
        opening_rom,
    )
    _write_component(
        result,
        dialogue_layout.load_dispatcher_offset,
        dialogue_layout.load_dispatcher,
        opening_rom,
    )
    for offset, data in zip(dialogue_layout.loader_offsets, dialogue_layout.loaders):
        _write_component(result, offset, data, opening_rom)
    for offset, data in zip(dialogue_layout.pattern_offsets, dialogue_layout.patterns):
        _write_component(result, offset, data, opening_rom)
    for offset, data in zip(
        dialogue_layout.original_pattern_offsets,
        dialogue_layout.original_patterns,
    ):
        if offset is not None:
            _write_component(result, offset, data, opening_rom)
    for offset, data in zip(dialogue_layout.restore_offsets, dialogue_layout.restore_helpers):
        _write_component(result, offset, data, opening_rom)
    _write_component(
        result,
        opening_restore_copy_offset,
        opening_restore_copy,
        opening_rom,
    )

    result[
        opening_layout.restore_offset:
        opening_layout.restore_offset + len(opening_layout.restore_helper)
    ] = bytes([0xFF]) * len(opening_layout.restore_helper)
    result[
        opening_layout.restore_offset:
        opening_layout.restore_offset + len(restore_dispatcher)
    ] = restore_dispatcher

    for context in dialogue_contexts:
        start = context.source_offset
        end = start + len(context.payload)
        result[start:end] = context.payload
        mirror_start = MBC1_MIRROR_OFFSET + start
        result[mirror_start:mirror_start + len(context.payload)] = context.payload

    result[
        MENU_EXTENSION_ALIAS_OFFSET:MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE
    ] = result[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]

    checked = update_checksums(result)
    if len(checked) != MENU_EXPANDED_SIZE or not verify_rom(checked).passed:
        raise ValueError("opening-plus-dialogue ROM failed size or checksum verification")
    if checked[0x148] != MENU_ROM_SIZE_CODE:
        raise ValueError("opening-plus-dialogue ROM has an unexpected MBC1 ROM-size code")
    return checked


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_file(
    opening_path: Path,
    source_path: Path,
    manifest_path: Path,
    opening_glyphs_path: Path,
    shared_glyphs_path: Path,
    practice_glyphs_path: Path,
    tile_candidate_path: Path,
    encoding_candidate_path: Path,
    context_plan_path: Path,
    context_encoding_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, str]:
    opening_path = opening_path.resolve(strict=True)
    source_path = source_path.resolve(strict=True)
    input_paths = {
        manifest_path.resolve(strict=True),
        opening_glyphs_path.resolve(strict=True),
        shared_glyphs_path.resolve(strict=True),
        practice_glyphs_path.resolve(strict=True),
        tile_candidate_path.resolve(strict=True),
        encoding_candidate_path.resolve(strict=True),
        context_plan_path.resolve(strict=True),
        context_encoding_path.resolve(strict=True),
    }
    output_path = output_path.resolve()
    if output_path in {opening_path, source_path} or output_path in input_paths:
        raise ValueError("ROM output path must differ from every input")
    if not output_path.parent.is_dir():
        raise ValueError("ROM output directory must already exist")
    if output_path.exists() and not overwrite:
        raise FileExistsError("output ROM already exists; pass --overwrite to replace it")

    inputs = [
        load_json(path)
        for path in (
            manifest_path,
            opening_glyphs_path,
            shared_glyphs_path,
            practice_glyphs_path,
            tile_candidate_path,
            encoding_candidate_path,
            context_plan_path,
            context_encoding_path,
        )
    ]
    rom = build_opening_dialogue_pilot(
        opening_path.read_bytes(),
        source_path.read_bytes(),
        *inputs,
    )
    write_output(output_path, rom, overwrite)
    if output_path.read_bytes() != rom:
        raise OSError(f"written ROM differs from generated ROM: {output_path}")
    return output_path, hashlib.sha256(rom).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a dialogue pilot on top of the verified opening ROM."
    )
    parser.add_argument(
        "--opening-base",
        type=Path,
        default=ROOT / "roms" / "oni5_opening_preview.gb",
    )
    parser.add_argument("--source", type=Path, default=ROOT / "roms" / "oni5_original.gb")
    parser.add_argument("--text-manifest", type=Path, default=ROOT / "data" / "text_manifest.json")
    parser.add_argument(
        "--opening-glyphs",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs_oni5_bank04_01330d.json",
    )
    parser.add_argument("--shared-glyphs", type=Path, default=ROOT / "data" / "chinese_glyphs.json")
    parser.add_argument(
        "--practice-glyphs",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs_oni5_bank24_01348f.json",
    )
    parser.add_argument(
        "--tile-candidate",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_candidate.json",
    )
    parser.add_argument(
        "--encoding-candidate",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
    )
    parser.add_argument(
        "--context-plan",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json",
    )
    parser.add_argument(
        "--context-encoding",
        type=Path,
        default=ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "roms" / "oni5_opening_dialogue_pilot.gb",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        output, digest = build_file(
            args.opening_base,
            args.source,
            args.text_manifest,
            args.opening_glyphs,
            args.shared_glyphs,
            args.practice_glyphs,
            args.tile_candidate,
            args.encoding_candidate,
            args.context_plan,
            args.context_encoding,
            args.output,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote opening-plus-dialogue ROM: {output} ({output.stat().st_size} bytes)")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
