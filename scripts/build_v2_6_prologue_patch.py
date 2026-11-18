"""Build the V2.6.1 opening-dialogue ROM and its V2.6-based BPS patch."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .apply_bps_patch import apply_bps_patch, create_bps_patch
    from .build_mbc1_expansion_probe import SOURCE_SIZE
    from .build_menu_pilot import (
        MBC1_MIRROR_OFFSET,
        MENU_EXPANDED_SIZE,
        MENU_EXTENSION_ALIAS_OFFSET,
        MENU_ROM_SIZE_CODE,
        ROM_BANK_SIZE,
    )
    from .build_noticeboard_glyph_probe import TILE_PATTERN_SIZE
    from .build_opening_text_preview_patch import (
        D5_NATIVE_EXPANSION_TILE,
        FONT_BANK,
        FONT_DESCRIPTOR,
        FONT_LENGTH,
        create_glyph_mapping,
    )
    from .build_rom import write_output
    from .build_text_comparison_pilot import (
        PilotContext,
        build_load_dispatcher,
        build_loader_helper,
        build_restore_dispatcher,
        build_restore_helper,
        bank_cpu_address,
    )
    from .decode_gb_resource import decode_resource
    from .rom_checksums import update_checksums, verify_rom
else:
    from apply_bps_patch import apply_bps_patch, create_bps_patch
    from build_mbc1_expansion_probe import SOURCE_SIZE
    from build_menu_pilot import (
        MBC1_MIRROR_OFFSET,
        MENU_EXPANDED_SIZE,
        MENU_EXTENSION_ALIAS_OFFSET,
        MENU_ROM_SIZE_CODE,
        ROM_BANK_SIZE,
    )
    from build_noticeboard_glyph_probe import TILE_PATTERN_SIZE
    from build_opening_text_preview_patch import (
        D5_NATIVE_EXPANSION_TILE,
        FONT_BANK,
        FONT_DESCRIPTOR,
        FONT_LENGTH,
        create_glyph_mapping,
    )
    from build_rom import write_output
    from build_text_comparison_pilot import (
        PilotContext,
        build_load_dispatcher,
        build_loader_helper,
        build_restore_dispatcher,
        build_restore_helper,
        bank_cpu_address,
    )
    from decode_gb_resource import decode_resource
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_V2_5_SHA256 = "a39eb8b30942f37f657bda03c806abf761d6cbbbc5d99b0697544dc25b03170f"
EXPECTED_V2_6_SHA256 = "ce310f3886743d19fc428aa8d515b29aafa513e6462814235c4e368744a7c94c"
EXPECTED_V2_6_PATCH_SHA256 = "97258dba513628e593a52bc4d3af2e11b313ffcbf1cafd6e55365869ec74a675"
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
V2_6_PATCH_PATH = ROOT / "roms" / "oni5_v2_6_opening_prologue.bps"
V2_6_ROM_OUTPUT = ROOT / "roms" / "oni5_v2_6_opening_prologue.gb"

PROLOGUE_RECORD_IDS = (
    "oni5-bank04-inline-013396",
    "oni5-bank04-inline-0133d7",
)
FIRST_EVENT_OFFSET = 0x013395
FIRST_EVENT_END = 0x0133D4
THIRD_EVENT_OFFSET = 0x0133D6
THIRD_EVENT_END = 0x0133E9
FIRST_TEXT_SPAN = (0x013396, 0x0133C8)
STUDENT_TEXT_SPAN = (0x0133CA, 0x0133D3)
THIRD_TEXT_SPAN = (0x0133D8, 0x0133E8)
NEXT_DIALOGUE_RECORD_ID = "oni5-bank04-inline-013459"
NEXT_DIALOGUE_SPAN = (0x013459, 0x01346D)
NEXT_DIALOGUE_EVENT_OFFSET = 0x013457
NEXT_DIALOGUE_EVENT_END = 0x01347C
ADDITIONAL_DIALOGUE_RECORD_ID = "oni5-bank04-inline-0133ef"
ADDITIONAL_DIALOGUE_SPAN = (0x0133EF, 0x013408)
ADDITIONAL_DIALOGUE_EVENT_OFFSET = 0x0133EE
ADDITIONAL_DIALOGUE_EVENT_END = 0x013409
ADDITIONAL_DIALOGUE_EVENT_BYTES = bytes.fromhex(
    "57 95 7D 3B 25 0C 4D AB 07 0B 35 1A 0A 6A 21 0E 0A "
    "7D 4D 15 64 0A 1D 4D AD 3C 7F"
)
PRACTICE_DIALOGUE_RECORD_ID = "oni5-bank24-01348c"
PRACTICE_DIALOGUE_SPAN = (0x01348F, 0x0134AA)
PRACTICE_DIALOGUE_EVENT_OFFSET = 0x01348B
PRACTICE_DIALOGUE_EVENT_END = 0x0134AB
PRACTICE_DIALOGUE_EVENT_BYTES = bytes.fromhex(
    "57 7C AD 7D 3B 0F 07 4D 0F 07 0B 21 11 0A 12 22 4D 12 "
    "32 6D 7D 4D 0D 14 27 0A 1E 14 27 15 3C 7E"
)
LATER_DIALOGUE_RECORD_ID = "oni5-bank24-01353f"
LATER_DIALOGUE_SPAN = (0x013545, 0x013552)
LATER_DIALOGUE_EVENT_OFFSET = 0x01353E
LATER_DIALOGUE_EVENT_END = 0x013553
LATER_DIALOGUE_EVENT_BYTES = bytes.fromhex(
    "57 80 7D 3B CC 7E 7C 95 7D 3B 1D 4D B7 4D 12 21 0E "
    "36 66 CC 7F"
)
FIRST_EVENT_BYTES = bytes.fromhex(
    "57 AD 7D 3B D5 1C 4D 0A 0B 2E 0B 1E 4D 11 36 21 "
    "28 19 1E 22 7D 4D 16 0A 14 36 21 18 36 32 36 60 "
    "4D 18 0A 16 1A 1D 21 7D 4D 6D 15 4D 34 0E 30 27 "
    "15 20 3C 7E 7C 16 0A 1C 7D 3B 22 37 0A D0 7F"
)
THIRD_EVENT_BYTES = bytes.fromhex(
    "57 7C AD 7D 3B 2E 33 14 0A 4D 6D 22 1A 61 1E D5 D5 3C 7F"
)
NEXT_DIALOGUE_EVENT_BYTES = bytes.fromhex(
    "57 7C 95 7D 3B 0F 06 0B 1E 4D 0E 0D 60 28 18 10 1D 08 "
    "18 36 6A 3C 7E 7C AD 7D 3B 95 08 18 2F D5 D5 22 08 3C 7F"
)

PROLOGUE_MARKER = 0x87
NEXT_DIALOGUE_MARKER = 0x86
ADDITIONAL_DIALOGUE_MARKER = 0x85
PRACTICE_DIALOGUE_MARKER = 0x84
LATER_DIALOGUE_MARKER = 0x83
PROLOGUE_LOAD_FIRST_CURSOR = 0x96
PROLOGUE_RESTORE_CURSOR = 0xE9
NEXT_DIALOGUE_LOAD_FIRST_CURSOR = 0x59
NEXT_DIALOGUE_RESTORE_CURSOR = 0x7C
ADDITIONAL_DIALOGUE_LOAD_CURSOR = 0xF0
ADDITIONAL_DIALOGUE_RESTORE_CURSOR = 0x09
PRACTICE_DIALOGUE_LOAD_CURSOR = 0x90
PRACTICE_DIALOGUE_RESTORE_CURSOR = 0xAB
LATER_DIALOGUE_LOAD_CURSOR = 0x46
LATER_DIALOGUE_RESTORE_CURSOR = 0x53
SHIZUNA_MACRO_TOKEN = "{静那}"
PUNCTUATION_MACRO_TOKEN = "！？」"
ADDITIONAL_DIALOGUE_MACROS = {
    SHIZUNA_MACRO_TOKEN: (0xAD, 3),
}
LATER_DIALOGUE_MACROS = {
    PUNCTUATION_MACRO_TOKEN: (0xCC, 3),
}
PROTAGONIST_NATIVE_TILES = frozenset({0x94, 0x95, 0x9D})
NATIVE_QUOTE_TILES = frozenset({0xBB, 0xBC})
NATIVE_END_PUNCTUATION_TILES = frozenset({0xCA, 0xCB, 0xBC})
NEXT_DIALOGUE_NATIVE_TILES = frozenset(
    {0x88, 0x8F, 0x98, 0x9C, 0xA2, 0xA7, 0xAF, 0xB1, 0xB4}
)
MAX_DIALOGUE_LINE_WIDTH = 18
RESERVED_TILE_IDS = frozenset(
    {
        0x80,
        0x85,
        PROLOGUE_MARKER,
        0x94,
        0xA5,
        D5_NATIVE_EXPANSION_TILE,
    }
)

LEGACY_ENTRY_OFFSET = SOURCE_SIZE + 0x0004
LEGACY_ENTRY_END = SOURCE_SIZE + 0x0030
LEGACY_ENTRY_COPY_OFFSET = SOURCE_SIZE + 0x0080
NEW_LOAD_GATE_OFFSET = SOURCE_SIZE + 0x0100
LOAD_DISPATCHER_OFFSET = SOURCE_SIZE + 0x0200
RESTORE_WRAPPER_OFFSET = SOURCE_SIZE + 0x0060
RESTORE_ROUTER_CALL_OFFSET = SOURCE_SIZE + 0x2567
RESTORE_ROUTER_CALL_EXPECTED = bytes.fromhex("CD B0 48")
PROLOGUE_BANK10_START = SOURCE_SIZE + 0x2900
PROLOGUE_BANK10_END = SOURCE_SIZE + 0x4000

V2_5_INPUT_FILES = (
    "text_manifest.json",
    "chinese_glyphs_oni5_bank04_prologue_v26.json",
    "tile_cache_plan_candidate.json",
    "chinese_glyphs_oni5_bank04_prologue_v261.json",
    "chinese_glyphs_oni5_bank24_01348f.json",
    "chinese_glyphs_oni5_v261_remaining_dialogues.json",
)


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _parse_hex_offset(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.lower().startswith("0x"):
        raise ValueError(f"{field} must be a hexadecimal string")
    try:
        return int(value[2:], 16)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid hexadecimal") from exc


def _find_record(manifest: Any, record_id: str) -> dict[str, Any]:
    root = _require_object(manifest, "text manifest")
    records = root.get("records")
    if not isinstance(records, list):
        raise ValueError("text manifest.records must be a list")
    matches = [
        _require_object(record, f"text manifest.records[{index}]")
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get("id") == record_id
    ]
    if len(matches) != 1:
        raise ValueError(f"text manifest must contain exactly one {record_id!r} record")
    return matches[0]


def _translation_text(
    record: dict[str, Any],
    start: int,
    end_exclusive: int,
) -> str:
    translation = _require_object(record.get("translation"), "record.translation")
    if translation.get("status") != "confirmed":
        raise ValueError(f"{record.get('id')} translation must be confirmed")
    segments = translation.get("segments")
    if not isinstance(segments, list):
        raise ValueError(f"{record.get('id')}.translation.segments must be a list")
    matches = []
    for index, value in enumerate(segments):
        segment = _require_object(
            value,
            f"{record.get('id')}.translation.segments[{index}]",
        )
        segment_start = _parse_hex_offset(
            segment.get("source_start"),
            f"{record.get('id')}.translation.segments[{index}].source_start",
        )
        segment_end = _parse_hex_offset(
            segment.get("source_end_exclusive"),
            f"{record.get('id')}.translation.segments[{index}].source_end_exclusive",
        )
        if segment_start == start and segment_end == end_exclusive:
            matches.append(segment.get("text"))
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise ValueError(
            f"{record.get('id')} must contain exactly one translation for "
            f"0x{start:X}-0x{end_exclusive:X}"
        )
    return matches[0]


def _parse_tile_id(value: Any, field: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        tile = value
    elif isinstance(value, str):
        try:
            tile = int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError as exc:
            raise ValueError(f"{field} is not a valid tile ID") from exc
    else:
        raise ValueError(f"{field} must be a tile ID")
    if not 0 <= tile <= 0xFF:
        raise ValueError(f"{field} must fit in one byte")
    return tile


def _candidate_without_reserved_tiles(tile_candidate: Any) -> dict[str, Any]:
    candidate = copy.deepcopy(_require_object(tile_candidate, "tile cache candidate"))
    pool = _require_object(candidate.get("tile_pool"), "tile cache candidate.tile_pool")
    start = _parse_tile_id(pool.get("start"), "tile pool start")
    end = _parse_tile_id(pool.get("end_exclusive"), "tile pool end_exclusive")
    if end <= start:
        raise ValueError("tile pool end_exclusive must follow start")
    excluded = pool.get("excluded_non_text_map_ids")
    reserved = pool.get("reserved_native_tile_ids")
    if not isinstance(excluded, list) or not isinstance(reserved, list):
        raise ValueError("tile pool must list excluded and reserved tile IDs")
    reserved_set = {
        _parse_tile_id(value, "excluded tile ID")
        for value in excluded
    } | {
        _parse_tile_id(value, "reserved tile ID")
        for value in reserved
    } | RESERVED_TILE_IDS
    pool["reserved_native_tile_ids"] = [
        f"0x{tile:02X}" for tile in sorted(reserved_set)
    ]
    pool["eligible_count"] = sum(
        tile not in reserved_set
        for tile in range(start, end)
    )
    return candidate


def _candidate_avoiding_next_japanese_text(tile_candidate: Any) -> dict[str, Any]:
    candidate = _candidate_without_reserved_tiles(tile_candidate)
    pool = _require_object(candidate.get("tile_pool"), "tile candidate.tile_pool")
    excluded = set(pool["excluded_non_text_map_ids"])
    excluded.update(f"0x{tile:02X}" for tile in NEXT_DIALOGUE_NATIVE_TILES)
    pool["excluded_non_text_map_ids"] = sorted(excluded)
    start = _parse_tile_id(pool.get("start"), "tile pool start")
    end = _parse_tile_id(pool.get("end_exclusive"), "tile pool end_exclusive")
    reserved = {
        _parse_tile_id(value, "tile ID")
        for value in pool["excluded_non_text_map_ids"] + pool["reserved_native_tile_ids"]
    }
    pool["eligible_count"] = sum(tile not in reserved for tile in range(start, end))
    return candidate


def _candidate_excluding_tiles(
    tile_candidate: Any,
    excluded_tiles: frozenset[int],
) -> dict[str, Any]:
    candidate = _candidate_without_reserved_tiles(tile_candidate)
    pool = _require_object(candidate.get("tile_pool"), "tile candidate.tile_pool")
    excluded = set(pool["excluded_non_text_map_ids"])
    excluded.update(f"0x{tile:02X}" for tile in excluded_tiles)
    pool["excluded_non_text_map_ids"] = sorted(excluded)
    start = _parse_tile_id(pool.get("start"), "tile pool start")
    end = _parse_tile_id(pool.get("end_exclusive"), "tile pool end_exclusive")
    reserved = {
        _parse_tile_id(value, "tile ID")
        for value in pool["excluded_non_text_map_ids"] + pool["reserved_native_tile_ids"]
    }
    pool["eligible_count"] = sum(tile not in reserved for tile in range(start, end))
    return candidate


def _without_macro_tokens(
    text: str,
    macro_tokens: dict[str, tuple[int, int]],
) -> str:
    for token in macro_tokens:
        text = text.replace(token, "")
    return text


def _encode_line(
    line: str,
    code_by_character: dict[str, int],
    expected_ellipsis_codes: int,
    macro_tokens: dict[str, tuple[int, int]] | None = None,
) -> tuple[bytes, int]:
    native_codes = {
        "「": 0x3B,
        "」": 0x3C,
        "！": 0x4B,
        "？": 0x4A,
        "。": 0x3E,
    }
    encoded = bytearray()
    visual_width = 0
    ellipsis_groups = 0
    index = 0
    tokens = sorted((macro_tokens or {}).items(), key=lambda item: len(item[0]), reverse=True)
    while index < len(line):
        matched_macro = next(
            (
                (token, code, width)
                for token, (code, width) in tokens
                if line.startswith(token, index)
            ),
            None,
        )
        if matched_macro is not None:
            token, code, width = matched_macro
            encoded.append(code)
            visual_width += width
            index += len(token)
            continue
        character = line[index]
        if character == "…":
            if line[index:index + 2] != "……" or ellipsis_groups:
                raise ValueError("prologue translations need one paired ellipsis per line")
            if expected_ellipsis_codes < 1:
                raise ValueError("translation ellipsis does not match the source layout")
            encoded.extend([0xD5] * expected_ellipsis_codes)
            visual_width += expected_ellipsis_codes * 2
            ellipsis_groups += 1
            index += 2
            continue
        if character == " ":
            encoded.append(0x4D)
            visual_width += 1
        elif character in native_codes:
            encoded.append(native_codes[character])
            visual_width += 1
        else:
            code = code_by_character.get(character)
            if code is None:
                raise ValueError(f"no prologue glyph input code for {character!r}")
            encoded.append(code)
            visual_width += 1
        index += 1
    if (expected_ellipsis_codes > 0) != (ellipsis_groups == 1):
        raise ValueError("translation ellipsis count does not match the source layout")
    return bytes(encoded), visual_width


def encode_translation_span(
    text: str,
    code_by_character: dict[str, int],
    span_size: int,
    expected_ellipsis_codes: int,
    macro_tokens: dict[str, tuple[int, int]] | None = None,
) -> bytes:
    lines = text.split("\n")
    if len(lines) < 1 or any(not line for line in lines):
        raise ValueError("prologue translations may not contain empty lines")
    ellipsis_lines = [index for index, line in enumerate(lines) if "…" in line]
    if len(ellipsis_lines) != (1 if expected_ellipsis_codes else 0):
        raise ValueError("translation ellipsis groups do not match the source layout")
    encoded_lines: list[bytearray] = []
    widths: list[int] = []
    for index, line in enumerate(lines):
        line_ellipsis_codes = (
            expected_ellipsis_codes
            if index in ellipsis_lines
            else 0
        )
        encoded, width = _encode_line(
            line,
            code_by_character,
            line_ellipsis_codes,
            macro_tokens,
        )
        encoded_lines.append(bytearray(encoded))
        widths.append(width)

    required_size = sum(len(line) for line in encoded_lines) + len(lines) - 1
    padding = span_size - required_size
    if padding < 0:
        raise ValueError(
            f"translation needs {required_size} bytes, source span has {span_size}"
        )
    for index in range(len(lines) - 1, -1, -1):
        available = MAX_DIALOGUE_LINE_WIDTH - widths[index]
        if available < 0:
            raise ValueError(
                f"translated line {index + 1} is {widths[index]} tiles wide; "
                f"maximum is {MAX_DIALOGUE_LINE_WIDTH}"
            )
        amount = min(padding, available)
        encoded_lines[index].extend([0x4D] * amount)
        widths[index] += amount
        padding -= amount
    if padding:
        raise ValueError(
            f"translation needs {padding} more blank tiles than its lines can hold"
        )

    output = bytearray()
    for index, line in enumerate(encoded_lines):
        output.extend(line)
        if index < len(encoded_lines) - 1:
            output.append(0x7D)
    if len(output) != span_size:
        raise ValueError("encoded translation does not preserve its fixed source span")
    return bytes(output)


def _build_restore_wrapper(dispatcher_cpu_address: int) -> bytes:
    return (
        bytes.fromhex("F5 CD")
        + dispatcher_cpu_address.to_bytes(2, "little")
        + bytes.fromhex("F1 C3 B0 48")
    )


def _build_load_gate(
    dispatcher_cpu_address: int,
    legacy_cpu_address: int,
) -> bytes:
    return (
        bytes.fromhex("CD")
        + dispatcher_cpu_address.to_bytes(2, "little")
        + bytes.fromhex("B7 C0 C3")
        + legacy_cpu_address.to_bytes(2, "little")
    )


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("alignment must be a positive power of two")
    return (value + alignment - 1) & ~(alignment - 1)


def _install_free_component(
    target: bytearray,
    parent_rom: bytes,
    offset: int,
    data: bytes,
    allocation_end: int,
    label: str,
) -> None:
    end = offset + len(data)
    if offset < PROLOGUE_BANK10_START or end > allocation_end:
        raise ValueError(f"{label} exceeds the reserved bank-10 prologue allocation")
    if parent_rom[offset:end] != bytes([0xFF]) * len(data):
        raise ValueError(f"{label} overlaps occupied V2.5 bank-10 bytes")
    target[offset:end] = data


def _require_span(
    rom: bytes | bytearray,
    offset: int,
    expected: bytes,
    label: str,
) -> None:
    if rom[offset:offset + len(expected)] != expected:
        raise ValueError(f"{label} does not match the verified V2.5 layout")


def build_v2_6_rom(
    parent_rom: bytes,
    source_rom: bytes,
    manifest: Any,
    glyph_asset: Any,
    tile_candidate: Any,
    extra_glyph_asset: Any | None = None,
    practice_glyph_asset: Any | None = None,
    additional_dialogue_glyph_asset: Any | None = None,
) -> bytes:
    if len(parent_rom) != MENU_EXPANDED_SIZE:
        raise ValueError(f"V2.5 parent ROM must be exactly {MENU_EXPANDED_SIZE} bytes")
    parent_digest = hashlib.sha256(parent_rom).hexdigest()
    if parent_digest != EXPECTED_V2_5_SHA256:
        raise ValueError(
            f"V2.6 parent ROM must match the runtime-verified V2.5 SHA-256 "
            f"(found {parent_digest})"
        )
    if not verify_rom(parent_rom).passed:
        raise ValueError("V2.5 parent ROM failed checksum verification")
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    source_digest = hashlib.sha256(source_rom).hexdigest()
    if source_digest != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 does not match the verified original")
    if not verify_rom(source_rom).passed:
        raise ValueError("original source ROM failed checksum verification")
    if parent_rom[0x148] != MENU_ROM_SIZE_CODE:
        raise ValueError("V2.5 parent ROM has an unexpected ROM-size code")

    _require_span(
        source_rom,
        FIRST_EVENT_OFFSET,
        FIRST_EVENT_BYTES,
        "first prologue event",
    )
    _require_span(
        source_rom,
        THIRD_EVENT_OFFSET,
        THIRD_EVENT_BYTES,
        "third prologue event",
    )
    _require_span(
        source_rom,
        NEXT_DIALOGUE_EVENT_OFFSET,
        NEXT_DIALOGUE_EVENT_BYTES,
        "next prologue dialogue event",
    )
    for offset, event_bytes, label in (
        (
            ADDITIONAL_DIALOGUE_EVENT_OFFSET,
            ADDITIONAL_DIALOGUE_EVENT_BYTES,
            "additional opening dialogue event",
        ),
        (
            PRACTICE_DIALOGUE_EVENT_OFFSET,
            PRACTICE_DIALOGUE_EVENT_BYTES,
            "practice dialogue event",
        ),
        (
            LATER_DIALOGUE_EVENT_OFFSET,
            LATER_DIALOGUE_EVENT_BYTES,
            "later dialogue event",
        ),
    ):
        _require_span(source_rom, offset, event_bytes, label)
    _require_span(
        parent_rom,
        FIRST_EVENT_OFFSET,
        FIRST_EVENT_BYTES,
        "V2.5 first prologue event",
    )
    _require_span(
        parent_rom,
        MBC1_MIRROR_OFFSET + FIRST_EVENT_OFFSET,
        FIRST_EVENT_BYTES,
        "V2.5 first prologue event mirror",
    )
    _require_span(
        parent_rom,
        THIRD_EVENT_OFFSET,
        THIRD_EVENT_BYTES,
        "V2.5 third prologue event",
    )
    _require_span(
        parent_rom,
        NEXT_DIALOGUE_EVENT_OFFSET,
        NEXT_DIALOGUE_EVENT_BYTES,
        "V2.5 next prologue dialogue event",
    )
    for offset, event_bytes, label in (
        (
            ADDITIONAL_DIALOGUE_EVENT_OFFSET,
            ADDITIONAL_DIALOGUE_EVENT_BYTES,
            "V2.5 additional opening dialogue event",
        ),
        (
            PRACTICE_DIALOGUE_EVENT_OFFSET,
            PRACTICE_DIALOGUE_EVENT_BYTES,
            "V2.5 practice dialogue event",
        ),
        (
            LATER_DIALOGUE_EVENT_OFFSET,
            LATER_DIALOGUE_EVENT_BYTES,
            "V2.5 later dialogue event",
        ),
    ):
        _require_span(parent_rom, offset, event_bytes, label)
    _require_span(
        parent_rom,
        MBC1_MIRROR_OFFSET + THIRD_EVENT_OFFSET,
        THIRD_EVENT_BYTES,
        "V2.5 third prologue event mirror",
    )
    for offset, event_bytes, label in (
        (
            ADDITIONAL_DIALOGUE_EVENT_OFFSET,
            ADDITIONAL_DIALOGUE_EVENT_BYTES,
            "V2.5 additional opening dialogue event mirror",
        ),
        (
            PRACTICE_DIALOGUE_EVENT_OFFSET,
            PRACTICE_DIALOGUE_EVENT_BYTES,
            "V2.5 practice dialogue event mirror",
        ),
        (
            LATER_DIALOGUE_EVENT_OFFSET,
            LATER_DIALOGUE_EVENT_BYTES,
            "V2.5 later dialogue event mirror",
        ),
    ):
        _require_span(
            parent_rom,
            MBC1_MIRROR_OFFSET + offset,
            event_bytes,
            label,
        )

    _require_span(
        parent_rom,
        LEGACY_ENTRY_OFFSET,
        bytes.fromhex(
            "FA F2 C4 B7 20 24 FA AA FF FE 04 20 19 FA AE FF FE 33 "
            "20 12 FA AD FF FE 1D 20 0B CD 00 4B 3E BB EA F0 C4 "
            "3E 01 C9 CD 00 4E C9 AF C9"
        ),
        "V2.5 legacy text loader",
    )
    if LEGACY_ENTRY_END - LEGACY_ENTRY_OFFSET != 0x2C:
        raise ValueError("V2.5 legacy text loader span changed")
    _require_span(
        parent_rom,
        RESTORE_ROUTER_CALL_OFFSET,
        RESTORE_ROUTER_CALL_EXPECTED,
        "V2.5 dialogue restore router call",
    )
    if (
        parent_rom[MENU_EXTENSION_ALIAS_OFFSET:MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE]
        != parent_rom[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]
    ):
        raise ValueError("V2.5 bank-10 extension alias is inconsistent")
    if (
        parent_rom[PROLOGUE_BANK10_START:PROLOGUE_BANK10_END]
        != bytes([0xFF]) * (PROLOGUE_BANK10_END - PROLOGUE_BANK10_START)
    ):
        raise ValueError("V2.5 prologue bank-10 allocation is not entirely free")

    teacher_record = _find_record(manifest, PROLOGUE_RECORD_IDS[0])
    third_record = _find_record(manifest, PROLOGUE_RECORD_IDS[1])
    next_dialogue_record = _find_record(manifest, NEXT_DIALOGUE_RECORD_ID)
    additional_dialogue_record = _find_record(
        manifest,
        ADDITIONAL_DIALOGUE_RECORD_ID,
    )
    practice_dialogue_record = _find_record(
        manifest,
        PRACTICE_DIALOGUE_RECORD_ID,
    )
    later_dialogue_record = _find_record(
        manifest,
        LATER_DIALOGUE_RECORD_ID,
    )
    teacher_text = _translation_text(
        teacher_record,
        *FIRST_TEXT_SPAN,
    )
    student_text = _translation_text(
        teacher_record,
        *STUDENT_TEXT_SPAN,
    )
    third_text = _translation_text(
        third_record,
        *THIRD_TEXT_SPAN,
    )
    next_dialogue_text = _translation_text(
        next_dialogue_record,
        *NEXT_DIALOGUE_SPAN,
    )
    additional_dialogue_text = _translation_text(
        additional_dialogue_record,
        *ADDITIONAL_DIALOGUE_SPAN,
    )
    practice_dialogue_text = _translation_text(
        practice_dialogue_record,
        *PRACTICE_DIALOGUE_SPAN,
    )
    later_dialogue_text = _translation_text(
        later_dialogue_record,
        *LATER_DIALOGUE_SPAN,
    )

    filtered_candidate = _candidate_without_reserved_tiles(tile_candidate)
    glyph_source_text = "\n".join((teacher_text, student_text, third_text))
    for native_character in ("！", "？"):
        glyph_source_text = glyph_source_text.replace(native_character, "")
    glyphs, code_by_character = create_glyph_mapping(
        glyph_source_text,
        (glyph_asset,),
        filtered_candidate,
    )
    if any(glyph.tile in RESERVED_TILE_IDS for glyph in glyphs):
        raise ValueError("prologue glyph allocation overlaps a reserved native tile")

    teacher_payload = encode_translation_span(
        teacher_text,
        code_by_character,
        FIRST_TEXT_SPAN[1] - FIRST_TEXT_SPAN[0],
        expected_ellipsis_codes=1,
    )
    student_payload = encode_translation_span(
        student_text,
        code_by_character,
        STUDENT_TEXT_SPAN[1] - STUDENT_TEXT_SPAN[0],
        expected_ellipsis_codes=0,
    )
    third_payload = encode_translation_span(
        third_text,
        code_by_character,
        THIRD_TEXT_SPAN[1] - THIRD_TEXT_SPAN[0],
        expected_ellipsis_codes=2,
    )
    next_glyph_source_text = next_dialogue_text
    for native_character in ("！", "？", "。", "「", "」"):
        next_glyph_source_text = next_glyph_source_text.replace(native_character, "")
    next_candidate = _candidate_avoiding_next_japanese_text(tile_candidate)
    next_glyph_asset = extra_glyph_asset if extra_glyph_asset is not None else glyph_asset
    next_glyphs, next_code_by_character = create_glyph_mapping(
        next_glyph_source_text,
        (next_glyph_asset,),
        next_candidate,
    )
    next_dialogue_payload = encode_translation_span(
        next_dialogue_text,
        next_code_by_character,
        NEXT_DIALOGUE_SPAN[1] - NEXT_DIALOGUE_SPAN[0],
        expected_ellipsis_codes=0,
    )

    additional_candidate = _candidate_excluding_tiles(
        tile_candidate,
        frozenset({ADDITIONAL_DIALOGUE_MARKER}) | PROTAGONIST_NATIVE_TILES,
    )
    additional_macro_free_text = _without_macro_tokens(
        additional_dialogue_text,
        ADDITIONAL_DIALOGUE_MACROS,
    ).replace("\n", "")
    for native_character in ("！", "？", "。", "「", "」"):
        additional_macro_free_text = additional_macro_free_text.replace(
            native_character,
            "",
        )
    additional_glyph_asset = (
        additional_dialogue_glyph_asset
        if additional_dialogue_glyph_asset is not None
        else extra_glyph_asset
    )
    if additional_glyph_asset is None:
        raise ValueError("additional dialogue glyph asset is required")
    additional_glyph_assets = tuple(
        asset
        for asset in (glyph_asset, extra_glyph_asset, additional_glyph_asset)
        if asset is not None
    )
    additional_glyphs, additional_code_by_character = create_glyph_mapping(
        additional_macro_free_text,
        additional_glyph_assets,
        additional_candidate,
    )
    additional_dialogue_payload = encode_translation_span(
        additional_dialogue_text,
        additional_code_by_character,
        ADDITIONAL_DIALOGUE_SPAN[1] - ADDITIONAL_DIALOGUE_SPAN[0],
        expected_ellipsis_codes=0,
        macro_tokens=ADDITIONAL_DIALOGUE_MACROS,
    )

    practice_candidate = _candidate_excluding_tiles(
        tile_candidate,
        frozenset({PRACTICE_DIALOGUE_MARKER}) | NATIVE_QUOTE_TILES,
    )
    practice_glyphs_source = practice_dialogue_text.replace("\n", "")
    for native_character in ("！", "？", "。", "「", "」"):
        practice_glyphs_source = practice_glyphs_source.replace(
            native_character,
            "",
        )
    practice_asset = (
        practice_glyph_asset
        if practice_glyph_asset is not None
        else glyph_asset
    )
    practice_glyphs, practice_code_by_character = create_glyph_mapping(
        practice_glyphs_source,
        tuple(
            asset
            for asset in (practice_asset, additional_dialogue_glyph_asset)
            if asset is not None
        ),
        practice_candidate,
    )
    practice_dialogue_payload = encode_translation_span(
        practice_dialogue_text,
        practice_code_by_character,
        PRACTICE_DIALOGUE_SPAN[1] - PRACTICE_DIALOGUE_SPAN[0],
        expected_ellipsis_codes=0,
    )

    later_candidate = _candidate_excluding_tiles(
        tile_candidate,
        frozenset({LATER_DIALOGUE_MARKER})
        | NATIVE_QUOTE_TILES
        | NATIVE_END_PUNCTUATION_TILES,
    )
    later_macro_free_text = _without_macro_tokens(
        later_dialogue_text,
        LATER_DIALOGUE_MACROS,
    ).replace("\n", "")
    for native_character in ("！", "？", "。", "「", "」"):
        later_macro_free_text = later_macro_free_text.replace(
            native_character,
            "",
        )
    later_extra_glyph_asset = (
        additional_dialogue_glyph_asset
        if additional_dialogue_glyph_asset is not None
        else extra_glyph_asset
    )
    later_glyph_assets = tuple(
        asset
        for asset in (extra_glyph_asset, later_extra_glyph_asset)
        if asset is not None
    )
    later_glyphs, later_code_by_character = create_glyph_mapping(
        later_macro_free_text,
        later_glyph_assets,
        later_candidate,
    )
    later_dialogue_payload = encode_translation_span(
        later_dialogue_text,
        later_code_by_character,
        LATER_DIALOGUE_SPAN[1] - LATER_DIALOGUE_SPAN[0],
        expected_ellipsis_codes=0,
        macro_tokens=LATER_DIALOGUE_MACROS,
    )

    font_patterns = decode_resource(source_rom, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    if len(font_patterns) != FONT_LENGTH:
        raise ValueError("decoded original font has an unexpected size")
    def backup_patterns(glyph_values, label):
        patterns = tuple(
            font_patterns[
                (glyph.tile - 0x80) * TILE_PATTERN_SIZE:
                (glyph.tile - 0x80 + 1) * TILE_PATTERN_SIZE
            ]
            for glyph in glyph_values
        )
        if any(len(pattern) != TILE_PATTERN_SIZE for pattern in patterns):
            raise ValueError(f"original font is missing a {label} glyph backup pattern")
        return patterns

    original_patterns = backup_patterns(glyphs, "prologue")
    next_original_patterns = backup_patterns(next_glyphs, "next-dialogue")
    additional_original_patterns = backup_patterns(
        additional_glyphs,
        "additional-dialogue",
    )
    practice_original_patterns = backup_patterns(
        practice_glyphs,
        "practice-dialogue",
    )
    later_original_patterns = backup_patterns(later_glyphs, "later-dialogue")

    context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x33,
        first_cursor=PROLOGUE_LOAD_FIRST_CURSOR,
        restore_cursor=PROLOGUE_RESTORE_CURSOR,
        source_offset=FIRST_TEXT_SPAN[0],
        payload=teacher_payload,
        glyphs=tuple(glyphs),
        marker=PROLOGUE_MARKER,
        restore_from_rom=True,
        original_patterns=original_patterns,
        return_code=glyphs[0].tile,
        loader_return_b=0xCD,
    )
    next_context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x34,
        first_cursor=NEXT_DIALOGUE_LOAD_FIRST_CURSOR,
        restore_cursor=NEXT_DIALOGUE_RESTORE_CURSOR,
        source_offset=NEXT_DIALOGUE_SPAN[0],
        payload=next_dialogue_payload,
        glyphs=tuple(next_glyphs),
        marker=NEXT_DIALOGUE_MARKER,
        restore_from_rom=True,
        original_patterns=next_original_patterns,
        return_code=next_glyphs[0].tile,
        loader_return_b=0xCD,
    )

    additional_context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x33,
        first_cursor=ADDITIONAL_DIALOGUE_LOAD_CURSOR,
        restore_cursor=ADDITIONAL_DIALOGUE_RESTORE_CURSOR,
        source_offset=ADDITIONAL_DIALOGUE_SPAN[0],
        payload=additional_dialogue_payload,
        glyphs=tuple(additional_glyphs),
        marker=ADDITIONAL_DIALOGUE_MARKER,
        restore_from_rom=True,
        original_patterns=additional_original_patterns,
        return_code=additional_glyphs[0].tile,
        loader_return_b=0xCD,
    )
    practice_context = PilotContext(
        record_id="opening",
        bank=0x24,
        pointer_high=0x74,
        first_cursor=PRACTICE_DIALOGUE_LOAD_CURSOR,
        restore_cursor=PRACTICE_DIALOGUE_RESTORE_CURSOR,
        source_offset=PRACTICE_DIALOGUE_SPAN[0],
        payload=practice_dialogue_payload,
        glyphs=tuple(practice_glyphs),
        marker=PRACTICE_DIALOGUE_MARKER,
        restore_from_rom=True,
        original_patterns=practice_original_patterns,
        return_code=practice_glyphs[0].tile,
        loader_return_b=0xCD,
    )
    later_context = PilotContext(
        record_id="opening",
        bank=0x24,
        pointer_high=0x75,
        first_cursor=LATER_DIALOGUE_LOAD_CURSOR,
        restore_cursor=LATER_DIALOGUE_RESTORE_CURSOR,
        source_offset=LATER_DIALOGUE_SPAN[0],
        payload=later_dialogue_payload,
        glyphs=tuple(later_glyphs),
        marker=LATER_DIALOGUE_MARKER,
        restore_from_rom=True,
        original_patterns=later_original_patterns,
        return_code=later_glyphs[0].tile,
        loader_return_b=0xCD,
    )

    contexts = (
        context,
        next_context,
        additional_context,
        practice_context,
        later_context,
    )
    cursor_windows = (True, True, False, True, True)
    loader_offsets = []
    loader_bytes = []
    pattern_offsets = []
    pattern_bytes = []
    original_pattern_offsets = []
    original_pattern_bytes = []
    restore_offsets = []
    restore_bytes = []
    next_offset = PROLOGUE_BANK10_START
    for current_context, current_original_patterns in zip(
        contexts,
        (
            original_patterns,
            next_original_patterns,
            additional_original_patterns,
            practice_original_patterns,
            later_original_patterns,
        ),
    ):
        loader_offset = next_offset
        preliminary_loader = build_loader_helper(current_context, 0x4100)
        pattern_offset = _align_up(loader_offset + len(preliminary_loader), 0x10)
        current_pattern_data = b"".join(glyph.pattern for glyph in current_context.glyphs)
        loader = build_loader_helper(
            current_context,
            bank_cpu_address(pattern_offset),
        )
        original_pattern_offset = _align_up(
            pattern_offset + len(current_pattern_data),
            0x10,
        )
        current_original_data = b"".join(current_original_patterns)
        restore_helper_offset = _align_up(
            original_pattern_offset + len(current_original_data),
            0x10,
        )
        restore_helper = build_restore_helper(
            current_context,
            bank_cpu_address(restore_helper_offset),
            bank_cpu_address(original_pattern_offset),
        )
        loader_offsets.append(loader_offset)
        loader_bytes.append(loader)
        pattern_offsets.append(pattern_offset)
        pattern_bytes.append(current_pattern_data)
        original_pattern_offsets.append(original_pattern_offset)
        original_pattern_bytes.append(current_original_data)
        restore_offsets.append(restore_helper_offset)
        restore_bytes.append(restore_helper)
        next_offset = _align_up(restore_helper_offset + len(restore_helper), 0x10)
    load_dispatcher = build_load_dispatcher(
        contexts,
        tuple(loader_offsets),
        cursor_window=cursor_windows,
    )
    load_gate = _build_load_gate(
        bank_cpu_address(LOAD_DISPATCHER_OFFSET),
        bank_cpu_address(LEGACY_ENTRY_COPY_OFFSET),
    )
    restore_dispatcher_offset = _align_up(next_offset, 0x10)
    restore_dispatcher = build_restore_dispatcher(
        contexts,
        tuple(restore_offsets),
    )
    if restore_dispatcher_offset + len(restore_dispatcher) > PROLOGUE_BANK10_END:
        raise ValueError("prologue glyph helpers exceed the free bank-10 allocation")

    restore_wrapper = _build_restore_wrapper(
        bank_cpu_address(restore_dispatcher_offset),
    )
    legacy_loader = parent_rom[LEGACY_ENTRY_OFFSET:LEGACY_ENTRY_END]
    if len(legacy_loader) != 0x2C:
        raise ValueError("V2.5 legacy loader has an unexpected size")
    if parent_rom[NEW_LOAD_GATE_OFFSET:NEW_LOAD_GATE_OFFSET + len(load_gate)] != (
        bytes([0xFF]) * len(load_gate)
    ):
        raise ValueError("prologue load gate overlaps occupied V2.5 bank-10 bytes")
    if parent_rom[
        LOAD_DISPATCHER_OFFSET:LOAD_DISPATCHER_OFFSET + len(load_dispatcher)
    ] != bytes([0xFF]) * len(load_dispatcher):
        raise ValueError("prologue load dispatcher overlaps occupied V2.5 bank-10 bytes")
    if parent_rom[RESTORE_WRAPPER_OFFSET:RESTORE_WRAPPER_OFFSET + len(restore_wrapper)] != (
        bytes([0xFF]) * len(restore_wrapper)
    ):
        raise ValueError("prologue restore wrapper overlaps occupied V2.5 bank-10 bytes")
    if parent_rom[
        LEGACY_ENTRY_COPY_OFFSET:LEGACY_ENTRY_COPY_OFFSET + len(legacy_loader)
    ] != bytes([0xFF]) * len(legacy_loader):
        raise ValueError("legacy loader fallback overlaps occupied V2.5 bank-10 bytes")

    result = bytearray(parent_rom)
    result[LEGACY_ENTRY_OFFSET:LEGACY_ENTRY_OFFSET + 3] = (
        bytes((0xC3,)) + bank_cpu_address(NEW_LOAD_GATE_OFFSET).to_bytes(2, "little")
    )
    result[NEW_LOAD_GATE_OFFSET:NEW_LOAD_GATE_OFFSET + len(load_gate)] = load_gate
    result[
        LOAD_DISPATCHER_OFFSET:
        LOAD_DISPATCHER_OFFSET + len(load_dispatcher)
    ] = load_dispatcher
    result[
        RESTORE_WRAPPER_OFFSET:RESTORE_WRAPPER_OFFSET + len(restore_wrapper)
    ] = restore_wrapper
    result[
        LEGACY_ENTRY_COPY_OFFSET:LEGACY_ENTRY_COPY_OFFSET + len(legacy_loader)
    ] = legacy_loader
    result[
        RESTORE_ROUTER_CALL_OFFSET:
        RESTORE_ROUTER_CALL_OFFSET + len(RESTORE_ROUTER_CALL_EXPECTED)
    ] = bytes((0xCD,)) + bank_cpu_address(RESTORE_WRAPPER_OFFSET).to_bytes(2, "little")

    for index in range(len(contexts)):
        _install_free_component(
            result,
            parent_rom,
            loader_offsets[index],
            loader_bytes[index],
            PROLOGUE_BANK10_END,
            f"prologue glyph loader {index + 1}",
        )
        _install_free_component(
            result,
            parent_rom,
            pattern_offsets[index],
            pattern_bytes[index],
            PROLOGUE_BANK10_END,
            f"prologue glyph patterns {index + 1}",
        )
        _install_free_component(
            result,
            parent_rom,
            original_pattern_offsets[index],
            original_pattern_bytes[index],
            PROLOGUE_BANK10_END,
            f"prologue original glyph patterns {index + 1}",
        )
        _install_free_component(
            result,
            parent_rom,
            restore_offsets[index],
            restore_bytes[index],
            PROLOGUE_BANK10_END,
            f"prologue restore helper {index + 1}",
        )
    _install_free_component(
        result,
        parent_rom,
        restore_dispatcher_offset,
        restore_dispatcher,
        PROLOGUE_BANK10_END,
        "prologue restore dispatcher",
    )

    for start, payload in (
        (FIRST_TEXT_SPAN[0], teacher_payload),
        (STUDENT_TEXT_SPAN[0], student_payload),
        (THIRD_TEXT_SPAN[0], third_payload),
        (NEXT_DIALOGUE_SPAN[0], next_dialogue_payload),
        (ADDITIONAL_DIALOGUE_SPAN[0], additional_dialogue_payload),
        (PRACTICE_DIALOGUE_SPAN[0], practice_dialogue_payload),
        (LATER_DIALOGUE_SPAN[0], later_dialogue_payload),
    ):
        result[start:start + len(payload)] = payload
        mirror_start = MBC1_MIRROR_OFFSET + start
        result[mirror_start:mirror_start + len(payload)] = payload

    result[
        MENU_EXTENSION_ALIAS_OFFSET:
        MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE
    ] = result[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]

    checked = update_checksums(result)
    if len(checked) != MENU_EXPANDED_SIZE or not verify_rom(checked).passed:
        raise ValueError("V2.6 prologue ROM failed size or checksum verification")
    if checked[0x148] != MENU_ROM_SIZE_CODE:
        raise ValueError("V2.6 prologue ROM has an unexpected ROM-size code")
    if (
        checked[MENU_EXTENSION_ALIAS_OFFSET:MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE]
        != checked[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]
    ):
        raise ValueError("V2.6 bank-10 extension alias is inconsistent")
    for offset, payload, label in (
        (0x0133C8, b"\x7E", "first event page control"),
        (0x0133C9, b"\x7C", "first event region control"),
        (0x0133D3, b"\x7F", "first event terminator"),
        (0x0133D7, b"\x7C", "third event region control"),
        (0x0133E8, b"\x7F", "third event terminator"),
        (ADDITIONAL_DIALOGUE_EVENT_END - 1, b"\x7F", "additional dialogue terminator"),
        (PRACTICE_DIALOGUE_SPAN[1], b"\x7E", "practice dialogue page control"),
        (LATER_DIALOGUE_EVENT_END - 1, b"\x7F", "later dialogue terminator"),
        (0x01346D, b"\x7E", "next dialogue page control"),
        (0x01347B, b"\x7F", "next dialogue terminator"),
    ):
        _require_span(checked, offset, payload, label)
        _require_span(checked, MBC1_MIRROR_OFFSET + offset, payload, f"{label} mirror")
    return checked


def build_v2_6_patch(
    parent_rom: bytes,
    source_rom: bytes,
    manifest: Any,
    glyph_asset: Any,
    tile_candidate: Any,
    extra_glyph_asset: Any | None = None,
    practice_glyph_asset: Any | None = None,
    additional_dialogue_glyph_asset: Any | None = None,
) -> tuple[bytes, bytes, str]:
    target_rom = build_v2_6_rom(
        parent_rom,
        source_rom,
        manifest,
        glyph_asset,
        tile_candidate,
        extra_glyph_asset,
        practice_glyph_asset,
        additional_dialogue_glyph_asset,
    )
    copy_spans = (
        (
            MBC1_MIRROR_OFFSET + FIRST_EVENT_OFFSET + 1,
            FIRST_EVENT_OFFSET + 1,
            THIRD_EVENT_END - (FIRST_EVENT_OFFSET + 1),
        ),
        (
            MBC1_MIRROR_OFFSET + NEXT_DIALOGUE_SPAN[0],
            NEXT_DIALOGUE_SPAN[0],
            NEXT_DIALOGUE_SPAN[1] - NEXT_DIALOGUE_SPAN[0],
        ),
        (
            MBC1_MIRROR_OFFSET + ADDITIONAL_DIALOGUE_SPAN[0],
            ADDITIONAL_DIALOGUE_SPAN[0],
            ADDITIONAL_DIALOGUE_SPAN[1] - ADDITIONAL_DIALOGUE_SPAN[0],
        ),
        (
            MBC1_MIRROR_OFFSET + PRACTICE_DIALOGUE_SPAN[0],
            PRACTICE_DIALOGUE_SPAN[0],
            PRACTICE_DIALOGUE_SPAN[1] - PRACTICE_DIALOGUE_SPAN[0],
        ),
        (
            MBC1_MIRROR_OFFSET + LATER_DIALOGUE_SPAN[0],
            LATER_DIALOGUE_SPAN[0],
            LATER_DIALOGUE_SPAN[1] - LATER_DIALOGUE_SPAN[0],
        ),
        (MENU_EXTENSION_ALIAS_OFFSET, SOURCE_SIZE, ROM_BANK_SIZE),
    )
    patch = create_bps_patch(parent_rom, target_rom, copy_spans)
    if apply_bps_patch(parent_rom, patch) != target_rom:
        raise ValueError("V2.5-to-V2.6 BPS round-trip did not reproduce the target ROM")
    return patch, target_rom, hashlib.sha256(target_rom).hexdigest()


def build_v2_6_1_patch(v2_6_rom: bytes, target_rom: bytes) -> bytes:
    if len(v2_6_rom) != MENU_EXPANDED_SIZE:
        raise ValueError(f"V2.6 parent ROM must be exactly {MENU_EXPANDED_SIZE} bytes")
    if hashlib.sha256(v2_6_rom).hexdigest() != EXPECTED_V2_6_SHA256:
        raise ValueError("V2.6 parent ROM does not match the user-accepted baseline")
    if not verify_rom(v2_6_rom).passed:
        raise ValueError("V2.6 parent ROM failed checksum verification")
    if len(target_rom) != MENU_EXPANDED_SIZE or not verify_rom(target_rom).passed:
        raise ValueError("V2.6.1 target ROM failed size or checksum verification")
    patch = create_bps_patch(v2_6_rom, target_rom)
    if apply_bps_patch(v2_6_rom, patch) != target_rom:
        raise ValueError("V2.6-to-V2.6.1 BPS round-trip did not reproduce the target ROM")
    return patch


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_v2_6_files(
    parent_path: Path,
    source_path: Path,
    patch_path: Path,
    version_path: Path,
    overwrite: bool = False,
) -> tuple[Path, Path, str, str]:
    parent = parent_path.resolve(strict=True)
    source = source_path.resolve(strict=True)
    patch_output = patch_path.resolve()
    version_output = version_path.resolve()
    rom_output = (ROOT / "roms" / "oni5_v2_6_1_opening_prologue.gb").resolve()
    v2_6_rom_output = V2_6_ROM_OUTPUT.resolve()
    v2_6_patch = V2_6_PATCH_PATH.resolve(strict=True)
    inputs = {
        parent,
        source,
        v2_6_patch,
        *(ROOT / "data" / name for name in V2_5_INPUT_FILES),
    }
    if (
        patch_output in inputs
        or version_output in inputs
        or rom_output in inputs
        or v2_6_rom_output in inputs
        or patch_output == version_output
        or patch_output == rom_output
        or patch_output == v2_6_rom_output
        or version_output == rom_output
        or version_output == v2_6_rom_output
        or rom_output == v2_6_rom_output
    ):
        raise ValueError("V2.6.1 outputs must differ from each other and every input")
    if not patch_output.parent.is_dir() or not version_output.parent.is_dir() or not rom_output.parent.is_dir():
        raise ValueError("V2.6.1 output directories must already exist")
    if not overwrite and any(
        path.exists()
        for path in (patch_output, version_output, rom_output, v2_6_rom_output)
    ):
        raise FileExistsError("a V2.6.1 output already exists; pass --overwrite to replace it")

    v2_6_patch_bytes = v2_6_patch.read_bytes()
    if hashlib.sha256(v2_6_patch_bytes).hexdigest() != EXPECTED_V2_6_PATCH_SHA256:
        raise ValueError("V2.6 baseline patch does not match the accepted build")
    v2_6_rom = apply_bps_patch(parent.read_bytes(), v2_6_patch_bytes)
    if hashlib.sha256(v2_6_rom).hexdigest() != EXPECTED_V2_6_SHA256:
        raise ValueError("reconstructed V2.6 ROM does not match the accepted baseline")
    (
        manifest,
        glyph_asset,
        tile_candidate,
        next_glyph_asset,
        practice_glyph_asset,
        additional_dialogue_glyph_asset,
    ) = (
        _load_json(ROOT / "data" / name)
        for name in V2_5_INPUT_FILES
    )
    _, target_rom, target_digest = build_v2_6_patch(
        parent.read_bytes(),
        source.read_bytes(),
        manifest,
        glyph_asset,
        tile_candidate,
        next_glyph_asset,
        practice_glyph_asset,
        additional_dialogue_glyph_asset,
    )
    patch = build_v2_6_1_patch(v2_6_rom, target_rom)
    patch_digest = hashlib.sha256(patch).hexdigest()
    version_manifest = {
        "schema_version": 1,
        "version_id": "V2.6.1-opening-dialogue",
        "parent_version": {
            "version_id": "V2.6-opening-prologue-preview",
            "path": "../roms/oni5_v2_6_opening_prologue.gb",
            "sha256": EXPECTED_V2_6_SHA256,
        },
        "source_rom": {
            "path": "../roms/oni5_original.gb",
            "sha256": EXPECTED_SOURCE_SHA256,
        },
        "patch": {
            "path": f"../roms/{patch_output.name}",
            "size_bytes": len(patch),
            "sha256": patch_digest,
        },
        "target_rom": {
            "path": f"../roms/{rom_output.name}",
            "size_bytes": len(target_rom),
            "sha256": target_digest,
            "persisted_by_builder": True,
        },
        "runtime_validation": {
            "status": "pending-user-sameboy",
            "tested_rom_sha256": None,
            "required_sameboy_checks": [
                "Apply this BPS to the accepted V2.6 ROM and confirm the resulting ROM SHA-256 matches target_rom.sha256.",
                "Start a new game and confirm 静那's prologue, the student's reply, and 静那's next line display in Chinese.",
                "Confirm 静 is rendered with tile $81, not the native opening-quote tile $BB.",
                "Confirm the tile above the first Chinese glyph remains blank ($CD); this was a prior first-glyph regression.",
                "Confirm the new line 「常叶丸『突然想见你了。』」 and its period Tile $BE.",
                "Confirm the 25-byte dialogue at $0133EF-$013407 preserves the original $AD protagonist-name macro and the $013408 terminator.",
                "Confirm 「今日的修行／就到此为止」 at $01348F and the compact 「常叶丸／『什么情况这气息！？』」 at $013545.",
                "Confirm the deferred $013411 dialogue remains unchanged in V2.6.1.",
                "Confirm the glyphs restore before the next original dialogue.",
                "Advance across the page transition between 静那's explanation and the student reply; confirm no blank scroll, freeze, or stray tile.",
                "Continue past the third line and confirm original Japanese dialogue glyphs restore before later conversations.",
                "Confirm existing V2.6 opening-prologue behavior remains unchanged.",
            ],
        },
        "features": [
            "opening-prologue-dialogue",
            "student-reply",
            "prologue-font-restoration",
            "confirmed-bank04-dialogue",
            "confirmed-bank24-dialogues",
        ],
        "text_records": [
            *PROLOGUE_RECORD_IDS,
            NEXT_DIALOGUE_RECORD_ID,
            ADDITIONAL_DIALOGUE_RECORD_ID,
            PRACTICE_DIALOGUE_RECORD_ID,
            LATER_DIALOGUE_RECORD_ID,
        ],
        "deferred_to_v2_6_2": [
            {
                "record_id": "oni5-bank04-inline-013411",
                "task": "Design a local translated-name expansion without changing shared name macros.",
            }
        ],
        "inputs": [
            {
                "path": f"../data/{name}",
                "sha256": hashlib.sha256((ROOT / "data" / name).read_bytes()).hexdigest(),
            }
            for name in V2_5_INPUT_FILES
        ] + [
            {
                "path": f"../roms/{v2_6_patch.name}",
                "sha256": hashlib.sha256(v2_6_patch_bytes).hexdigest(),
            }
        ],
        "builder": {
            "script": "../scripts/build_v2_6_prologue_patch.py",
            "arguments": ["--overwrite"],
        },
        "automated_validation": {
            "checksum": "Target ROM passes the repository's ROM checksum verification.",
            "bps_round_trip": "Applying the V2.6-to-V2.6.1 BPS patch reproduces the target ROM.",
            "full_rom_persisted": True,
        },
        "rebuild_command": (
            "./.venv/bin/python scripts/build_v2_6_prologue_patch.py "
            "--output-patch roms/oni5_v2_6_1_opening_prologue.bps "
            "--output-version versions/V2.6.1-opening-dialogue.json "
            "--overwrite"
        ),
    }
    patch_bytes = patch
    version_bytes = (json.dumps(version_manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    write_output(patch_output, patch_bytes, overwrite)
    write_output(version_output, version_bytes, overwrite)
    write_output(rom_output, target_rom, overwrite)
    write_output(v2_6_rom_output, v2_6_rom, overwrite)
    if (
        patch_output.read_bytes() != patch_bytes
        or version_output.read_bytes() != version_bytes
        or rom_output.read_bytes() != target_rom
        or v2_6_rom_output.read_bytes() != v2_6_rom
    ):
        raise OSError("written V2.6.1 outputs differ from the deterministic build")
    return patch_output, version_output, patch_digest, target_digest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the V2.6.1 ROM and V2.6-based BPS patch."
    )
    parser.add_argument(
        "--parent",
        type=Path,
        default=ROOT / "roms" / "oni5_v2_5_main_menu.gb",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
    )
    parser.add_argument(
        "--output-patch",
        type=Path,
        default=ROOT / "roms" / "oni5_v2_6_1_opening_prologue.bps",
    )
    parser.add_argument(
        "--output-version",
        type=Path,
        default=ROOT / "versions" / "V2.6.1-opening-dialogue.json",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        patch_path, version_path, patch_digest, target_digest = build_v2_6_files(
            args.parent,
            args.source,
            args.output_patch,
            args.output_version,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote V2.6-to-V2.6.1 BPS patch: {patch_path}")
    print(f"BPS SHA-256: {patch_digest}")
    print(f"Wrote V2.6.1 version manifest: {version_path}")
    print(f"In-memory target ROM SHA-256: {target_digest}")
    print(f"Wrote V2.6.1 test ROM: {ROOT / 'roms' / 'oni5_v2_6_1_opening_prologue.gb'}")
    print("SameBoy validation is pending.")


if __name__ == "__main__":
    main()
