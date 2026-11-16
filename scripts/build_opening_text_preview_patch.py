"""Build a BPS-only preview patch for the confirmed opening scroll text."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .apply_bps_patch import apply_bps_patch, create_bps_patch
    from .build_mbc1_expansion_probe import (
        BANK_RESTORE_STUB,
        BANK_RESTORE_STUB_OFFSET,
        BANK_SWITCH_HELPER,
        BANK_SWITCH_HELPER_OFFSET,
        BANK_SWITCH_MARKER,
        BANK_SWITCH_MARKER_OFFSET,
        ENTRY_OFFSET,
        EXPANDED_SIZE as BASE_EXPANDED_SIZE,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
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
        ENTRY_CODE,
        POSTLUDE_AREA_SIZE,
        RESTORE_HELPER_OFFSET,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        CachedGlyph,
        build_copy_code,
        tile_vram_address,
    )
    from .build_rom import write_output
    from .decode_gb_resource import decode_resource
    from .rom_checksums import update_checksums, verify_rom
else:
    from apply_bps_patch import apply_bps_patch, create_bps_patch
    from build_mbc1_expansion_probe import (
        BANK_RESTORE_STUB,
        BANK_RESTORE_STUB_OFFSET,
        BANK_SWITCH_HELPER,
        BANK_SWITCH_HELPER_OFFSET,
        BANK_SWITCH_MARKER,
        BANK_SWITCH_MARKER_OFFSET,
        ENTRY_OFFSET,
        EXPANDED_SIZE as BASE_EXPANDED_SIZE,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
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
        ENTRY_CODE,
        POSTLUDE_AREA_SIZE,
        RESTORE_HELPER_OFFSET,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        CachedGlyph,
        build_copy_code,
        tile_vram_address,
    )
    from build_rom import write_output
    from decode_gb_resource import decode_resource
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
FONT_SOURCE_SHA256 = "37b51f4f2a094a952a3cb481090c2185922a65b90c228e5bdad7b4c445ca7939"
RECORD_ID = "oni5-bank04-pointer-01330d"
OPENING_TEXT = (
    "「……远在东方的大地上，封印着\n"
    "我的灵魂。如今终于从漫长的\n"
    "沉睡中苏醒……我的家臣\n"
    "们啊，向我献上祭品吧\n"
    "为了复活仪式……」"
)
SOURCE_OFFSET = 0x01330D
SOURCE_END = 0x013368
SOURCE_PAYLOAD_SIZE = SOURCE_END - SOURCE_OFFSET
LINE_ADVANCE_OFFSETS = (0x0F, 0x22, 0x34, 0x46)
CLOSING_QUOTE_OFFSET = 0x56
TAIL_START_OFFSET = 0x57
TERMINATOR_OFFSET = 0x5A
ORIGINAL_ELLIPSIS_OFFSETS = (0x01, 0x2E, 0x54, 0x55)
ELLIPSIS_GROUPS_PER_LINE = (1, 0, 1, 0, 1)
ELLIPSIS = "…"
NATIVE_INPUT_CODES = {"「": 0x3B, "」": 0x3C}
SPACE_CODE = 0x4D
LINE_ADVANCE_CODE = 0x7D
TERMINATOR_CODE = 0x7F
ELLIPSIS_CODES_PER_LINE = (1, 0, 1, 0, 2)
D5_NATIVE_EXPANSION_TILE = 0xBA
FONT_BANK = 0x03
FONT_DESCRIPTOR = 0x5CA4
FONT_LENGTH = 0x800
ROM_BANK_WINDOW_CPU_START = 0x4000
ROM_BANK_WINDOW_FILE_END = SOURCE_SIZE + 0x4000
PATTERN_ALIGNMENT = 0x100
RESTORE_CURSOR_VALUE = 0x68
OPENING_BANK = 0x04
OPENING_POINTER_HIGH = 0x33
OPENING_LOAD_CURSOR = 0x1D
OPENING_FIRST_TILE = 0x80 + NATIVE_INPUT_CODES["「"]
OPENING_POSTLUDE_CODE = (
    bytes.fromhex("F3 3E 10 EA 00 20 CD 00 40 3E 04 EA 00 20 FB F1 3E")
    + bytes((OPENING_FIRST_TILE,))
    + bytes.fromhex("C3 0C 18")
)
OPENING_GATE_MISS_CODE = bytes.fromhex("F1 FE 60 D2 15 18 C3 07 18")
OPENING_TARGET_COPY_SPANS = (
    (MBC1_MIRROR_OFFSET, 0, 0x0134),
    (MBC1_MIRROR_OFFSET + 0x0150, 0x0150, SOURCE_SIZE - 0x0150),
    (MENU_EXTENSION_ALIAS_OFFSET, SOURCE_SIZE, ROM_BANK_SIZE),
)


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def parse_byte(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.lower().startswith("0x"):
        raise ValueError(f"{field} must be a hexadecimal byte string")
    try:
        result = int(value[2:], 16)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid hexadecimal: {value!r}") from exc
    if not 0 <= result <= 0xFF:
        raise ValueError(f"{field} must be between 0x00 and 0xFF")
    return result


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a positive power of two")
    return (value + alignment - 1) & ~(alignment - 1)


def get_confirmed_translation(manifest: Any) -> str:
    root = require_object(manifest, "text manifest")
    records = root.get("records")
    if not isinstance(records, list):
        raise ValueError("text manifest.records must be a list")
    matches = [
        require_object(record, f"text manifest.records[{index}]")
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get("id") == RECORD_ID
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one text record {RECORD_ID!r}")

    translation = require_object(matches[0].get("translation"), f"{RECORD_ID}.translation")
    if translation.get("status") != "confirmed":
        raise ValueError(f"{RECORD_ID}: translation must be confirmed")
    segments = translation.get("segments")
    if not isinstance(segments, list) or len(segments) != 1:
        raise ValueError(f"{RECORD_ID}: expected exactly one translation segment")
    segment = require_object(segments[0], f"{RECORD_ID}.translation.segments[0]")
    if segment.get("source_start") != "0x01330D":
        raise ValueError("opening translation start does not match the verified source")
    if segment.get("source_end_exclusive") != "0x013364":
        raise ValueError("opening translation end does not match the verified source")
    text = segment.get("text")
    if text != OPENING_TEXT:
        raise ValueError("opening translation differs from the confirmed preview text")
    return text


def required_custom_characters(text: str) -> list[str]:
    characters = []
    seen = set()
    for character in text:
        if character == ELLIPSIS:
            continue
        if character in {"\n", " "} or character in NATIVE_INPUT_CODES:
            continue
        if character.isspace():
            raise ValueError(f"unsupported whitespace U+{ord(character):04X}")
        if character not in seen:
            seen.add(character)
            characters.append(character)
    return characters


def load_glyph_patterns(
    glyph_assets: tuple[Any, ...],
    required_characters: list[str],
) -> dict[str, bytes]:
    patterns: dict[str, bytes] = {}
    for asset_index, value in enumerate(glyph_assets):
        root = require_object(value, f"glyph asset[{asset_index}]")
        if root.get("schema_version") != 1:
            raise ValueError(f"glyph asset[{asset_index}].schema_version must be 1")
        font = require_object(root.get("font"), f"glyph asset[{asset_index}].font")
        if font.get("source_sha256") != FONT_SOURCE_SHA256:
            raise ValueError(f"glyph asset[{asset_index}] uses an unexpected font source")
        glyph_values = root.get("glyphs")
        if not isinstance(glyph_values, list):
            raise ValueError(f"glyph asset[{asset_index}].glyphs must be a list")
        for glyph_index, item in enumerate(glyph_values):
            glyph = require_object(
                item,
                f"glyph asset[{asset_index}].glyphs[{glyph_index}]",
            )
            character = glyph.get("character")
            if character not in required_characters:
                continue
            if not isinstance(character, str) or len(character) != 1:
                raise ValueError(f"glyph asset contains an invalid character at index {glyph_index}")
            if glyph.get("codepoint") != f"U+{ord(character):04X}":
                raise ValueError(f"glyph asset codepoint mismatch for {character!r}")
            try:
                pattern = bytes.fromhex(glyph["tile_2bpp_hex"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"glyph pattern for {character!r} is missing or invalid") from exc
            if len(pattern) != 16:
                raise ValueError(f"glyph pattern for {character!r} must contain 16 bytes")
            previous = patterns.get(character)
            if previous is not None and previous != pattern:
                raise ValueError(f"glyph assets contain conflicting patterns for {character!r}")
            patterns[character] = pattern

    missing = set(required_characters) - set(patterns)
    if missing:
        raise ValueError(f"glyph assets are missing: {''.join(sorted(missing, key=ord))}")
    return patterns


def get_eligible_tiles(candidate: Any) -> list[int]:
    root = require_object(candidate, "tile cache candidate")
    pool = require_object(
        root.get("tile_pool"),
        "tile cache candidate.tile_pool",
    )
    start = parse_byte(pool.get("start"), "tile pool start")
    end = parse_byte(pool.get("end_exclusive"), "tile pool end_exclusive")
    excluded_values = pool.get("excluded_non_text_map_ids")
    native_values = pool.get("reserved_native_tile_ids")
    if not isinstance(excluded_values, list) or not isinstance(native_values, list):
        raise ValueError("tile pool must list excluded and native tile IDs")
    unavailable = {
        parse_byte(value, "excluded tile ID")
        for value in excluded_values + native_values
    }
    eligible = [tile for tile in range(start, end) if tile not in unavailable]
    if pool.get("eligible_count") != len(eligible):
        raise ValueError("tile pool eligible_count does not match its exclusions")
    if len(eligible) < 1:
        raise ValueError("tile pool has no eligible text tiles")
    return eligible


def create_glyph_mapping(
    text: str,
    glyph_assets: tuple[Any, ...],
    tile_candidate: Any,
) -> tuple[list[CachedGlyph], dict[str, int]]:
    characters = required_custom_characters(text)
    patterns = load_glyph_patterns(
        glyph_assets,
        characters,
    )
    eligible_tiles = get_eligible_tiles(tile_candidate)
    if len(characters) > len(eligible_tiles):
        raise ValueError(
            f"opening text needs {len(characters)} custom tiles, "
            f"but only {len(eligible_tiles)} are eligible"
        )

    tile_by_character = dict(zip(characters, eligible_tiles))
    conflicting_characters = [
        character
        for character, tile in tile_by_character.items()
        if tile == D5_NATIVE_EXPANSION_TILE
    ]
    spare_tiles = eligible_tiles[len(characters):]
    if len(conflicting_characters) > len(spare_tiles):
        raise ValueError(
            "opening glyph allocation would overwrite a native D5 expansion tile "
            "and has no spare tile for remapping"
        )
    for character, tile in zip(conflicting_characters, spare_tiles):
        tile_by_character[character] = tile

    glyphs = []
    code_by_character = {}
    for character in characters:
        tile = tile_by_character[character]
        input_code = tile - 0x80
        if not 0 <= input_code < 0x40:
            raise ValueError(f"tile 0x{tile:02X} has no direct text input code")
        glyphs.append(CachedGlyph(character, tile, patterns[character]))
        code_by_character[character] = input_code
    return glyphs, code_by_character


def encode_translation_line(
    line: str,
    code_by_character: dict[str, int],
    expected_ellipsis_groups: int,
    expected_ellipsis_codes: int,
) -> bytes:
    encoded = bytearray()
    found_ellipsis_group = False
    index = 0
    while index < len(line):
        character = line[index]
        if character == ELLIPSIS:
            if line[index:index + 2] != ELLIPSIS * 2 or found_ellipsis_group:
                raise ValueError("opening text must use one two-character ellipsis group per line")
            encoded.extend([0xD5] * expected_ellipsis_codes)
            found_ellipsis_group = True
            index += 2
            continue
        if character in NATIVE_INPUT_CODES:
            encoded.append(NATIVE_INPUT_CODES[character])
        else:
            code = code_by_character.get(character)
            if code is None:
                raise ValueError(f"no glyph input code for {character!r}")
            encoded.append(code)
        index += 1

    if found_ellipsis_group != (expected_ellipsis_groups > 0):
        raise ValueError("translation ellipsis groups do not match the expected line layout")
    if (expected_ellipsis_codes > 0) != found_ellipsis_group:
        raise ValueError("opening ellipsis code count does not match the line layout")
    return bytes(encoded)


def encode_opening_payload(text: str, original_payload: bytes, code_by_character: dict[str, int]) -> bytes:
    if len(original_payload) != SOURCE_PAYLOAD_SIZE:
        raise ValueError(f"original opening payload must contain {SOURCE_PAYLOAD_SIZE} bytes")
    if original_payload[0] != 0x3B:
        raise ValueError("original opening payload does not start with native quote 0x3B")
    if original_payload[CLOSING_QUOTE_OFFSET] != 0x3C:
        raise ValueError("original opening payload does not end its text with native quote 0x3C")
    if original_payload[TAIL_START_OFFSET:] != bytes([0x7D, 0x7D, 0x7D, TERMINATOR_CODE]):
        raise ValueError("original scroll tail controls or terminator changed")
    if tuple(index for index, byte in enumerate(original_payload) if byte == 0x7D) != (
        *LINE_ADVANCE_OFFSETS,
        0x57,
        0x58,
        0x59,
    ):
        raise ValueError("original line-advance positions changed")
    if tuple(index for index, byte in enumerate(original_payload) if byte == 0xD5) != (
        *ORIGINAL_ELLIPSIS_OFFSETS,
    ):
        raise ValueError("original ellipsis token positions changed")
    if CLOSING_QUOTE_OFFSET != TERMINATOR_OFFSET - 4:
        raise ValueError("opening text quote and terminator layout is inconsistent")

    lines = text.split("\n")
    if len(lines) != 5:
        raise ValueError("opening translation must contain exactly five lines")
    starts = [0] + [offset + 1 for offset in LINE_ADVANCE_OFFSETS]
    ends = list(LINE_ADVANCE_OFFSETS) + [CLOSING_QUOTE_OFFSET]
    capacities = [end - start for start, end in zip(starts, ends)]

    output = bytearray()
    for index, line in enumerate(lines):
        if index < len(lines) - 1:
            encoded = encode_translation_line(
                line,
                code_by_character,
                ELLIPSIS_GROUPS_PER_LINE[index],
                ELLIPSIS_CODES_PER_LINE[index],
            )
            if len(encoded) > capacities[index]:
                raise ValueError(
                    f"translated line {index + 1} needs {len(encoded)} bytes, "
                    f"source span has {capacities[index]}"
                )
            output.extend(encoded)
            output.extend([SPACE_CODE] * (capacities[index] - len(encoded)))
            output.append(LINE_ADVANCE_CODE)
            continue

        if not line.endswith("」"):
            raise ValueError("the final opening-text line must retain its closing quote")
        encoded = encode_translation_line(
            line[:-1],
            code_by_character,
            ELLIPSIS_GROUPS_PER_LINE[index],
            ELLIPSIS_CODES_PER_LINE[index],
        )
        quote_code = NATIVE_INPUT_CODES["」"]
        if len(encoded) > capacities[index]:
            raise ValueError(
                f"translated final line needs {len(encoded)} bytes, "
                f"source span has {capacities[index]}"
            )
        output.extend(encoded)
        output.append(quote_code)
        output.extend([SPACE_CODE] * (capacities[index] - len(encoded)))

    output.extend(original_payload[TAIL_START_OFFSET:])
    if len(output) != SOURCE_PAYLOAD_SIZE:
        raise ValueError("translated opening payload does not preserve the original byte span")
    if tuple(index for index, byte in enumerate(output) if byte == 0x7D) != (
        *LINE_ADVANCE_OFFSETS,
        0x57,
        0x58,
        0x59,
    ):
        raise ValueError("translated line advances do not preserve the original positions")
    if output[-4:] != original_payload[-4:]:
        raise ValueError("original scroll tail controls and terminator were not preserved")
    if output.count(0xD5) != sum(ELLIPSIS_CODES_PER_LINE):
        raise ValueError("translated opening text does not preserve its native ellipsis tokens")
    return bytes(output)


def build_loader(glyphs: list[CachedGlyph], pattern_cpu_address: int) -> bytes:
    if not glyphs:
        raise ValueError("at least one glyph is required")
    code = bytearray.fromhex("C5 D5 E5")
    for index, glyph in enumerate(glyphs):
        code.extend(
            build_copy_code(
                pattern_cpu_address + index * 16,
                tile_vram_address(glyph.tile),
            )
        )
    code.extend(
        bytes((0x3E, glyphs[0].tile))
        + bytes.fromhex("EA F2 C4 E1 D1 C1 06 CD C9")
    )
    return bytes(code)


def build_opening_entry_code() -> bytes:
    entry_code = bytearray(ENTRY_CODE)
    if (entry_code[5], entry_code[12], entry_code[19]) != (0x0C, 0x0E, 0x34):
        raise ValueError("shared text-loader entry code changed; opening gates need review")
    entry_code[5] = OPENING_BANK
    entry_code[12] = OPENING_POINTER_HIGH
    entry_code[19] = OPENING_LOAD_CURSOR

    marker_guard = bytearray.fromhex("FA F2 C4 B7 20 00 C3 E0 00")
    marker_branch_next = ENTRY_OFFSET + 22 + 6
    marker_displacement = BANK_RESTORE_STUB_OFFSET - marker_branch_next
    if not -128 <= marker_displacement <= 127:
        raise ValueError("opening marker guard exceeds the signed relative-jump range")
    marker_guard[5] = marker_displacement & 0xFF
    entry_code = entry_code[:22] + marker_guard
    if len(entry_code) > ENTRY_AREA_SIZE:
        raise ValueError("opening entry code exceeds its reserved area")
    return bytes(entry_code)


def build_rom_restore_bank_helper(
    glyphs: list[CachedGlyph],
    original_patterns_cpu_address: int,
    restore_cursor_value: int,
    helper_cpu_address: int,
) -> bytes:
    if not glyphs:
        raise ValueError("at least one glyph is required for restoration")
    code = bytearray.fromhex("C5 D5 F5 FA F2 C4 FE")
    code.append(glyphs[0].tile)
    code.extend(bytes.fromhex("C2 00 00 FA AD FF FE"))
    code.append(restore_cursor_value)
    code.extend(bytes.fromhex("C2 00 00"))
    branch_offsets = (9, 17)
    for index, glyph in enumerate(glyphs):
        code.extend(
            build_copy_code(
                original_patterns_cpu_address + index * 16,
                tile_vram_address(glyph.tile),
            )
        )
    code.extend(bytes.fromhex("AF EA F2 C4"))
    common_offset = len(code)
    code.extend(bytes.fromhex("F1 D1 C1 C9"))
    target = helper_cpu_address + common_offset
    if target > 0xFFFF:
        raise ValueError("restore helper return target exceeds the 16-bit address range")
    for operand_offset in branch_offsets:
        code[operand_offset:operand_offset + 2] = bytes(
            (target & 0xFF, target >> 8)
        )
    return bytes(code)


def build_opening_restore_helper(restore_cpu_address: int) -> bytes:
    if not 0 <= restore_cpu_address <= 0xFFFF:
        raise ValueError("opening restore helper address must fit in 16 bits")
    return (
        bytes.fromhex("F5 FA AA FF F5 F3 3E 10 EA 00 20")
        + bytes((0xCD, restore_cpu_address & 0xFF, restore_cpu_address >> 8))
        + bytes.fromhex("F1 EA 00 20 FB F1 21 03 00 C9")
    )


def build_opening_mbc1_layout(base_target: bytes, source_rom: bytes) -> bytes:
    if len(base_target) != BASE_EXPANDED_SIZE:
        raise ValueError(f"base target must be exactly {BASE_EXPANDED_SIZE} bytes")
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")

    expanded = bytearray([0xFF]) * MENU_EXPANDED_SIZE
    expanded[:len(base_target)] = base_target
    expanded[0x148] = MENU_ROM_SIZE_CODE
    expanded[
        MBC1_MIRROR_OFFSET:MBC1_MIRROR_OFFSET + SOURCE_SIZE
    ] = expanded[:SOURCE_SIZE]
    expanded[
        MBC1_MIRROR_OFFSET + 0x0134:
        MBC1_MIRROR_OFFSET + 0x0150
    ] = source_rom[0x0134:0x0150]
    expanded[
        MENU_EXTENSION_ALIAS_OFFSET:
        MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE
    ] = expanded[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]
    return bytes(expanded)


def build_opening_text_target(
    source_rom: bytes,
    manifest: Any,
    opening_glyph_asset: Any,
    shared_glyph_asset: Any,
    tile_candidate: Any,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    source_hash = hashlib.sha256(source_rom).hexdigest()
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"source ROM SHA-256 mismatch: found {source_hash}")
    if not verify_rom(source_rom).passed:
        raise ValueError("source ROM failed size or checksum verification")

    text = get_confirmed_translation(manifest)
    glyphs, code_by_character = create_glyph_mapping(
        text,
        (shared_glyph_asset, opening_glyph_asset),
        tile_candidate,
    )
    if len(glyphs) != 43:
        raise ValueError(f"opening preview requires 43 custom glyphs, found {len(glyphs)}")

    original_payload = source_rom[SOURCE_OFFSET:SOURCE_END]
    encoded_payload = encode_opening_payload(text, original_payload, code_by_character)
    decoded_font = decode_resource(
        source_rom,
        FONT_BANK,
        FONT_DESCRIPTOR,
        FONT_LENGTH,
    )
    if len(decoded_font) != FONT_LENGTH:
        raise ValueError("decoded original font has an unexpected length")
    original_patterns = [
        decoded_font[(glyph.tile - 0x80) * 16:(glyph.tile - 0x80) * 16 + 16]
        for glyph in glyphs
    ]
    if any(len(pattern) != 16 for pattern in original_patterns):
        raise ValueError("an original tile pattern is missing")

    loader_offset = BANK_SWITCH_HELPER_OFFSET
    preliminary_loader = build_loader(glyphs, 0x4100)
    pattern_offset = align_up(loader_offset + len(preliminary_loader), PATTERN_ALIGNMENT)
    pattern_cpu_address = ROM_BANK_WINDOW_CPU_START + pattern_offset - SOURCE_SIZE
    loader = build_loader(glyphs, pattern_cpu_address)
    pattern_end = pattern_offset + len(glyphs) * 16
    original_patterns_offset = align_up(pattern_end, PATTERN_ALIGNMENT)
    original_patterns_end = original_patterns_offset + len(glyphs) * 16
    original_patterns_cpu_address = (
        ROM_BANK_WINDOW_CPU_START + original_patterns_offset - SOURCE_SIZE
    )
    restore_offset = align_up(original_patterns_end, 0x10)
    restore_cpu_address = ROM_BANK_WINDOW_CPU_START + restore_offset - SOURCE_SIZE
    restore_bank_helper = build_rom_restore_bank_helper(
        glyphs,
        original_patterns_cpu_address,
        RESTORE_CURSOR_VALUE,
        restore_cpu_address,
    )
    if loader_offset + len(loader) > pattern_offset:
        raise ValueError("opening loader overlaps its glyph patterns")
    if pattern_end > original_patterns_offset:
        raise ValueError("opening glyph patterns overlap original tile backups")
    if original_patterns_end > restore_offset:
        raise ValueError("original tile backups overlap the restore helper")
    if restore_offset + len(restore_bank_helper) > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("opening cache helpers exceed the bank-10 ROM window")
    if restore_cpu_address + len(restore_bank_helper) > 0x8000:
        raise ValueError("opening restore helper exceeds the bank-10 CPU window")

    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("tile restore hook bytes do not match the expected source")
    restore_helper_template = build_opening_restore_helper(0x4100)
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_helper_template)
    ] != bytes([0xFF]) * len(restore_helper_template):
        raise ValueError("tile restore helper area is not entirely unused")

    if POSTLUDE_OFFSET + len(OPENING_POSTLUDE_CODE) > BANK_RESTORE_STUB_OFFSET:
        raise ValueError("opening postlude overlaps the gateway miss handler")
    entry_code = build_opening_entry_code()
    restore_helper = build_opening_restore_helper(restore_cpu_address)

    target = bytearray(build_expansion_probe(source_rom))
    expected_loader_area = bytearray([0xFF]) * len(loader)
    expected_loader_area[:len(BANK_SWITCH_HELPER)] = BANK_SWITCH_HELPER
    marker_relative = BANK_SWITCH_MARKER_OFFSET - loader_offset
    if 0 <= marker_relative < len(expected_loader_area):
        expected_loader_area[marker_relative] = BANK_SWITCH_MARKER
    if target[loader_offset:loader_offset + len(loader)] != expected_loader_area:
        raise ValueError("bank-10 loader area is not in its expected unused state")
    if target[pattern_offset:pattern_end] != bytes([0xFF]) * (pattern_end - pattern_offset):
        raise ValueError("bank-10 glyph pattern area is not unused")
    if target[
        original_patterns_offset:original_patterns_end
    ] != bytes([0xFF]) * (original_patterns_end - original_patterns_offset):
        raise ValueError("bank-10 original-pattern backup area is not unused")
    if target[
        restore_offset:restore_offset + len(restore_bank_helper)
    ] != bytes([0xFF]) * len(restore_bank_helper):
        raise ValueError("bank-10 restore-helper area is not unused")
    if target[
        BANK_RESTORE_STUB_OFFSET:
        BANK_RESTORE_STUB_OFFSET + len(BANK_RESTORE_STUB)
    ] != BANK_RESTORE_STUB:
        raise ValueError("gateway miss handler area does not match the expansion probe")

    target[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = bytes([0xFF]) * ENTRY_AREA_SIZE
    target[ENTRY_OFFSET:ENTRY_OFFSET + len(entry_code)] = entry_code
    target[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = bytes(
        [0xFF]
    ) * POSTLUDE_AREA_SIZE
    target[
        POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(OPENING_POSTLUDE_CODE)
    ] = OPENING_POSTLUDE_CODE
    target[
        BANK_RESTORE_STUB_OFFSET:
        BANK_RESTORE_STUB_OFFSET + len(OPENING_GATE_MISS_CODE)
    ] = OPENING_GATE_MISS_CODE
    target[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)] = (
        RESTORE_HOOK_PATCH
    )
    target[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_helper)] = (
        restore_helper
    )
    target[loader_offset:loader_offset + len(loader)] = loader
    for index, glyph in enumerate(glyphs):
        start = pattern_offset + index * 16
        target[start:start + 16] = glyph.pattern
        original_start = original_patterns_offset + index * 16
        target[original_start:original_start + 16] = original_patterns[index]
    target[restore_offset:restore_offset + len(restore_bank_helper)] = restore_bank_helper
    target[SOURCE_OFFSET:SOURCE_END] = encoded_payload

    expanded_target = build_opening_mbc1_layout(bytes(target), source_rom)
    result = update_checksums(expanded_target)
    if len(result) != MENU_EXPANDED_SIZE or not verify_rom(result).passed:
        raise ValueError("opening text preview target failed ROM size or checksum verification")
    if result[SOURCE_OFFSET:SOURCE_END] != encoded_payload:
        raise ValueError("opening text payload differs from the generated target")
    return result


def build_patch_file(
    source_path: Path,
    manifest_path: Path,
    opening_glyph_asset_path: Path,
    shared_glyph_asset_path: Path,
    tile_candidate_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, int, str, str]:
    source = source_path.resolve(strict=True)
    inputs = {
        manifest_path.resolve(strict=True),
        opening_glyph_asset_path.resolve(strict=True),
        shared_glyph_asset_path.resolve(strict=True),
        tile_candidate_path.resolve(strict=True),
    }
    output = output_path.resolve()
    if output == source or output in inputs:
        raise ValueError("BPS output path must differ from every input")
    if not output.parent.is_dir():
        raise ValueError(f"BPS output directory does not exist: {output.parent}")
    if output.exists() and not overwrite:
        raise FileExistsError(
            f"BPS output already exists: {output}; pass --overwrite to replace it"
        )

    source_rom = source.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    opening_glyph_asset = json.loads(
        opening_glyph_asset_path.read_text(encoding="utf-8")
    )
    shared_glyph_asset = json.loads(shared_glyph_asset_path.read_text(encoding="utf-8"))
    tile_candidate = json.loads(tile_candidate_path.read_text(encoding="utf-8"))
    target_rom = build_opening_text_target(
        source_rom,
        manifest,
        opening_glyph_asset,
        shared_glyph_asset,
        tile_candidate,
    )
    patch = create_bps_patch(source_rom, target_rom, OPENING_TARGET_COPY_SPANS)
    if apply_bps_patch(source_rom, patch) != target_rom:
        raise ValueError("BPS round-trip did not reproduce the preview target")
    write_output(output, patch, overwrite)
    if output.read_bytes() != patch:
        raise OSError(f"written BPS patch differs from generated patch: {output}")
    return (
        output,
        len(patch),
        hashlib.sha256(patch).hexdigest(),
        hashlib.sha256(target_rom).hexdigest(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a BPS-only preview patch for the confirmed opening scroll."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
        help="verified original ROM (default: roms/oni5_original.gb)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "text_manifest.json",
        help="confirmed text manifest",
    )
    parser.add_argument(
        "--glyph-asset",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs_oni5_bank04_01330d.json",
        help="new opening-text glyphs",
    )
    parser.add_argument(
        "--shared-glyph-asset",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs.json",
        help="existing glyphs reused by the opening text",
    )
    parser.add_argument(
        "--tile-candidate",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_candidate.json",
        help="audited context-eligible tile pool",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "roms" / "oni5_opening_preview.bps",
        help="BPS patch output (default: roms/oni5_opening_preview.bps)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing BPS patch",
    )
    args = parser.parse_args()

    try:
        output, size, patch_hash, target_hash = build_patch_file(
            args.source,
            args.manifest,
            args.glyph_asset,
            args.shared_glyph_asset,
            args.tile_candidate,
            args.output,
            args.overwrite,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    print(f"Wrote BPS patch {output} ({size} bytes)")
    print(f"BPS SHA-256: {patch_hash}")
    print(f"Preview target SHA-256: {target_hash}")


if __name__ == "__main__":
    main()
