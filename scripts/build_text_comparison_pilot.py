"""Build matching 7x7 and vertically expanded 7x8 text pilot ROMs."""
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
        BANK_RESTORE_STUB,
        BANK_RESTORE_STUB_OFFSET,
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
    from .build_menu_pilot import MENU_EXPANDED_SIZE
    from .build_noticeboard_glyph_probe import (
        BACKUP_ADDRESS,
        ENTRY_AREA_SIZE,
        NOTICEBOARD_PAYLOAD_SIZE,
        NOTICEBOARD_SOURCE_BYTES,
        NOTICEBOARD_SOURCE_OFFSET,
        POSTLUDE_AREA_SIZE,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        RESTORE_HELPER_OFFSET,
        TILE_PATTERN_SIZE,
        CachedGlyph,
        build_copy_code,
        parse_noticeboard_inputs,
        tile_vram_address,
    )
    from .build_opening_text_preview_patch import (
        FONT_BANK,
        FONT_DESCRIPTOR,
        FONT_LENGTH,
        NATIVE_INPUT_CODES,
        OPENING_BANK,
        OPENING_GATE_MISS_CODE,
        OPENING_LOAD_CURSOR,
        OPENING_POINTER_HIGH,
        RESTORE_CURSOR_VALUE,
        SOURCE_END as OPENING_SOURCE_END,
        SOURCE_OFFSET as OPENING_SOURCE_OFFSET,
        create_glyph_mapping,
        encode_opening_payload,
        build_opening_mbc1_layout,
        get_confirmed_translation,
        get_eligible_tiles,
        load_glyph_patterns,
    )
    from .build_rom import apply_patch_manifest, write_output
    from .build_two_text_pilot import (
        BANK_ALIGNMENT,
        ROM_BANK_WINDOW_CPU_START,
        ROM_BANK_WINDOW_FILE_END,
        WOMAN_FIRST_CURSOR,
        WOMAN_PATCH_BYTES,
        WOMAN_PAYLOAD_SIZE,
        WOMAN_RESTORE_CURSOR,
        WOMAN_SOURCE_BYTES,
        WOMAN_SOURCE_OFFSET,
    )
    from .build_woman_glyph_probe import parse_woman_inputs
    from .decode_gb_resource import decode_resource
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
        BANK_RESTORE_STUB,
        BANK_RESTORE_STUB_OFFSET,
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
    from build_menu_pilot import MENU_EXPANDED_SIZE
    from build_noticeboard_glyph_probe import (
        BACKUP_ADDRESS,
        ENTRY_AREA_SIZE,
        NOTICEBOARD_PAYLOAD_SIZE,
        NOTICEBOARD_SOURCE_BYTES,
        NOTICEBOARD_SOURCE_OFFSET,
        POSTLUDE_AREA_SIZE,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        RESTORE_HELPER_OFFSET,
        TILE_PATTERN_SIZE,
        CachedGlyph,
        build_copy_code,
        parse_noticeboard_inputs,
        tile_vram_address,
    )
    from build_opening_text_preview_patch import (
        FONT_BANK,
        FONT_DESCRIPTOR,
        FONT_LENGTH,
        NATIVE_INPUT_CODES,
        OPENING_BANK,
        OPENING_GATE_MISS_CODE,
        OPENING_LOAD_CURSOR,
        OPENING_POINTER_HIGH,
        RESTORE_CURSOR_VALUE,
        SOURCE_END as OPENING_SOURCE_END,
        SOURCE_OFFSET as OPENING_SOURCE_OFFSET,
        create_glyph_mapping,
        encode_opening_payload,
        build_opening_mbc1_layout,
        get_confirmed_translation,
        get_eligible_tiles,
        load_glyph_patterns,
    )
    from build_rom import apply_patch_manifest, write_output
    from build_two_text_pilot import (
        BANK_ALIGNMENT,
        ROM_BANK_WINDOW_CPU_START,
        ROM_BANK_WINDOW_FILE_END,
        WOMAN_FIRST_CURSOR,
        WOMAN_PATCH_BYTES,
        WOMAN_PAYLOAD_SIZE,
        WOMAN_RESTORE_CURSOR,
        WOMAN_SOURCE_BYTES,
        WOMAN_SOURCE_OFFSET,
    )
    from build_woman_glyph_probe import parse_woman_inputs
    from decode_gb_resource import decode_resource
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"

PRACTICE_TEXT = "「今日的修行\n就到此为止」"
PRACTICE_SOURCE_OFFSET = 0x01348F
PRACTICE_SOURCE_END = 0x0134AA
PRACTICE_SOURCE_BYTES = bytes.fromhex(
    "3B 0F 07 4D 0F 07 0B 21 11 0A 12 22 4D 12 32 6D "
    "7D 4D 0D 14 27 0A 1E 14 27 15 3C"
)
PRACTICE_BANK = 0x24
PRACTICE_POINTER_HIGH = 0x74
PRACTICE_FIRST_CURSOR = 0x8F
PRACTICE_RUNTIME_SIGNATURE_V2_3 = (0x04, 0x34, 0x8F)
PRACTICE_RESTORE_CURSOR = 0xAB
SPACE_CODE = 0x4D
LINE_ADVANCE_CODE = 0x7D
PRACTICE_LINE_CAPACITIES = (15, 9)

NOTICEBOARD_BANK = 0x0C
NOTICEBOARD_POINTER_HIGH = 0x0E
NOTICEBOARD_FIRST_CURSOR = 0x34
NOTICEBOARD_RESTORE_CURSOR = 0x3D
NOTICEBOARD_MARKER = 0xA5
WOMAN_BANK = 0x0C
WOMAN_POINTER_HIGH = 0x0E
WOMAN_MARKER = 0x94
CONTEXT_BANK = 0x0C
CONTEXT_POINTER_HIGH = 0x0E
CONTEXT_MARKER = 0x85
ENTRY_BANKS = (
    OPENING_BANK,
    PRACTICE_BANK,
    NOTICEBOARD_BANK,
)
OPENING_RETURN_CODE = 0xBB
PRACTICE_RETURN_CODE = 0xBB

POSTLUDE_CODE = bytes.fromhex(
    "F3 3E 10 EA 00 20 CD 00 40 F5 FA AA FF EA 00 20 FB F1 "
    "B7 28 07 F1 FA F0 C4 C3 0C 18 C3 F7 00 00"
)
RESTORE_HELPER_SIZE = 31
PATTERN_ALIGNMENT = 0x100


@dataclass(frozen=True)
class PilotContext:
    record_id: str
    bank: int
    pointer_high: int
    first_cursor: int
    restore_cursor: int
    source_offset: int
    payload: bytes
    glyphs: tuple[CachedGlyph, ...]
    marker: int
    restore_from_rom: bool = False
    original_patterns: tuple[bytes, ...] = ()
    return_code: int | None = None
    loader_return_b: int | None = None
    preserve_return_code: bool = False


@dataclass(frozen=True)
class ContextBankLayout:
    load_dispatcher_offset: int
    load_dispatcher: bytes
    loader_offsets: tuple[int, ...]
    loaders: tuple[bytes, ...]
    pattern_offsets: tuple[int, ...]
    patterns: tuple[bytes, ...]
    original_pattern_offsets: tuple[int | None, ...]
    original_patterns: tuple[bytes, ...]
    restore_dispatcher_offset: int
    restore_dispatcher: bytes
    restore_offsets: tuple[int, ...]
    restore_helpers: tuple[bytes, ...]


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a positive power of two")
    return (value + alignment - 1) & ~(alignment - 1)


def bank_cpu_address(file_offset: int) -> int:
    address = ROM_BANK_WINDOW_CPU_START + file_offset - SOURCE_SIZE
    if not ROM_BANK_WINDOW_CPU_START <= address < 0x8000:
        raise ValueError(f"file offset 0x{file_offset:X} is outside bank-10 window")
    return address


def vertical_expand_pattern(pattern: bytes) -> bytes:
    if len(pattern) != TILE_PATTERN_SIZE:
        raise ValueError("a Game Boy 2BPP tile pattern must contain 16 bytes")
    rows = [pattern[index:index + 2] for index in range(0, TILE_PATTERN_SIZE, 2)]
    if any(len(row) != 2 for row in rows):
        raise ValueError("tile pattern does not contain eight complete rows")
    occupied = [index for index, row in enumerate(rows) if row[0] | row[1]]
    if not occupied:
        return pattern
    rows = rows[occupied[0]:occupied[-1] + 1]
    while len(rows) < 8:
        middle = (len(rows) - 1) / 2
        index = min(
            range(len(rows)),
            key=lambda row_index: (
                rows[row_index][0].bit_count() + rows[row_index][1].bit_count(),
                abs(row_index - middle),
                row_index,
            ),
        )
        rows.insert(index + 1, rows[index])
    return b"".join(rows)


def convert_glyphs(
    glyphs: list[CachedGlyph] | tuple[CachedGlyph, ...],
    vertical_8: bool,
) -> tuple[CachedGlyph, ...]:
    if not vertical_8:
        return tuple(glyphs)
    return tuple(
        CachedGlyph(glyph.character, glyph.tile, vertical_expand_pattern(glyph.pattern))
        for glyph in glyphs
    )


def build_practice_translation(
    source_rom: bytes,
    glyph_assets: tuple[Any, ...],
    tile_candidate: Any,
    vertical_8: bool,
) -> tuple[tuple[CachedGlyph, ...], bytes]:
    original = source_rom[PRACTICE_SOURCE_OFFSET:PRACTICE_SOURCE_END]
    if original != PRACTICE_SOURCE_BYTES:
        raise ValueError("practice dialogue bytes do not match the verified source")

    custom_characters = list(dict.fromkeys(
        character
        for character in PRACTICE_TEXT
        if character not in {"\n", " ", "「", "」"}
    ))
    patterns = load_glyph_patterns(glyph_assets, custom_characters)
    reserved_markers = {NOTICEBOARD_MARKER, WOMAN_MARKER, CONTEXT_MARKER}
    eligible = [
        tile for tile in get_eligible_tiles(tile_candidate)
        if tile not in reserved_markers
    ]
    if len(custom_characters) > len(eligible):
        raise ValueError("practice dialogue needs more distinct tiles than the audited pool")
    tile_by_character = dict(zip(custom_characters, eligible))
    glyphs = tuple(
        CachedGlyph(character, tile_by_character[character], patterns[character])
        for character in custom_characters
    )
    code_by_character = {
        character: tile - 0x80
        for character, tile in tile_by_character.items()
    }

    lines = PRACTICE_TEXT.split("\n")
    if len(lines) != 2 or lines[0][0] != "「" or not lines[1].endswith("」"):
        raise ValueError("practice translation must preserve its two-line native quotes")
    encoded = bytearray((NATIVE_INPUT_CODES["「"],))
    first_line = bytes(code_by_character[character] for character in lines[0][1:])
    if len(first_line) > PRACTICE_LINE_CAPACITIES[0]:
        raise ValueError("practice translation first line exceeds its verified source span")
    encoded.extend(first_line)
    encoded.extend([SPACE_CODE] * (PRACTICE_LINE_CAPACITIES[0] - len(first_line)))
    encoded.append(LINE_ADVANCE_CODE)

    second_line = bytes(code_by_character[character] for character in lines[1][:-1])
    if len(second_line) > PRACTICE_LINE_CAPACITIES[1]:
        raise ValueError("practice translation second line exceeds its verified source span")
    encoded.extend(second_line)
    encoded.extend([SPACE_CODE] * (PRACTICE_LINE_CAPACITIES[1] - len(second_line)))
    encoded.append(NATIVE_INPUT_CODES["」"])
    if len(encoded) != len(original):
        raise ValueError("practice translation must preserve the exact 27-byte text span")
    return convert_glyphs(glyphs, vertical_8), bytes(encoded)


def build_loader_helper(
    context: PilotContext,
    pattern_cpu_address: int,
) -> bytes:
    code = bytearray.fromhex("C5 D5 E5")
    if context.preserve_return_code:
        code.extend(bytes.fromhex("FA F0 C4 EA F1 C4"))
    if not context.restore_from_rom:
        for index, glyph in enumerate(context.glyphs):
            code.extend(
                build_copy_code(
                    tile_vram_address(glyph.tile),
                    BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
                )
            )
    for index, glyph in enumerate(context.glyphs):
        code.extend(
            build_copy_code(
                pattern_cpu_address + index * TILE_PATTERN_SIZE,
                tile_vram_address(glyph.tile),
            )
        )
    return_code = context.marker if context.return_code is None else context.return_code
    code.extend(bytes((0x3E, context.marker)) + bytes.fromhex("EA F2 C4"))
    code.extend(bytes((0x3E, return_code)) + bytes.fromhex("EA F0 C4 E1 D1 C1"))
    if context.loader_return_b is not None:
        code.extend((0x06, context.loader_return_b))
    code.append(0xC9)
    return bytes(code)


def build_restore_helper(
    context: PilotContext,
    helper_cpu_address: int,
    original_patterns_cpu_address: int | None,
) -> bytes:
    if context.restore_from_rom:
        if original_patterns_cpu_address is None:
            raise ValueError(f"{context.record_id} is missing ROM pattern backups")
        source_addresses = [
            original_patterns_cpu_address + index * TILE_PATTERN_SIZE
            for index in range(len(context.glyphs))
        ]
    else:
        if original_patterns_cpu_address is not None:
            raise ValueError(f"{context.record_id} unexpectedly has ROM pattern backups")
        source_addresses = [
            BACKUP_ADDRESS + index * TILE_PATTERN_SIZE
            for index in range(len(context.glyphs))
        ]

    code = bytearray.fromhex("C5 D5 F5 FA F2 C4 FE")
    code.append(context.marker)
    code.extend(bytes.fromhex("C2 00 00 FA AD FF FE"))
    code.append(context.restore_cursor)
    code.extend(bytes.fromhex("C2 00 00"))
    for glyph, source_address in zip(context.glyphs, source_addresses):
        code.extend(build_copy_code(source_address, tile_vram_address(glyph.tile)))
    code.extend(bytes.fromhex("AF EA F2 C4"))
    if context.preserve_return_code:
        code.extend(bytes.fromhex("FA F1 C4 EA F0 C4 AF EA F1 C4"))
    common_offset = len(code)
    code.extend(bytes.fromhex("F1 D1 C1 C9"))
    return_address = helper_cpu_address + common_offset
    if return_address > 0xFFFF:
        raise ValueError("restore helper return target exceeds the 16-bit CPU address range")
    for operand_offset in (9, 17):
        code[operand_offset:operand_offset + 2] = bytes(
            (return_address & 0xFF, return_address >> 8)
        )
    return bytes(code)


def build_load_dispatcher(
    contexts: tuple[PilotContext, ...],
    loader_offsets: tuple[int, ...],
) -> bytes:
    if len(contexts) != len(loader_offsets):
        raise ValueError("each text context must have exactly one loader")
    code = bytearray()
    cached_opening_branches: list[int] = []
    for context, loader_offset in zip(contexts, loader_offsets):
        block_start = len(code)
        code.extend(bytes.fromhex("FA AA FF FE"))
        code.append(context.bank)
        bank_branch = len(code)
        code.extend((0x20, 0))
        code.extend(bytes.fromhex("FA AE FF FE"))
        code.append(context.pointer_high)
        pointer_branch = len(code)
        code.extend((0x20, 0))
        code.extend(bytes.fromhex("FA AD FF FE"))
        code.append(context.first_cursor)
        cursor_branch = len(code)
        code.extend((0x20, 0))
        if context.record_id == "opening":
            code.extend(bytes.fromhex("FA F2 C4 B7"))
            cached_opening_branches.append(len(code) + 1)
            code.extend((0x20, 0))
        code.append(0xCD)
        code.extend(bank_cpu_address(loader_offset).to_bytes(2, "little"))
        code.extend(bytes.fromhex("3E 01 C9"))
        block_end = len(code)
        for branch_offset in (bank_branch, pointer_branch, cursor_branch):
            displacement = block_end - (branch_offset + 2)
            if not -128 <= displacement <= 127:
                raise ValueError("load dispatcher branch exceeds its signed range")
            code[branch_offset + 1] = displacement & 0xFF
        expected_block_size = 33 if context.record_id == "opening" else 27
        if len(code) - block_start != expected_block_size:
            raise ValueError("load dispatcher context block has an unexpected size")
    miss_target = len(code)
    code.extend(bytes.fromhex("AF C9"))
    for branch_offset in cached_opening_branches:
        displacement = miss_target - (branch_offset + 1)
        if not -128 <= displacement <= 127:
            raise ValueError("opening cache guard exceeds the signed relative-jump range")
        code[branch_offset] = displacement & 0xFF
    return bytes(code)


def build_restore_dispatcher(
    contexts: tuple[PilotContext, ...],
    restore_offsets: tuple[int, ...],
) -> bytes:
    if len(contexts) != len(restore_offsets):
        raise ValueError("each text context must have exactly one restore helper")
    code = bytearray.fromhex("FA F2 C4")
    for context, restore_offset in zip(contexts, restore_offsets):
        block_start = len(code)
        code.extend((0xFE, context.marker))
        marker_branch = len(code)
        code.extend((0x20, 0))
        code.extend(bytes.fromhex("FA AD FF FE"))
        code.append(context.restore_cursor)
        cursor_branch = len(code)
        code.extend((0x20, 0))
        code.append(0xCA)
        code.extend(bank_cpu_address(restore_offset).to_bytes(2, "little"))
        block_end = len(code)
        for branch_offset in (marker_branch, cursor_branch):
            displacement = block_end - (branch_offset + 2)
            if not -128 <= displacement <= 127:
                raise ValueError("restore dispatcher branch exceeds its signed range")
            code[branch_offset + 1] = displacement & 0xFF
        if len(code) - block_start != 14:
            raise ValueError("restore dispatcher context block has an unexpected size")
    code.append(0xC9)
    return bytes(code)


def build_context_bank_layout(
    contexts: tuple[PilotContext, ...],
    start_offset: int = BANK_SWITCH_HELPER_OFFSET,
) -> ContextBankLayout:
    signatures = [
        (context.bank, context.pointer_high, context.first_cursor)
        for context in contexts
    ]
    if len(set(signatures)) != len(contexts):
        raise ValueError("text contexts must have distinct bank/pointer/cursor signatures")
    if not contexts:
        raise ValueError("at least one text context is required")
    for context in contexts:
        if not context.glyphs:
            raise ValueError(f"{context.record_id} has no cached glyphs")
        if any(len(glyph.pattern) != TILE_PATTERN_SIZE for glyph in context.glyphs):
            raise ValueError(f"{context.record_id} has a malformed glyph pattern")
        if len({glyph.tile for glyph in context.glyphs}) != len(context.glyphs):
            raise ValueError(f"{context.record_id} contains duplicate tile assignments")
        if context.restore_from_rom and len(context.original_patterns) != len(context.glyphs):
            raise ValueError(f"{context.record_id} has incomplete original tile backups")
        if not context.restore_from_rom and context.original_patterns:
            raise ValueError(f"{context.record_id} must use WRAM backups, not ROM backups")

    load_dispatcher_offset = start_offset
    load_dispatcher_size = len(
        build_load_dispatcher(contexts, (load_dispatcher_offset,) * len(contexts))
    )
    cursor = load_dispatcher_offset + load_dispatcher_size
    loader_offsets: list[int] = []
    loaders: list[bytes] = []
    pattern_offsets: list[int] = []
    patterns: list[bytes] = []
    original_pattern_offsets: list[int | None] = []
    original_patterns: list[bytes] = []

    for context in contexts:
        loader_offset = cursor
        preliminary = build_loader_helper(context, 0x4100)
        pattern_offset = align_up(loader_offset + len(preliminary), BANK_ALIGNMENT)
        loader = build_loader_helper(context, bank_cpu_address(pattern_offset))
        pattern_data = b"".join(glyph.pattern for glyph in context.glyphs)
        if loader_offset + len(loader) > pattern_offset:
            raise ValueError(f"{context.record_id} loader overlaps glyph data")
        loader_offsets.append(loader_offset)
        loaders.append(loader)
        pattern_offsets.append(pattern_offset)
        patterns.append(pattern_data)
        cursor = pattern_offset + len(pattern_data)

        if context.restore_from_rom:
            original_offset = align_up(cursor, BANK_ALIGNMENT)
            original_data = b"".join(context.original_patterns)
            original_pattern_offsets.append(original_offset)
            original_patterns.append(original_data)
            cursor = original_offset + len(original_data)
        else:
            original_pattern_offsets.append(None)
            original_patterns.append(b"")

    restore_dispatcher_offset = align_up(cursor, BANK_ALIGNMENT)
    restore_size = len(
        build_restore_dispatcher(
            contexts,
            (restore_dispatcher_offset,) * len(contexts),
        )
    )
    cursor = restore_dispatcher_offset + restore_size
    restore_offsets: list[int] = []
    restore_helpers: list[bytes] = []
    for context, original_offset in zip(contexts, original_pattern_offsets):
        restore_offset = cursor
        original_cpu_address = (
            bank_cpu_address(original_offset) if original_offset is not None else None
        )
        helper = build_restore_helper(
            context,
            bank_cpu_address(restore_offset),
            original_cpu_address,
        )
        restore_offsets.append(restore_offset)
        restore_helpers.append(helper)
        cursor += len(helper)

    load_dispatcher = build_load_dispatcher(contexts, tuple(loader_offsets))
    restore_dispatcher = build_restore_dispatcher(contexts, tuple(restore_offsets))
    if len(load_dispatcher) != load_dispatcher_size:
        raise ValueError("load dispatcher size changed during layout")
    if restore_dispatcher_offset + len(restore_dispatcher) > restore_offsets[0]:
        raise ValueError("restore dispatcher overlaps its helper routines")
    if cursor > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("comparison-pilot helpers exceed the bank-10 ROM window")
    return ContextBankLayout(
        load_dispatcher_offset=load_dispatcher_offset,
        load_dispatcher=load_dispatcher,
        loader_offsets=tuple(loader_offsets),
        loaders=tuple(loaders),
        pattern_offsets=tuple(pattern_offsets),
        patterns=tuple(patterns),
        original_pattern_offsets=tuple(original_pattern_offsets),
        original_patterns=tuple(original_patterns),
        restore_dispatcher_offset=restore_dispatcher_offset,
        restore_dispatcher=restore_dispatcher,
        restore_offsets=tuple(restore_offsets),
        restore_helpers=tuple(restore_helpers),
    )


def build_entry_code(entry_banks: tuple[int, ...] = ENTRY_BANKS) -> bytes:
    if not entry_banks or len(set(entry_banks)) != len(entry_banks):
        raise ValueError("entry banks must be a non-empty sequence of unique banks")
    code = bytearray(ENTRY_AREA_SIZE)
    code[:] = bytes([0xFF]) * ENTRY_AREA_SIZE
    body = bytearray.fromhex("F5 FA AA FF")
    branch_operands = []
    for bank in entry_banks:
        body.extend((0xFE, bank, 0x28, 0))
        branch_operands.append(len(body) - 1)
    body.extend(bytes.fromhex("C3 F7 00"))
    gate_offset = len(body)
    body.extend(bytes.fromhex("FA F2 C4 B7 28 03 C3 F7 00 C3 E0 00"))
    for displacement_offset in branch_operands:
        displacement = gate_offset - (displacement_offset + 1)
        if not -128 <= displacement <= 127:
            raise ValueError("entry dispatch branch exceeds its signed range")
        body[displacement_offset] = displacement & 0xFF
    code[:len(body)] = body
    if len(body) > ENTRY_AREA_SIZE:
        raise ValueError("entry gateway exceeds its reserved ROM area")
    return bytes(code)


def build_postlude() -> bytes:
    if len(POSTLUDE_CODE) != POSTLUDE_AREA_SIZE:
        raise ValueError("postlude must fill its reserved 32-byte area")
    if (
        POSTLUDE_CODE[28] != 0xC3
        or int.from_bytes(POSTLUDE_CODE[29:31], "little")
        != BANK_RESTORE_STUB_OFFSET
    ):
        raise ValueError("postlude miss jump no longer lands at the gateway fallback")
    return POSTLUDE_CODE


def _read_font_patterns(source_rom: bytes, glyphs: tuple[CachedGlyph, ...]) -> tuple[bytes, ...]:
    decoded_font = decode_resource(source_rom, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    if len(decoded_font) != FONT_LENGTH:
        raise ValueError("decoded original font has an unexpected size")
    patterns = []
    for glyph in glyphs:
        start = (glyph.tile - 0x80) * TILE_PATTERN_SIZE
        pattern = decoded_font[start:start + TILE_PATTERN_SIZE]
        if len(pattern) != TILE_PATTERN_SIZE:
            raise ValueError(f"original pattern for tile 0x{glyph.tile:02X} is missing")
        patterns.append(pattern)
    return tuple(patterns)


def build_contexts(
    source_rom: bytes,
    manifest: Any,
    opening_glyph_asset: Any,
    shared_glyph_asset: Any,
    practice_glyph_asset: Any,
    tile_candidate: Any,
    encoding_candidate: Any,
    context_plan: Any,
    context_encoding: Any,
    vertical_8: bool,
    practice_runtime_signature: tuple[int, int, int] | None = None,
    dialogue_loader_return_b: int | None = None,
    restore_dialogue_patterns_from_rom: bool = False,
    preserve_dialogue_return_code: bool = False,
) -> tuple[tuple[PilotContext, ...], bytes]:
    practice_signature = (
        practice_runtime_signature
        if practice_runtime_signature is not None
        else (PRACTICE_BANK, PRACTICE_POINTER_HIGH, PRACTICE_FIRST_CURSOR)
    )
    if len(practice_signature) != 3 or any(
        not 0 <= value <= 0xFF for value in practice_signature
    ):
        raise ValueError("practice runtime signature must contain three byte values")
    if dialogue_loader_return_b is not None and not 0 <= dialogue_loader_return_b <= 0xFF:
        raise ValueError("dialogue loader return B must fit in one byte")

    opening_text = get_confirmed_translation(manifest)
    opening_glyphs, opening_codes = create_glyph_mapping(
        opening_text,
        (shared_glyph_asset, opening_glyph_asset),
        tile_candidate,
    )
    if len(opening_glyphs) != 43:
        raise ValueError(f"opening text requires 43 custom glyphs, found {len(opening_glyphs)}")
    opening_payload = encode_opening_payload(
        opening_text,
        source_rom[OPENING_SOURCE_OFFSET:OPENING_SOURCE_END],
        opening_codes,
    )
    original_opening_patterns = _read_font_patterns(source_rom, tuple(opening_glyphs))

    practice_glyphs, practice_payload = build_practice_translation(
        source_rom,
        (shared_glyph_asset, practice_glyph_asset),
        tile_candidate,
        vertical_8,
    )
    noticeboard_glyphs, noticeboard_payload = parse_noticeboard_inputs(
        tile_candidate,
        encoding_candidate,
    )
    woman_glyphs, woman_payload = parse_woman_inputs(
        tile_candidate,
        encoding_candidate,
    )
    context_glyphs, context_payload = parse_context_inputs(context_plan, context_encoding)
    dialogue_original_patterns = (
        {
            "noticeboard": _read_font_patterns(source_rom, tuple(noticeboard_glyphs)),
            "woman": _read_font_patterns(source_rom, tuple(woman_glyphs)),
            "garou": _read_font_patterns(source_rom, tuple(context_glyphs)),
        }
        if restore_dialogue_patterns_from_rom
        else {"noticeboard": (), "woman": (), "garou": ()}
    )

    if vertical_8:
        opening_glyphs = list(convert_glyphs(opening_glyphs, True))
        noticeboard_glyphs = list(convert_glyphs(noticeboard_glyphs, True))
        woman_glyphs = list(convert_glyphs(woman_glyphs, True))
        context_glyphs = list(convert_glyphs(context_glyphs, True))
    else:
        opening_glyphs = list(opening_glyphs)

    contexts = (
        PilotContext(
            "opening",
            OPENING_BANK,
            OPENING_POINTER_HIGH,
            OPENING_LOAD_CURSOR,
            RESTORE_CURSOR_VALUE,
            OPENING_SOURCE_OFFSET,
            opening_payload,
            tuple(opening_glyphs),
            opening_glyphs[0].tile,
            True,
            original_opening_patterns,
            OPENING_RETURN_CODE,
            0xCD,
        ),
        PilotContext(
            "practice",
            *practice_signature,
            PRACTICE_RESTORE_CURSOR,
            PRACTICE_SOURCE_OFFSET,
            practice_payload,
            practice_glyphs,
            practice_glyphs[0].tile,
            return_code=PRACTICE_RETURN_CODE,
        ),
        PilotContext(
            "noticeboard",
            NOTICEBOARD_BANK,
            NOTICEBOARD_POINTER_HIGH,
            NOTICEBOARD_FIRST_CURSOR,
            NOTICEBOARD_RESTORE_CURSOR,
            NOTICEBOARD_SOURCE_OFFSET,
            noticeboard_payload,
            tuple(noticeboard_glyphs),
            NOTICEBOARD_MARKER,
            restore_from_rom=restore_dialogue_patterns_from_rom,
            original_patterns=dialogue_original_patterns["noticeboard"],
            loader_return_b=dialogue_loader_return_b,
            preserve_return_code=preserve_dialogue_return_code,
        ),
        PilotContext(
            "woman",
            WOMAN_BANK,
            WOMAN_POINTER_HIGH,
            WOMAN_FIRST_CURSOR,
            WOMAN_RESTORE_CURSOR,
            WOMAN_SOURCE_OFFSET,
            woman_payload,
            tuple(woman_glyphs),
            WOMAN_MARKER,
            restore_from_rom=restore_dialogue_patterns_from_rom,
            original_patterns=dialogue_original_patterns["woman"],
            loader_return_b=dialogue_loader_return_b,
            preserve_return_code=preserve_dialogue_return_code,
        ),
        PilotContext(
            "garou",
            CONTEXT_BANK,
            CONTEXT_POINTER_HIGH,
            CONTEXT_FIRST_CHARACTER_CURSOR,
            CONTEXT_RESTORE_CURSOR,
            CONTEXT_SOURCE_OFFSET,
            context_payload,
            tuple(context_glyphs),
            CONTEXT_MARKER,
            restore_from_rom=restore_dialogue_patterns_from_rom,
            original_patterns=dialogue_original_patterns["garou"],
            loader_return_b=dialogue_loader_return_b,
            preserve_return_code=preserve_dialogue_return_code,
        ),
    )
    return contexts, opening_payload


def build_comparison_pilot(
    source_rom: bytes,
    manifest: Any,
    opening_glyph_asset: Any,
    shared_glyph_asset: Any,
    practice_glyph_asset: Any,
    tile_candidate: Any,
    encoding_candidate: Any,
    context_plan: Any,
    context_encoding: Any,
    vertical_8: bool,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    source_hash = hashlib.sha256(source_rom).hexdigest()
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"source ROM SHA-256 mismatch: found {source_hash}")
    if not verify_rom(source_rom).passed:
        raise ValueError("source ROM failed size or checksum verification")

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
        vertical_8,
    )
    if any(context.bank not in ENTRY_BANKS for context in contexts):
        raise ValueError("entry bank gate does not cover every text context")
    expected_spans = (
        (OPENING_SOURCE_OFFSET, OPENING_SOURCE_END - OPENING_SOURCE_OFFSET, "opening"),
        (PRACTICE_SOURCE_OFFSET, len(PRACTICE_SOURCE_BYTES), "practice"),
        (NOTICEBOARD_SOURCE_OFFSET, NOTICEBOARD_PAYLOAD_SIZE, "noticeboard"),
        (WOMAN_SOURCE_OFFSET, WOMAN_PATCH_BYTES, "woman"),
        (CONTEXT_SOURCE_OFFSET, CONTEXT_SOURCE_SIZE, "garou"),
    )
    for offset, size, record_id in expected_spans:
        if len(next(context.payload for context in contexts if context.record_id == record_id)) != size:
            raise ValueError(f"{record_id} payload must preserve its {size}-byte source span")

    if source_rom[
        NOTICEBOARD_SOURCE_OFFSET:NOTICEBOARD_SOURCE_OFFSET + NOTICEBOARD_PAYLOAD_SIZE
    ] != NOTICEBOARD_SOURCE_BYTES:
        raise ValueError("noticeboard source bytes do not match the verified original")
    if source_rom[
        WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + WOMAN_PAYLOAD_SIZE
    ] != WOMAN_SOURCE_BYTES:
        raise ValueError("woman source bytes do not match the verified original")
    if source_rom[
        CONTEXT_SOURCE_OFFSET:CONTEXT_SOURCE_OFFSET + CONTEXT_SOURCE_SIZE
    ] != CONTEXT_SOURCE_BYTES:
        raise ValueError("Garou source bytes do not match the verified original")
    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("tile restore hook bytes do not match the expected source")

    restore_helper_template = bytes.fromhex(
        "F5 FA AA FF F5 F3 3E 10 EA 00 20 CD 00 40 "
        "F1 EA 00 20 FB F1 21 03 00 C9"
    )
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + RESTORE_HELPER_SIZE
    ] != bytes([0xFF]) * RESTORE_HELPER_SIZE:
        raise ValueError("restore helper area is not entirely unused")
    if len(restore_helper_template) >= RESTORE_HELPER_SIZE:
        raise ValueError("restore helper template size changed")

    layout = build_context_bank_layout(contexts)
    expanded = bytearray(build_expansion_probe(source_rom))
    entry_code = build_entry_code()
    if len(OPENING_GATE_MISS_CODE) != len(BANK_RESTORE_STUB):
        raise ValueError("opening fallback must exactly fill the gateway miss handler")
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = entry_code
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = build_postlude()
    expanded[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)] = (
        RESTORE_HOOK_PATCH
    )
    expanded[
        BANK_RESTORE_STUB_OFFSET:
        BANK_RESTORE_STUB_OFFSET + len(OPENING_GATE_MISS_CODE)
    ] = OPENING_GATE_MISS_CODE
    restore_helper = (
        bytes.fromhex("F5 FA AA FF F5 F3 3E 10 EA 00 20 CD")
        + bank_cpu_address(layout.restore_dispatcher_offset).to_bytes(2, "little")
        + bytes.fromhex("F1 EA 00 20 FB F1 21 03 00 C9")
    )
    if len(restore_helper) >= RESTORE_HELPER_SIZE:
        raise ValueError("generated restore helper has an unexpected size")
    expanded[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_helper)
    ] = restore_helper

    components: list[tuple[int, bytes]] = [
        (layout.load_dispatcher_offset, layout.load_dispatcher),
    ]
    components.extend(zip(layout.loader_offsets, layout.loaders))
    components.extend(zip(layout.pattern_offsets, layout.patterns))
    components.extend(
        (offset, pattern_data)
        for offset, pattern_data in zip(
            layout.original_pattern_offsets,
            layout.original_patterns,
        )
        if offset is not None
    )
    components.append((layout.restore_dispatcher_offset, layout.restore_dispatcher))
    components.extend(zip(layout.restore_offsets, layout.restore_helpers))

    bank_baseline = bytearray([0xFF]) * (ROM_BANK_WINDOW_FILE_END - SOURCE_SIZE)
    bank_baseline[:len(BANK_SWITCH_HELPER)] = BANK_SWITCH_HELPER
    bank_baseline[BANK_SWITCH_MARKER_OFFSET - SOURCE_SIZE] = BANK_SWITCH_MARKER
    for offset, component in components:
        relative = offset - SOURCE_SIZE
        if relative < 0 or relative + len(component) > len(bank_baseline):
            raise ValueError(f"bank-10 component at 0x{offset:X} is out of range")
        if expanded[offset:offset + len(component)] != bank_baseline[relative:relative + len(component)]:
            raise ValueError(f"bank-10 area at 0x{offset:06X} is not in its expected unused state")
        expanded[offset:offset + len(component)] = component

    for context in contexts:
        expanded[context.source_offset:context.source_offset + len(context.payload)] = (
            context.payload
        )

    if expanded[
        PRACTICE_SOURCE_OFFSET + len(PRACTICE_SOURCE_BYTES)
    ] != source_rom[PRACTICE_SOURCE_END]:
        raise ValueError("practice patch changed the following page-transition control")
    if expanded[OPENING_SOURCE_OFFSET:OPENING_SOURCE_END] != opening_payload:
        raise ValueError("opening payload differs from the confirmed translation")

    base_target = update_checksums(expanded)
    if len(base_target) != EXPANDED_SIZE or not verify_rom(base_target).passed:
        raise ValueError("512 KiB comparison base failed checksum verification")
    result = update_checksums(build_opening_mbc1_layout(base_target, source_rom))
    if len(result) != MENU_EXPANDED_SIZE or not verify_rom(result).passed:
        raise ValueError("1 MiB comparison pilot failed ROM size or checksum verification")
    if result[0x148] != 0x05:
        raise ValueError("comparison ROM must declare the 1 MiB MBC1 layout")
    return result


def create_patch_manifest(source_rom: bytes, target_rom: bytes, variant: str) -> dict[str, Any]:
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
                "id": f"text-comparison-{variant}-{len(patches) + 1:03d}",
                "offset": f"0x{start:06X}",
                "expected_hex": bytes(baseline[start:offset]).hex(" ").upper(),
                "replacement_hex": target_rom[start:offset].hex(" ").upper(),
            }
        )
    if not patches:
        raise ValueError("comparison pilot produced no ROM changes")
    return {
        "schema_version": 1,
        "source_rom_sha256": hashlib.sha256(source_rom).hexdigest(),
        "target_size": f"0x{len(target_rom):X}",
        "extension_fill_byte": "0xFF",
        "scope": (
            f"confirmed opening, practice, noticeboard, woman, and Garou text contexts; "
            f"7x{7 if variant == '7x7' else 8} comparison pilot"
        ),
        "patches": patches,
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_comparison_files(
    source_path: Path,
    manifest_path: Path,
    opening_glyph_asset_path: Path,
    shared_glyph_asset_path: Path,
    practice_glyph_asset_path: Path,
    tile_candidate_path: Path,
    encoding_candidate_path: Path,
    context_plan_path: Path,
    context_encoding_path: Path,
    output_7x7_path: Path,
    output_7x8_path: Path,
    overwrite: bool = False,
) -> tuple[tuple[Path, int, str], tuple[Path, int, str]]:
    source = source_path.resolve(strict=True)
    inputs = {
        manifest_path.resolve(strict=True),
        opening_glyph_asset_path.resolve(strict=True),
        shared_glyph_asset_path.resolve(strict=True),
        practice_glyph_asset_path.resolve(strict=True),
        tile_candidate_path.resolve(strict=True),
        encoding_candidate_path.resolve(strict=True),
        context_plan_path.resolve(strict=True),
        context_encoding_path.resolve(strict=True),
    }
    outputs = (output_7x7_path.resolve(), output_7x8_path.resolve())
    if source in outputs or inputs.intersection(outputs) or outputs[0] == outputs[1]:
        raise ValueError("ROM output paths must differ from each other and every input")
    if any(not output.parent.is_dir() for output in outputs):
        raise ValueError("ROM output directories must already exist")
    if not overwrite and any(output.exists() for output in outputs):
        raise FileExistsError("a comparison ROM already exists; pass --overwrite to replace it")

    source_rom = source.read_bytes()
    values = [
        load_json(path)
        for path in (
            manifest_path,
            opening_glyph_asset_path,
            shared_glyph_asset_path,
            practice_glyph_asset_path,
            tile_candidate_path,
            encoding_candidate_path,
            context_plan_path,
            context_encoding_path,
        )
    ]
    rom_7x7 = build_comparison_pilot(source_rom, *values, vertical_8=False)
    rom_7x8 = build_comparison_pilot(source_rom, *values, vertical_8=True)
    if rom_7x7 == rom_7x8:
        raise ValueError("7x7 and 7x8 ROMs unexpectedly contain identical glyph data")
    for target, output in zip((rom_7x7, rom_7x8), outputs):
        manifest = create_patch_manifest(
            source_rom,
            target,
            "7x7" if target is rom_7x7 else "7x8",
        )
        rebuilt = update_checksums(apply_patch_manifest(source_rom, manifest))
        if rebuilt != target:
            raise ValueError(f"patch manifest does not reproduce {output.name}")
        write_output(output, target, overwrite)
        if output.read_bytes() != target:
            raise OSError(f"written ROM differs from generated ROM: {output}")
    return (
        (outputs[0], len(rom_7x7), hashlib.sha256(rom_7x7).hexdigest()),
        (outputs[1], len(rom_7x8), hashlib.sha256(rom_7x8).hexdigest()),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build same-content 7x7 and vertically expanded 7x8 test ROMs."
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
        "--output-7x7",
        type=Path,
        default=ROOT / "roms" / "oni5_texts_7x7_pilot.gb",
    )
    parser.add_argument(
        "--output-7x8",
        type=Path,
        default=ROOT / "roms" / "oni5_texts_7x8_pilot.gb",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        outputs = build_comparison_files(
            args.source,
            args.text_manifest,
            args.opening_glyphs,
            args.shared_glyphs,
            args.practice_glyphs,
            args.tile_candidate,
            args.encoding_candidate,
            args.context_plan,
            args.context_encoding,
            args.output_7x7,
            args.output_7x8,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    for label, (path, size, digest) in zip(("7x7", "7x8"), outputs):
        print(f"Wrote {label} ROM: {path} ({size} bytes)")
        print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
