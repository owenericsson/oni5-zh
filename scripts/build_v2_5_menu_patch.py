"""Build V2.5 from the immutable V1 parent with the verified V2.4.5 features."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .apply_bps_patch import apply_bps_patch, create_bps_patch
    from .build_menu_pilot import (
        MENU_EXPANDED_SIZE,
        MENU_EXTENSION_ALIAS_OFFSET,
        MENU_ROM_SIZE_CODE,
        MBC1_MIRROR_OFFSET,
        ROM_BANK_SIZE,
        build_menu_candidate,
        build_open_helper,
        compile_menu_payloads,
    )
    from .build_mbc1_expansion_probe import (
        ENTRY_OFFSET,
        GATEWAY_OFFSET,
        SOURCE_SIZE,
    )
    from .build_noticeboard_glyph_probe import (
        RESTORE_HELPER_OFFSET,
        TILE_PATTERN_SIZE,
        CachedGlyph,
        build_copy_code,
        tile_vram_address,
    )
    from .build_rom import write_output
    from .build_text_comparison_pilot import bank_cpu_address
    from .build_v2_4_roam_dialogue_patch import build_v2_4_patch
    from .compile_tile_cache_plan import compile_tile_cache_plan
    from .rom_checksums import update_checksums, verify_rom
else:
    from apply_bps_patch import apply_bps_patch, create_bps_patch
    from build_menu_pilot import (
        MENU_EXPANDED_SIZE,
        MENU_EXTENSION_ALIAS_OFFSET,
        MENU_ROM_SIZE_CODE,
        MBC1_MIRROR_OFFSET,
        ROM_BANK_SIZE,
        build_menu_candidate,
        build_open_helper,
        compile_menu_payloads,
    )
    from build_mbc1_expansion_probe import (
        ENTRY_OFFSET,
        GATEWAY_OFFSET,
        SOURCE_SIZE,
    )
    from build_noticeboard_glyph_probe import (
        RESTORE_HELPER_OFFSET,
        TILE_PATTERN_SIZE,
        CachedGlyph,
        build_copy_code,
        tile_vram_address,
    )
    from build_rom import write_output
    from build_text_comparison_pilot import bank_cpu_address
    from build_v2_4_roam_dialogue_patch import build_v2_4_patch
    from compile_tile_cache_plan import compile_tile_cache_plan
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_V1_SHA256 = "5682522e20fade44c457725a66430bae13e3d6695dcc18e04d058e4ce2e910ab"
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
EXPECTED_V2_4_5_SHA256 = "2543df09fb1dc3f83b7b197701b1f84f9ff7c7906fc39d522c2bbdb0bf239b99"

MENU_OPEN_HOOK_OFFSET = 0x19E5
MENU_OPEN_HOOK_EXPECTED = bytes.fromhex("E5 D5 F5")
MENU_OPEN_HOOK_PATCH = bytes.fromhex("C3 A0 00")
MENU_CLOSE_HOOK_OFFSET = 0x8946
MENU_CLOSE_HOOK_EXPECTED = bytes.fromhex(
    "3E FF EA 39 D2 F5 E5 21 BD 02 3E 01 F7 F5 FE 01 38 0E CA D7"
)
MENU_CLOSE_HOOK_PATCH = bytes.fromhex("E5 CD E0 00 E1")
DIALOGUE_RESTORE_HOOK_OFFSET = 0x1BE8
DIALOGUE_RESTORE_HOOK_EXPECTED = bytes.fromhex("CD 61 00")
DIALOGUE_RESTORE_HOOK_PATCH = bytes.fromhex("CD E0 00")
FIXED_GATEWAY_EXPECTED = bytes.fromhex(
    "F3 3E 10 EA 00 20 CD 00 40 F5 FA AA FF EA 00 20 FB F1 C3 B6 00"
)
FIXED_GATEWAY_PATCH = bytes.fromhex(
    "F5 F3 3E 10 EA 00 20 CD 00 40 F5 FA A9 FF EA 00 20 FB F1 C3 61 00"
)
MAIN_GATEWAY_EXPECTED = bytes.fromhex("C3 A0 00 00")
MAIN_GATEWAY_PATCH = bytes.fromhex("C3 E0 00 00")
BANK10_GATEWAY_OFFSET = SOURCE_SIZE
BANK10_GATEWAY_EXPECTED = bytes.fromhex("CD 04 40 C9")

BANK10_START = SOURCE_SIZE
BANK10_END = SOURCE_SIZE + ROM_BANK_SIZE
ROM_ALLOCATION_SIZE = 0x800
ROM_ALLOCATION_ALIGNMENT = 0x100

GLYPH_PATTERN_RELATIVE_OFFSET = 0x000
ORIGINAL_PATTERN_RELATIVE_OFFSET = 0x100
MENU_LOADER_RELATIVE_OFFSET = 0x200
MENU_RESTORE_RELATIVE_OFFSET = 0x300
MENU_DISPATCHER_RELATIVE_OFFSET = 0x400
GATEWAY_ROUTER_RELATIVE_OFFSET = 0x440

MENU_MARKER = 0x80
ENTRY_RETURN_HANDLER = bytes.fromhex(
    "FE 02 28 0F FE 03 28 10 B7 CA F7 00 "
    "F1 FA F0 C4 C3 0C 18 "
    "F1 21 03 00 C9 "
    "F1 3E FF EA 39 D2 C9"
)

V2_4_INPUT_FILES = (
    "text_manifest.json",
    "chinese_glyphs_oni5_bank04_01330d.json",
    "chinese_glyphs.json",
    "chinese_glyphs_oni5_bank24_01348f.json",
    "tile_cache_plan_candidate.json",
    "translation_encoding_candidate.json",
    "tile_cache_plan_oni5_bank0c_030ee8.json",
    "translation_encoding_oni5_bank0c_030ee8.json",
)


def _require_span(
    rom: bytes | bytearray,
    offset: int,
    expected: bytes,
    label: str,
) -> None:
    if rom[offset:offset + len(expected)] != expected:
        raise ValueError(f"{label} bytes do not match the verified V2.4.5 layout")


def _restore_dispatcher_cpu_address(base_rom: bytes) -> int:
    helper = base_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + 24
    ]
    expected_prefix = bytes.fromhex(
        "F5 FA AA FF F5 F3 3E 10 EA 00 20 CD"
    )
    expected_suffix = bytes.fromhex(
        "F1 EA 00 20 FB F1 21 03 00 C9"
    )
    if (
        len(helper) != 24
        or helper[:len(expected_prefix)] != expected_prefix
        or helper[len(expected_prefix) + 2:] != expected_suffix
    ):
        raise ValueError("V2.4.5 restore gateway has an unexpected fixed helper")
    cpu_address = int.from_bytes(
        helper[len(expected_prefix):len(expected_prefix) + 2],
        "little",
    )
    if not 0x4000 <= cpu_address < 0x8000:
        raise ValueError("V2.4.5 restore dispatcher is outside the bank-10 window")
    return cpu_address


def _allocate_bank10_block(base_rom: bytes) -> int:
    start = BANK10_START + ROM_ALLOCATION_ALIGNMENT
    start = (
        start + ROM_ALLOCATION_ALIGNMENT - 1
    ) & ~(ROM_ALLOCATION_ALIGNMENT - 1)
    for candidate in range(
        start,
        BANK10_END - ROM_ALLOCATION_SIZE + 1,
        ROM_ALLOCATION_ALIGNMENT,
    ):
        if base_rom[candidate:candidate + ROM_ALLOCATION_SIZE] == bytes(
            [0xFF]
        ) * ROM_ALLOCATION_SIZE:
            return candidate
    raise ValueError("bank-10 has no verified 0x800-byte free allocation block")


def _patch_relative_branches(
    code: bytearray,
    branches: list[tuple[int, str]],
    labels: dict[str, int],
) -> None:
    for operand_offset, label in branches:
        displacement = labels[label] - (operand_offset + 1)
        if not -128 <= displacement <= 127:
            raise ValueError(f"generated branch to {label} exceeds signed range")
        code[operand_offset] = displacement & 0xFF


def _build_menu_loader(
    glyphs: list[CachedGlyph],
    pattern_cpu_address: int,
) -> bytes:
    code = bytearray.fromhex("C5 D5 E5")
    for index, glyph in enumerate(glyphs):
        code.extend(
            build_copy_code(
                pattern_cpu_address + index * TILE_PATTERN_SIZE,
                tile_vram_address(glyph.tile),
            )
        )
    code.extend(bytes((0x3E, glyphs[0].tile)) + bytes.fromhex("EA F2 C4"))
    code.extend(bytes.fromhex("3E 01 E1 D1 C1 C9"))
    return bytes(code)


def _build_menu_restore_helper(
    glyphs: list[CachedGlyph],
    original_patterns_cpu_address: int,
    helper_cpu_address: int,
) -> bytes:
    if len(glyphs) == 0:
        raise ValueError("menu restore helper requires at least one glyph")
    code = bytearray.fromhex("C5 D5 E5 F5 FA F2 C4 FE")
    code.append(glyphs[0].tile)
    code.extend(bytes.fromhex("C2 00 00"))
    return_operand_offset = len(code) - 2
    for index, glyph in enumerate(glyphs):
        code.extend(
            build_copy_code(
                original_patterns_cpu_address + index * TILE_PATTERN_SIZE,
                tile_vram_address(glyph.tile),
            )
        )
    code.extend(bytes.fromhex("AF EA F2 C4"))
    common_offset = len(code)
    code.extend(bytes.fromhex("F1 E1 D1 C1 C9"))
    return_address = helper_cpu_address + common_offset
    code[
        return_operand_offset:return_operand_offset + 2
    ] = return_address.to_bytes(2, "little")
    return bytes(code)


def _build_menu_dispatcher(
    loader_cpu_address: int,
    restore_dispatcher_cpu_address: int,
    glyphs: list[CachedGlyph],
) -> bytes:
    if not glyphs:
        raise ValueError("menu dispatcher requires at least one glyph")
    code = bytearray.fromhex("C5 D5 E5 FA F2 C4 FE")
    code.append(glyphs[0].tile)
    branches: list[tuple[int, str]] = []
    code.extend((0x28, 0))
    branches.append((len(code) - 1, "cached"))
    code.extend(bytes.fromhex("B7 28 00"))
    branches.append((len(code) - 1, "load"))
    code.append(0xCD)
    code.extend(restore_dispatcher_cpu_address.to_bytes(2, "little"))
    code.extend(bytes.fromhex("FA F2 C4 B7 20 00"))
    branches.append((len(code) - 1, "abort"))
    labels = {"load": len(code)}
    code.append(0xCD)
    code.extend(loader_cpu_address.to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 01 E1 D1 C1 C9"))

    labels["abort"] = len(code)
    code.extend(bytes.fromhex("3E 01 E1 D1 C1 C9"))
    labels["cached"] = len(code)
    code.extend(bytes.fromhex("3E 01 E1 D1 C1 C9"))
    _patch_relative_branches(code, branches, labels)
    return bytes(code)


def _build_gateway_router(
    menu_restore_cpu_address: int,
    dialogue_restore_cpu_address: int,
) -> bytes:
    code = bytearray.fromhex("C5 D5 E5 F5 F8 0E 2A FE EB")
    branches: list[tuple[int, str]] = []
    labels: dict[str, int] = {}

    code.extend((0x28, 0))
    branches.append((len(code) - 1, "dialogue-check"))
    code.extend(bytes.fromhex("FE 4A"))
    code.extend((0x20, 0))
    branches.append((len(code) - 1, "normal"))
    code.extend(bytes.fromhex("7E FE 49"))
    code.extend((0x20, 0))
    branches.append((len(code) - 1, "normal"))

    code.extend(bytes.fromhex("F1 E1 D1 C1 CD"))
    code.extend(menu_restore_cpu_address.to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 03 C9"))

    labels["dialogue-check"] = len(code)
    code.extend(bytes.fromhex("7E FE 1B"))
    code.extend((0x20, 0))
    branches.append((len(code) - 1, "normal"))
    code.extend(bytes.fromhex("F1 E1 D1 C1 CD"))
    code.extend(dialogue_restore_cpu_address.to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 02 C9"))

    labels["normal"] = len(code)
    code.extend(bytes.fromhex("F1 E1 D1 C1 C3 04 40"))
    _patch_relative_branches(code, branches, labels)
    return bytes(code)


def build_integrated_menu(
    base_v2_4_5_rom: bytes,
    source_rom: bytes,
    menu_manifest: Any,
    glyph_asset: Any,
) -> bytes:
    if len(base_v2_4_5_rom) != MENU_EXPANDED_SIZE:
        raise ValueError("V2.4.5 base ROM must be exactly 1 MiB")
    if hashlib.sha256(base_v2_4_5_rom).hexdigest() != EXPECTED_V2_4_5_SHA256:
        raise ValueError("menu integration requires the verified V2.4.5 base ROM")
    if not verify_rom(base_v2_4_5_rom).passed:
        raise ValueError("V2.4.5 base ROM failed checksum verification")
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    source_digest = hashlib.sha256(source_rom).hexdigest()
    if source_digest != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 does not match the verified original")

    _require_span(
        base_v2_4_5_rom,
        GATEWAY_OFFSET,
        MAIN_GATEWAY_EXPECTED,
        "main gateway",
    )
    _require_span(
        base_v2_4_5_rom,
        MBC1_MIRROR_OFFSET + GATEWAY_OFFSET,
        MAIN_GATEWAY_EXPECTED,
        "main gateway mirror",
    )
    _require_span(
        base_v2_4_5_rom,
        ENTRY_OFFSET,
        bytes.fromhex(
            "F5 FA AE FF FE 33 28 06 FE 0E 28 02 18 49 FA F2 C4 "
            "B7 20 43 18 2A B7 28 3E F1 FA F0 C4 C3 0C 18"
        ),
        "V2.4.5 shared entry",
    )
    _require_span(
        base_v2_4_5_rom,
        MENU_OPEN_HOOK_OFFSET,
        MENU_OPEN_HOOK_EXPECTED,
        "menu open hook",
    )
    _require_span(
        base_v2_4_5_rom,
        MENU_CLOSE_HOOK_OFFSET,
        MENU_CLOSE_HOOK_EXPECTED,
        "menu close hook",
    )
    _require_span(
        base_v2_4_5_rom,
        DIALOGUE_RESTORE_HOOK_OFFSET,
        DIALOGUE_RESTORE_HOOK_EXPECTED,
        "dialogue restore hook",
    )
    _require_span(
        base_v2_4_5_rom,
        0xE0,
        FIXED_GATEWAY_EXPECTED,
        "fixed gateway",
    )
    _require_span(
        base_v2_4_5_rom,
        MBC1_MIRROR_OFFSET + 0xE0,
        FIXED_GATEWAY_EXPECTED,
        "fixed gateway mirror",
    )
    _require_span(
        base_v2_4_5_rom,
        BANK10_GATEWAY_OFFSET,
        BANK10_GATEWAY_EXPECTED,
        "bank-10 gateway",
    )

    dispatcher_cpu_address = _restore_dispatcher_cpu_address(base_v2_4_5_rom)
    restore_file_offset = (
        SOURCE_SIZE + dispatcher_cpu_address - 0x4000
    )
    _require_span(
        base_v2_4_5_rom,
        restore_file_offset,
        bytes.fromhex("FA F2 C4"),
        "V2.4.5 restore dispatcher",
    )

    compiled_records, glyphs = compile_menu_payloads(
        source_rom,
        menu_manifest,
        glyph_asset,
    )
    candidate = build_menu_candidate(glyph_asset)
    cache_plan = compile_tile_cache_plan(source_rom, candidate, glyph_asset)
    entries = cache_plan.get("entries")
    if not isinstance(entries, list):
        raise ValueError("menu tile cache plan entries must be a list")
    restore_patterns_by_character = {}
    for index, value in enumerate(entries):
        if not isinstance(value, dict):
            raise ValueError(f"tile cache plan entry {index} must be an object")
        character = value.get("character")
        pattern_hex = value.get("restore_pattern_2bpp_hex")
        if not isinstance(character, str) or not isinstance(pattern_hex, str):
            raise ValueError(f"tile cache plan entry {index} has no original pattern")
        try:
            pattern = bytes.fromhex(pattern_hex)
        except ValueError as exc:
            raise ValueError(
                f"tile cache plan entry {index} has an invalid original pattern"
            ) from exc
        if len(pattern) != TILE_PATTERN_SIZE:
            raise ValueError(
                f"tile cache plan entry {index} original pattern must be 16 bytes"
            )
        restore_patterns_by_character[character] = pattern

    if len(restore_patterns_by_character) != len(glyphs):
        raise ValueError("menu original-pattern plan does not match the glyph set")
    original_patterns = [
        restore_patterns_by_character[glyph.character]
        for glyph in glyphs
    ]
    marker = glyphs[0].tile
    if marker != MENU_MARKER:
        raise ValueError("menu cache marker must remain the audited tile 0x80")

    allocation_start = _allocate_bank10_block(base_v2_4_5_rom)
    relative_offsets = (
        GLYPH_PATTERN_RELATIVE_OFFSET,
        ORIGINAL_PATTERN_RELATIVE_OFFSET,
        MENU_LOADER_RELATIVE_OFFSET,
        MENU_RESTORE_RELATIVE_OFFSET,
        MENU_DISPATCHER_RELATIVE_OFFSET,
        GATEWAY_ROUTER_RELATIVE_OFFSET,
    )
    if len(set(relative_offsets)) != len(relative_offsets):
        raise ValueError("V2.5 ROM allocation offsets are not unique")

    glyph_pattern_offset = allocation_start + GLYPH_PATTERN_RELATIVE_OFFSET
    original_pattern_offset = allocation_start + ORIGINAL_PATTERN_RELATIVE_OFFSET
    loader_offset = allocation_start + MENU_LOADER_RELATIVE_OFFSET
    restore_helper_offset = allocation_start + MENU_RESTORE_RELATIVE_OFFSET
    dispatcher_offset = allocation_start + MENU_DISPATCHER_RELATIVE_OFFSET
    router_offset = allocation_start + GATEWAY_ROUTER_RELATIVE_OFFSET

    glyph_pattern_cpu = bank_cpu_address(glyph_pattern_offset)
    original_pattern_cpu = bank_cpu_address(original_pattern_offset)
    loader_cpu = bank_cpu_address(loader_offset)
    restore_helper_cpu = bank_cpu_address(restore_helper_offset)
    dispatcher_cpu = bank_cpu_address(dispatcher_offset)
    router_cpu = bank_cpu_address(router_offset)

    loader = _build_menu_loader(glyphs, glyph_pattern_cpu)
    restore_helper = _build_menu_restore_helper(
        glyphs,
        original_pattern_cpu,
        restore_helper_cpu,
    )
    dispatcher = _build_menu_dispatcher(
        loader_cpu,
        dispatcher_cpu_address,
        glyphs,
    )
    router = _build_gateway_router(
        restore_helper_cpu,
        dispatcher_cpu_address,
    )
    open_helper = build_open_helper(dispatcher_cpu)

    spans = (
        (glyph_pattern_offset, len(glyphs) * TILE_PATTERN_SIZE),
        (original_pattern_offset, len(original_patterns) * TILE_PATTERN_SIZE),
        (loader_offset, len(loader)),
        (restore_helper_offset, len(restore_helper)),
        (dispatcher_offset, len(dispatcher)),
        (router_offset, len(router)),
    )
    allocation_end = allocation_start + ROM_ALLOCATION_SIZE
    for start, size in spans:
        if start < allocation_start or start + size > allocation_end:
            raise ValueError("V2.5 bank-10 component exceeds its reserved allocation")
    for (first_start, first_size), (second_start, second_size) in zip(
        sorted(spans),
        sorted(spans)[1:],
    ):
        if first_start + first_size > second_start:
            raise ValueError("V2.5 bank-10 components overlap")
    if len(open_helper) > 0x20:
        raise ValueError("V2.5 menu entry helper exceeds its fixed-bank slot")
    if len(FIXED_GATEWAY_PATCH) > 0x17:
        raise ValueError("V2.5 fixed gateway exceeds its reserved area")
    if len(MENU_OPEN_HOOK_PATCH) != len(MENU_OPEN_HOOK_EXPECTED):
        raise ValueError("V2.5 menu-open hook changes instruction span")
    if len(MENU_CLOSE_HOOK_PATCH) != 5:
        raise ValueError("V2.5 menu-close hook changes instruction span")
    if len(ENTRY_RETURN_HANDLER) > 0x1F:
        raise ValueError("V2.5 entry return handler exceeds its fixed-bank slot")

    result = bytearray(base_v2_4_5_rom)
    result[allocation_start:allocation_end] = bytes([0xFF]) * ROM_ALLOCATION_SIZE
    result[glyph_pattern_offset:glyph_pattern_offset + len(glyphs) * 16] = b"".join(
        glyph.pattern for glyph in glyphs
    )
    packed_original_patterns = b"".join(original_patterns)
    result[
        original_pattern_offset:
        original_pattern_offset + len(packed_original_patterns)
    ] = packed_original_patterns
    result[loader_offset:loader_offset + len(loader)] = loader
    result[restore_helper_offset:restore_helper_offset + len(restore_helper)] = (
        restore_helper
    )
    result[dispatcher_offset:dispatcher_offset + len(dispatcher)] = dispatcher
    result[router_offset:router_offset + len(router)] = router

    for record in compiled_records:
        offset = record["offset"]
        payload = bytes.fromhex(record["encoded_hex"])
        result[offset:offset + len(payload)] = payload
        mirror_offset = MBC1_MIRROR_OFFSET + offset
        result[mirror_offset:mirror_offset + len(payload)] = payload

    result[ENTRY_OFFSET:ENTRY_OFFSET + len(open_helper)] = open_helper
    result[
        MBC1_MIRROR_OFFSET + ENTRY_OFFSET:
        MBC1_MIRROR_OFFSET + ENTRY_OFFSET + len(open_helper)
    ] = open_helper
    result[
        MENU_OPEN_HOOK_OFFSET:
        MENU_OPEN_HOOK_OFFSET + len(MENU_OPEN_HOOK_PATCH)
    ] = MENU_OPEN_HOOK_PATCH
    result[
        MBC1_MIRROR_OFFSET + MENU_OPEN_HOOK_OFFSET:
        MBC1_MIRROR_OFFSET + MENU_OPEN_HOOK_OFFSET + len(MENU_OPEN_HOOK_PATCH)
    ] = MENU_OPEN_HOOK_PATCH
    result[
        MENU_CLOSE_HOOK_OFFSET:
        MENU_CLOSE_HOOK_OFFSET + len(MENU_CLOSE_HOOK_PATCH)
    ] = MENU_CLOSE_HOOK_PATCH
    result[
        MBC1_MIRROR_OFFSET + MENU_CLOSE_HOOK_OFFSET:
        MBC1_MIRROR_OFFSET + MENU_CLOSE_HOOK_OFFSET + len(MENU_CLOSE_HOOK_PATCH)
    ] = MENU_CLOSE_HOOK_PATCH
    result[
        DIALOGUE_RESTORE_HOOK_OFFSET:
        DIALOGUE_RESTORE_HOOK_OFFSET + len(DIALOGUE_RESTORE_HOOK_PATCH)
    ] = DIALOGUE_RESTORE_HOOK_PATCH
    result[
        MBC1_MIRROR_OFFSET + DIALOGUE_RESTORE_HOOK_OFFSET:
        MBC1_MIRROR_OFFSET + DIALOGUE_RESTORE_HOOK_OFFSET + len(DIALOGUE_RESTORE_HOOK_PATCH)
    ] = DIALOGUE_RESTORE_HOOK_PATCH
    result[
        GATEWAY_OFFSET:GATEWAY_OFFSET + len(MAIN_GATEWAY_PATCH)
    ] = MAIN_GATEWAY_PATCH
    result[
        MBC1_MIRROR_OFFSET + GATEWAY_OFFSET:
        MBC1_MIRROR_OFFSET + GATEWAY_OFFSET + len(MAIN_GATEWAY_PATCH)
    ] = MAIN_GATEWAY_PATCH
    result[
        0xE0:0xE0 + len(FIXED_GATEWAY_PATCH)
    ] = FIXED_GATEWAY_PATCH
    result[
        MBC1_MIRROR_OFFSET + 0xE0:
        MBC1_MIRROR_OFFSET + 0xE0 + len(FIXED_GATEWAY_PATCH)
    ] = FIXED_GATEWAY_PATCH
    result[
        RESTORE_HELPER_OFFSET:
        RESTORE_HELPER_OFFSET + len(ENTRY_RETURN_HANDLER)
    ] = ENTRY_RETURN_HANDLER
    result[
        MBC1_MIRROR_OFFSET + RESTORE_HELPER_OFFSET:
        MBC1_MIRROR_OFFSET + RESTORE_HELPER_OFFSET + len(ENTRY_RETURN_HANDLER)
    ] = ENTRY_RETURN_HANDLER
    result[
        BANK10_GATEWAY_OFFSET:
        BANK10_GATEWAY_OFFSET + 3
    ] = bytes((0xCD, router_cpu & 0xFF, router_cpu >> 8))

    result[
        MENU_EXTENSION_ALIAS_OFFSET:
        MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE
    ] = result[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]

    checked = update_checksums(result)
    if len(checked) != MENU_EXPANDED_SIZE or not verify_rom(checked).passed:
        raise ValueError("integrated V2.5 ROM failed size or checksum verification")
    if checked[0x148] != MENU_ROM_SIZE_CODE:
        raise ValueError("integrated V2.5 ROM has an unexpected ROM-size code")
    if checked[
        BANK10_GATEWAY_OFFSET:BANK10_GATEWAY_OFFSET + 3
    ] != bytes((0xCD, router_cpu & 0xFF, router_cpu >> 8)):
        raise ValueError("V2.5 bank-10 gateway does not target its shared router")
    if checked[
        MENU_EXTENSION_ALIAS_OFFSET:
        MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE
    ] != checked[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]:
        raise ValueError("V2.5 bank-10 extension alias is inconsistent")
    return checked


def build_v2_5_patch(
    parent_rom: bytes,
    source_rom: bytes,
    v2_4_inputs: list[Any],
    menu_manifest: Any,
    glyph_asset: Any,
) -> tuple[bytes, bytes, str]:
    if hashlib.sha256(parent_rom).hexdigest() != EXPECTED_V1_SHA256:
        raise ValueError("V2.5 must be rebuilt from the immutable V1 ROM")
    v2_4_patch, v2_4_digest = build_v2_4_patch(
        parent_rom,
        source_rom,
        *v2_4_inputs,
        prefilter_pointer_highs=True,
        clear_dialogue_upper_tile=True,
        include_garou=True,
        restore_dialogue_patterns_from_rom=True,
        preserve_dialogue_return_code=True,
    )
    base_v2_4_5 = apply_bps_patch(parent_rom, v2_4_patch)
    if hashlib.sha256(base_v2_4_5).hexdigest() != EXPECTED_V2_4_5_SHA256:
        raise ValueError(
            "V2.4.5 rebuild does not match the runtime-verified regression baseline"
        )
    if hashlib.sha256(base_v2_4_5).hexdigest() != v2_4_digest:
        raise ValueError("V2.4.5 rebuild digest differs from its builder result")

    target_rom = build_integrated_menu(
        base_v2_4_5,
        source_rom,
        menu_manifest,
        glyph_asset,
    )
    patch = create_bps_patch(parent_rom, target_rom)
    if apply_bps_patch(parent_rom, patch) != target_rom:
        raise ValueError("V1-to-V2.5 BPS round-trip did not reproduce the target ROM")
    return patch, target_rom, hashlib.sha256(target_rom).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_v2_5_files(
    parent_path: Path,
    source_path: Path,
    patch_path: Path,
    rom_path: Path,
    overwrite: bool = False,
) -> tuple[Path, Path, str, str]:
    parent = parent_path.resolve(strict=True)
    source = source_path.resolve(strict=True)
    patch_output = patch_path.resolve()
    rom_output = rom_path.resolve()
    inputs = {
        parent,
        source,
        *(ROOT / "data" / name for name in V2_4_INPUT_FILES),
        ROOT / "data" / "menu_text_manifest.json",
        ROOT / "data" / "menu_chinese_glyphs.json",
    }
    if patch_output in inputs or rom_output in inputs or patch_output == rom_output:
        raise ValueError("V2.5 outputs must differ from each other and every input")
    if not patch_output.parent.is_dir() or not rom_output.parent.is_dir():
        raise ValueError("V2.5 output directories must already exist")
    if not overwrite and (patch_output.exists() or rom_output.exists()):
        raise FileExistsError("a V2.5 output already exists; pass --overwrite to replace it")

    v2_4_inputs = [
        _load_json(ROOT / "data" / name)
        for name in V2_4_INPUT_FILES
    ]
    menu_manifest = _load_json(ROOT / "data" / "menu_text_manifest.json")
    glyph_asset = _load_json(ROOT / "data" / "menu_chinese_glyphs.json")
    patch, rom, rom_digest = build_v2_5_patch(
        parent.read_bytes(),
        source.read_bytes(),
        v2_4_inputs,
        menu_manifest,
        glyph_asset,
    )
    write_output(patch_output, patch, overwrite)
    write_output(rom_output, rom, overwrite)
    patch_digest = hashlib.sha256(patch).hexdigest()
    if patch_output.read_bytes() != patch or rom_output.read_bytes() != rom:
        raise OSError("written V2.5 outputs differ from the deterministic build")
    return patch_output, rom_output, patch_digest, rom_digest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build V2.5 from V1 with the verified V2.4.5 features and main menu."
    )
    parser.add_argument(
        "--parent",
        type=Path,
        default=ROOT / "roms" / "oni5_v1_opening_dialog.gb",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
    )
    parser.add_argument(
        "--output-patch",
        type=Path,
        default=ROOT / "roms" / "oni5_v2_5_main_menu.bps",
    )
    parser.add_argument(
        "--output-rom",
        type=Path,
        default=ROOT / "roms" / "oni5_v2_5_main_menu.gb",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        patch_path, rom_path, patch_digest, rom_digest = build_v2_5_files(
            args.parent,
            args.source,
            args.output_patch,
            args.output_rom,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote V1-to-V2.5 BPS patch: {patch_path}")
    print(f"BPS SHA-256: {patch_digest}")
    print(f"Wrote V2.5 ROM: {rom_path} ({rom_path.stat().st_size} bytes)")
    print(f"ROM SHA-256: {rom_digest}")
    print("Runtime validation status: pending SameBoy testing.")


if __name__ == "__main__":
    main()
