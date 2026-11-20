"""Add the confirmed opening, Shizuna reply, and Tokiwa visit to V2.6."""
import hashlib
import json
from pathlib import Path

from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_mbc1_expansion_probe import SOURCE_SIZE
from scripts.build_menu_pilot import (
    MENU_EXPANDED_SIZE,
    MBC1_MIRROR_OFFSET,
    ROM_BANK_SIZE,
)
from scripts.build_noticeboard_glyph_probe import CachedGlyph, TILE_PATTERN_SIZE
from scripts.build_opening_text_preview_patch import (
    FONT_BANK,
    FONT_DESCRIPTOR,
    FONT_LENGTH,
    create_glyph_mapping,
)
from scripts.build_text_comparison_pilot import (
    PilotContext,
    build_loader_helper,
    build_restore_dispatcher,
    build_restore_helper,
    bank_cpu_address,
)
from scripts.build_v2_6_prologue_patch import (
    ADDITIONAL_DIALOGUE_RECORD_ID,
    ADDITIONAL_DIALOGUE_SPAN,
    EXPECTED_SOURCE_SHA256,
    EXPECTED_V2_6_SHA256,
    NEXT_DIALOGUE_NATIVE_TILES,
    NATIVE_QUOTE_TILES,
    PROTAGONIST_NATIVE_TILES,
    _candidate_excluding_tiles,
    _load_json,
    _require_object,
    _translation_text,
    encode_translation_span,
)
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
BASE_ROM = ROOT / "roms" / "oni5_v2_6_opening_prologue.gb"
SOURCE_ROM = ROOT / "roms" / "oni5_original.gb"
OUTPUT_ROM = ROOT / "roms" / "oni5_v2_6_1_opening_prologue.gb"
OUTPUT_PATCH = ROOT / "roms" / "oni5_v2_6_1_opening_prologue.bps"
OUTPUT_VERSION = ROOT / "versions" / "V2.6.1-opening-dialogue.json"
RECORD_ID = "oni5-bank04-inline-0133ef"
TEXT_SPAN = ADDITIONAL_DIALOGUE_SPAN
MARKER = 0x85
REPLY_RECORD_ID = "oni5-bank04-inline-01342e"
REPLY_TEXT_SPAN = (0x01342E, 0x013452)
REPLY_MARKER = 0x88
REPLY_FIRST_CURSOR = 0x2E
REPLY_RESTORE_CURSOR = 0x53
TOKIWA_RECORD_ID = "oni5-bank04-inline-013459"
TOKIWA_TEXT_SPAN = (0x013459, 0x01346D)
TOKIWA_MARKER = 0x89
TOKIWA_FIRST_CURSOR = 0x59
TOKIWA_RESTORE_CURSOR = 0x6E
SHIZUNA_FOLLOWUP_TEXT_SPAN = (0x01346F, 0x01347B)
SHIZUNA_FOLLOWUP_MACROS = {
    "{静那}": (0xAD, 2),
    "{常叶丸}": (0x95, 3),
}
MACRO_ROUTER_HOOK_OFFSET = 0x1709
MACRO_ROUTER_HOOK_EXPECTED = bytes.fromhex(
    "3E 0C E0 AA 78 D6 80 28 2A CB 27"
)
MACRO_OVERRIDE_BANK = 0x11
MACRO_OVERRIDE_BANK_OFFSET = SOURCE_SIZE + ROM_BANK_SIZE
# Banked reads from $4000-$7FFF select FFAA plus the address-window bank.
MACRO_OVERRIDE_DATA_BANK_OFFSET = MACRO_OVERRIDE_BANK_OFFSET + ROM_BANK_SIZE
MACRO_TABLE_OFFSET = 0x0200
SHIZUNA_MACRO_DATA_OFFSET = 0x1200
TOKIWA_MACRO_DATA_OFFSET = 0x1210
MACRO_ROUTER_BANK_OFFSET = SOURCE_SIZE
MACRO_ROUTER_OFFSET = 0x3F00
MACRO_BANK_SWITCH_OFFSET = 0x2050
MACRO_BANK_SWITCH_EXPECTED = bytes.fromhex("E0 A9 EA 00 21 C9")
LOAD_GATE_OFFSET = SOURCE_SIZE + 0x0100
LOAD_DISPATCHER_OFFSET = SOURCE_SIZE + 0x0200
RESTORE_WRAPPER_OFFSET = SOURCE_SIZE + 0x3040
OLD_RESTORE_WRAPPER_OFFSET = SOURCE_SIZE + 0x3080
COMPONENTS_START = SOURCE_SIZE + 0x32C0
ALLOCATION_END = SOURCE_SIZE + ROM_BANK_SIZE
FIXED_NAME_TRANSLATIONS = {"{静那}": "静那"}


def _install(rom: bytearray, start: int, data: bytes, label: str) -> None:
    end = start + len(data)
    if end > ALLOCATION_END or rom[start:end] != bytes([0xFF]) * len(data):
        raise ValueError(f"{label} overlaps occupied V2.6 bank-10 bytes")
    rom[start:end] = data


def _restore_router(dispatcher_address: int) -> bytes:
    old_wrapper_address = bank_cpu_address(OLD_RESTORE_WRAPPER_OFFSET)
    return (
        bytes.fromhex("F5 CD")
        + dispatcher_address.to_bytes(2, "little")
        + bytes.fromhex("F1 C3")
        + old_wrapper_address.to_bytes(2, "little")
    )


def _build_macro_override_router() -> bytes:
    code = bytearray()
    labels: dict[str, int] = {}
    branches: list[tuple[int, str]] = []

    def branch(opcode: int, label: str) -> None:
        code.extend((opcode, 0))
        branches.append((len(code) - 1, label))

    code.extend(bytes.fromhex("F8 01 7E E0 A9 33 33 F8 01 7E FE 04"))
    branch(0x20, "fallback")
    code.extend(bytes.fromhex("78 FE AD"))
    branch(0x28, "shizuna")
    code.extend(bytes.fromhex("FE 95"))
    branch(0x20, "fallback")
    code.extend(bytes.fromhex("F0 AE FE 34"))
    branch(0x20, "fallback")
    code.extend(bytes.fromhex("F0 AD FE 73"))
    branch(0x20, "fallback")
    branch(0x18, "target")

    labels["shizuna"] = len(code)
    code.extend(bytes.fromhex("F0 AE FE 34"))
    branch(0x20, "fallback")
    code.extend(bytes.fromhex("F0 AD FE 70"))
    branch(0x20, "fallback")

    labels["target"] = len(code)
    code.extend(bytes.fromhex("3E 11 E0 AA"))
    branch(0x18, "calculate")
    labels["fallback"] = len(code)
    code.extend(bytes.fromhex("3E 0C E0 AA"))
    labels["calculate"] = len(code)
    code.extend(bytes.fromhex("78 D6 80"))
    branch(0x28, "dynamic_name")
    code.extend(bytes.fromhex("CB 27 C3 14 17"))
    labels["dynamic_name"] = len(code)
    code.extend(bytes.fromhex("F0 A9 CD 50 20 78 D6 80 C3 3C 17"))

    for displacement_offset, label in branches:
        displacement = labels[label] - (displacement_offset + 1)
        if not -128 <= displacement <= 127:
            raise ValueError("macro override router branch exceeds its signed range")
        code[displacement_offset] = displacement & 0xFF
    return bytes(code)


def _install_macro_overrides(
    target: bytearray,
    base: bytes,
    code_by_character: dict[str, int],
) -> None:
    if base[
        MACRO_ROUTER_HOOK_OFFSET:
        MACRO_ROUTER_HOOK_OFFSET + len(MACRO_ROUTER_HOOK_EXPECTED)
    ] != MACRO_ROUTER_HOOK_EXPECTED:
        raise ValueError("V2.6 macro expansion hook has an unexpected layout")
    if base[
        MACRO_BANK_SWITCH_OFFSET:
        MACRO_BANK_SWITCH_OFFSET + len(MACRO_BANK_SWITCH_EXPECTED)
    ] != MACRO_BANK_SWITCH_EXPECTED:
        raise ValueError("V2.6 MBC1 bank-switch helper has an unexpected layout")

    bank_start = MACRO_OVERRIDE_BANK_OFFSET
    if base[bank_start:bank_start + ROM_BANK_SIZE] != bytes([0xFF]) * ROM_BANK_SIZE:
        raise ValueError("V2.6 bank 0x11 is not free for local macro expansion data")
    mirror_start = MBC1_MIRROR_OFFSET + bank_start
    if base[mirror_start:mirror_start + ROM_BANK_SIZE] != bytes([0xFF]) * ROM_BANK_SIZE:
        raise ValueError("V2.6 bank 0x31 alias is not free for macro expansion data")
    data_bank_start = MACRO_OVERRIDE_DATA_BANK_OFFSET
    if base[data_bank_start:data_bank_start + ROM_BANK_SIZE] != bytes([0xFF]) * ROM_BANK_SIZE:
        raise ValueError("V2.6 bank 0x12 is not free for macro expansion data")
    data_mirror_start = MBC1_MIRROR_OFFSET + data_bank_start
    if base[data_mirror_start:data_mirror_start + ROM_BANK_SIZE] != bytes([0xFF]) * ROM_BANK_SIZE:
        raise ValueError("V2.6 bank 0x32 alias is not free for macro expansion data")
    router_start = MACRO_ROUTER_BANK_OFFSET + MACRO_ROUTER_OFFSET
    router = _build_macro_override_router()
    if base[router_start:router_start + len(router)] != bytes([0xFF]) * len(router):
        raise ValueError("V2.6 bank 0x10 has no reserved space for the macro router")

    def install(offset: int, data: bytes, label: str) -> None:
        start = bank_start + offset
        end = start + len(data)
        if end > bank_start + ROM_BANK_SIZE or base[start:end] != bytes([0xFF]) * len(data):
            raise ValueError(f"{label} overlaps occupied V2.6 bank 0x11 bytes")
        target[start:end] = data

    def install_data(offset: int, data: bytes, label: str) -> None:
        start = data_bank_start + offset
        end = start + len(data)
        if end > data_bank_start + ROM_BANK_SIZE or base[start:end] != bytes([0xFF]) * len(data):
            raise ValueError(f"{label} overlaps occupied V2.6 bank 0x12 bytes")
        target[start:end] = data

    def macro_data(name: str) -> bytes:
        return bytes((len(name), *(code_by_character[character] for character in name)))

    shizuna_data = macro_data("静那")
    tokiwa_data = macro_data("常叶丸")
    install_data(SHIZUNA_MACRO_DATA_OFFSET, shizuna_data, "Shizuna macro data")
    install_data(TOKIWA_MACRO_DATA_OFFSET, tokiwa_data, "Tokiwa macro data")

    table_entries = (
        (0xAD, SHIZUNA_MACRO_DATA_OFFSET),
        (0x95, TOKIWA_MACRO_DATA_OFFSET),
    )
    for macro_code, data_offset in table_entries:
        table_offset = MACRO_TABLE_OFFSET + 2 * (macro_code - 0x80)
        pointer = 0x4000 + data_offset
        install(table_offset, pointer.to_bytes(2, "little"), f"${macro_code:02X} macro table entry")

    _install(target, router_start, router, "local macro override router")
    hook = (
        bytes.fromhex("F0 A9 F5 3E 10 CD 50 20 C3")
        + bank_cpu_address(router_start).to_bytes(2, "little")
    )
    target[
        MACRO_ROUTER_HOOK_OFFSET:
        MACRO_ROUTER_HOOK_OFFSET + len(hook)
    ] = hook


def _build_load_dispatcher(
    opening_context: PilotContext,
    opening_loader_offset: int,
    reply_context: PilotContext,
    reply_loader_offset: int,
    tokiwa_context: PilotContext,
    tokiwa_loader_offset: int,
) -> bytes:
    code = bytearray.fromhex("FA AA FF FE")
    code.append(opening_context.bank)
    opening_bank_miss = len(code)
    code.extend((0x20, 0))

    code.extend(bytes.fromhex("FA AE FF FE"))
    code.append(opening_context.pointer_high)
    high34_check = len(code)
    code.extend((0x20, 0))
    code.extend(bytes.fromhex("FA AD FF FE"))
    code.append(0xEF)
    before_opening_start = len(code)
    code.extend((0x38, 0))
    opening_match_jump = len(code)
    code.extend((0x18, 0))

    high34_start = len(code)
    code.extend(bytes.fromhex("FA AE FF FE 34"))
    high34_miss = len(code)
    code.extend((0x20, 0))
    code.extend(bytes.fromhex("FA AD FF FE 09"))
    after_opening_end = len(code)
    code.extend((0x30, 0))

    opening_match = len(code)
    code.extend(bytes.fromhex("FA F2 C4 FE"))
    code.append(opening_context.marker)
    code.extend(bytes.fromhex("20 02 AF C9 CD"))
    code.extend(bank_cpu_address(opening_loader_offset).to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 01 C9"))

    reply_start = len(code)
    code.extend(bytes.fromhex("FA AA FF FE"))
    code.append(reply_context.bank)
    reply_bank_miss = len(code)
    code.extend((0x20, 0))
    code.extend(bytes.fromhex("FA AE FF FE"))
    code.append(reply_context.pointer_high)
    reply_pointer_miss = len(code)
    code.extend((0x20, 0))
    code.extend(bytes.fromhex("FA AD FF FE"))
    code.append(reply_context.first_cursor)
    reply_before_start = len(code)
    code.extend((0x38, 0))
    code.extend(bytes.fromhex("FA AD FF FE"))
    code.append(reply_context.restore_cursor)
    reply_after_end = len(code)
    code.extend((0x30, 0))
    code.extend(bytes.fromhex("FA F2 C4 FE"))
    code.append(reply_context.marker)
    code.extend(bytes.fromhex("20 02 AF C9 CD"))
    code.extend(bank_cpu_address(reply_loader_offset).to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 01 C9"))

    tokiwa_start = len(code)
    code.extend(bytes.fromhex("FA AA FF FE"))
    code.append(tokiwa_context.bank)
    tokiwa_bank_miss = len(code)
    code.extend((0x20, 0))
    code.extend(bytes.fromhex("FA AE FF FE"))
    code.append(tokiwa_context.pointer_high)
    tokiwa_pointer_miss = len(code)
    code.extend((0x20, 0))
    code.extend(bytes.fromhex("FA AD FF FE"))
    code.append(tokiwa_context.first_cursor)
    tokiwa_before_start = len(code)
    code.extend((0x38, 0))
    code.extend(bytes.fromhex("FA AD FF FE"))
    code.append(tokiwa_context.restore_cursor)
    tokiwa_after_end = len(code)
    code.extend((0x30, 0))
    code.extend(bytes.fromhex("FA F2 C4 FE"))
    code.append(tokiwa_context.marker)
    code.extend(bytes.fromhex("20 02 AF C9 CD"))
    code.extend(bank_cpu_address(tokiwa_loader_offset).to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 01 C9"))

    miss = len(code)
    code.extend(bytes.fromhex("AF C9"))
    for branch, destination in (
        (opening_bank_miss, reply_start),
        (high34_check, high34_start),
        (before_opening_start, reply_start),
        (opening_match_jump, opening_match),
        (high34_miss, reply_start),
        (after_opening_end, reply_start),
        (reply_bank_miss, miss),
        (reply_pointer_miss, miss),
        (reply_before_start, miss),
        (reply_after_end, tokiwa_start),
        (tokiwa_bank_miss, miss),
        (tokiwa_pointer_miss, miss),
        (tokiwa_before_start, miss),
        (tokiwa_after_end, miss),
    ):
        displacement = destination - (branch + 2)
        if not -128 <= displacement <= 127:
            raise ValueError("dialogue loader branch exceeds its signed range")
        code[branch + 1] = displacement & 0xFF
    return bytes(code)


def build(include_shizuna_followup: bool = False) -> tuple[bytes, bytes, dict[str, object]]:
    base = BASE_ROM.read_bytes()
    source = SOURCE_ROM.read_bytes()
    if hashlib.sha256(base).hexdigest() != EXPECTED_V2_6_SHA256:
        raise ValueError("V2.6 ROM does not match the accepted baseline")
    if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM does not match the expected original")
    if len(base) != MENU_EXPANDED_SIZE or not verify_rom(base).passed:
        raise ValueError("V2.6 ROM failed size or checksum verification")
    if base[0x01342D:0x013430] != bytes.fromhex("7C AD 7D"):
        raise ValueError("V2.6 Shizuna reply prefix has an unexpected layout")
    if base[REPLY_TEXT_SPAN[1]] != 0x7F:
        raise ValueError("V2.6 Shizuna reply terminator has an unexpected layout")
    if base[TOKIWA_TEXT_SPAN[1]] != 0x7E:
        raise ValueError("V2.6 Tokiwa dialogue page control has an unexpected layout")
    if include_shizuna_followup and (
        base[0x01346E] != 0x7C
        or base[SHIZUNA_FOLLOWUP_TEXT_SPAN[0]:SHIZUNA_FOLLOWUP_TEXT_SPAN[1]]
        != bytes.fromhex("AD 7D 3B 95 08 18 2F D5 D5 22 08 3C")
        or base[SHIZUNA_FOLLOWUP_TEXT_SPAN[1]] != 0x7F
    ):
        raise ValueError("V2.6 Shizuna follow-up dialogue has an unexpected layout")

    manifest = _load_json(ROOT / "data" / "text_manifest.json")
    record = _require_object(
        next(
            item for item in manifest["records"]
            if isinstance(item, dict) and item.get("id") == RECORD_ID
        ),
        "dialogue record",
    )
    text = _translation_text(record, TEXT_SPAN[0], TEXT_SPAN[1])
    for token, name in FIXED_NAME_TRANSLATIONS.items():
        text = text.replace(token, name)
    glyph_text = text
    for character in ("\n", "「", "」", "！", "？", "。"):
        glyph_text = glyph_text.replace(character, "")

    reply_record = _require_object(
        next(
            item for item in manifest["records"]
            if isinstance(item, dict)
            and item.get("id") == REPLY_RECORD_ID
        ),
        "Shizuna reply dialogue record",
    )
    reply_text = _translation_text(
        reply_record,
        *REPLY_TEXT_SPAN,
    )
    reply_glyph_text = reply_text
    for character in ("\n", "「", "」", "！", "？", "。"):
        reply_glyph_text = reply_glyph_text.replace(character, "")

    tile_candidate = _candidate_excluding_tiles(
        _load_json(ROOT / "data" / "tile_cache_plan_candidate.json"),
        frozenset({MARKER}) | PROTAGONIST_NATIVE_TILES,
    )
    glyph_assets = tuple(
        _load_json(ROOT / "data" / name)
        for name in (
            "chinese_glyphs_oni5_bank04_prologue_v26.json",
            "chinese_glyphs_oni5_bank04_prologue_v261.json",
            "chinese_glyphs_oni5_v261_remaining_dialogues.json",
        )
    )
    glyphs, codes = create_glyph_mapping(glyph_text, glyph_assets, tile_candidate)
    payload = encode_translation_span(
        text,
        codes,
        TEXT_SPAN[1] - TEXT_SPAN[0],
        expected_ellipsis_codes=0,
    )

    reply_candidate = _candidate_excluding_tiles(
        _load_json(ROOT / "data" / "tile_cache_plan_candidate.json"),
        frozenset(
            {
                MARKER,
                REPLY_MARKER,
            }
        )
        | PROTAGONIST_NATIVE_TILES
        | NATIVE_QUOTE_TILES,
    )
    reply_glyph_assets = (
        *glyph_assets,
        _load_json(ROOT / "data" / "chinese_glyphs_oni5_bank04_01342e.json"),
    )
    reply_glyphs, reply_codes = create_glyph_mapping(
        reply_glyph_text,
        reply_glyph_assets,
        reply_candidate,
    )
    reply_payload = encode_translation_span(
        reply_text,
        reply_codes,
        REPLY_TEXT_SPAN[1] - REPLY_TEXT_SPAN[0],
        expected_ellipsis_codes=0,
    )

    tokiwa_record = _require_object(
        next(
            item for item in manifest["records"]
            if isinstance(item, dict)
            and item.get("id") == TOKIWA_RECORD_ID
        ),
        "Tokiwa dialogue record",
    )
    tokiwa_text = _translation_text(
        tokiwa_record,
        *TOKIWA_TEXT_SPAN,
    )
    followup_text = (
        _translation_text(tokiwa_record, *SHIZUNA_FOLLOWUP_TEXT_SPAN)
        if include_shizuna_followup
        else None
    )
    tokiwa_glyph_text = tokiwa_text
    if followup_text is not None:
        followup_glyph_text = followup_text
        for token in SHIZUNA_FOLLOWUP_MACROS:
            followup_glyph_text = followup_glyph_text.replace(token, token[1:-1])
        tokiwa_glyph_text += followup_glyph_text
    for character in ("\n", "「", "」", "！", "？", "。"):
        tokiwa_glyph_text = tokiwa_glyph_text.replace(character, "")
    tokiwa_excluded_tiles = (
        frozenset({MARKER, REPLY_MARKER, TOKIWA_MARKER})
        | PROTAGONIST_NATIVE_TILES
        | NATIVE_QUOTE_TILES
    )
    if include_shizuna_followup:
        tokiwa_excluded_tiles |= NEXT_DIALOGUE_NATIVE_TILES
    tokiwa_candidate = _candidate_excluding_tiles(
        _load_json(ROOT / "data" / "tile_cache_plan_candidate.json"),
        tokiwa_excluded_tiles,
    )
    if include_shizuna_followup:
        tokiwa_glyph_assets = (
            *reply_glyph_assets,
            _load_json(ROOT / "data" / "chinese_glyphs_oni5_bank04_01330d.json"),
            _load_json(ROOT / "data" / "chinese_glyphs_oni5_bank04_01346f.json"),
        )
    else:
        tokiwa_glyph_assets = reply_glyph_assets
    tokiwa_glyphs, tokiwa_codes = create_glyph_mapping(
        tokiwa_glyph_text,
        tokiwa_glyph_assets,
        tokiwa_candidate,
    )
    if include_shizuna_followup and (
        {glyph.tile for glyph in tokiwa_glyphs} & NEXT_DIALOGUE_NATIVE_TILES
    ):
        raise ValueError("V2.6.2 Tokiwa glyph allocation conflicts with the next native page")
    tokiwa_payload = encode_translation_span(
        tokiwa_text,
        tokiwa_codes,
        TOKIWA_TEXT_SPAN[1] - TOKIWA_TEXT_SPAN[0],
        expected_ellipsis_codes=0,
    )
    followup_payload = None
    if followup_text is not None:
        followup_payload = encode_translation_span(
            followup_text,
            tokiwa_codes,
            SHIZUNA_FOLLOWUP_TEXT_SPAN[1] - SHIZUNA_FOLLOWUP_TEXT_SPAN[0],
            expected_ellipsis_codes=0,
            macro_tokens=SHIZUNA_FOLLOWUP_MACROS,
        )

    font = decode_resource(source, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)

    def original_patterns(
        context_glyphs: list[CachedGlyph],
    ) -> tuple[bytes, ...]:
        patterns = tuple(
            font[(glyph.tile - 0x80) * TILE_PATTERN_SIZE:
                 (glyph.tile - 0x7F) * TILE_PATTERN_SIZE]
            for glyph in context_glyphs
        )
        if any(len(pattern) != TILE_PATTERN_SIZE for pattern in patterns):
            raise ValueError("original font is missing a dialogue glyph backup pattern")
        return patterns

    patterns = original_patterns(glyphs)
    reply_patterns = original_patterns(reply_glyphs)
    tokiwa_patterns = original_patterns(tokiwa_glyphs)

    context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x33,
        first_cursor=0xF0,
        restore_cursor=TEXT_SPAN[1] & 0xFF,
        source_offset=TEXT_SPAN[0],
        payload=payload,
        glyphs=tuple(glyphs),
        marker=MARKER,
        restore_from_rom=True,
        original_patterns=patterns,
        return_code=glyphs[0].tile,
        loader_return_b=0xCD,
    )
    reply_context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x34,
        first_cursor=REPLY_FIRST_CURSOR,
        restore_cursor=REPLY_RESTORE_CURSOR,
        source_offset=REPLY_TEXT_SPAN[0],
        payload=reply_payload,
        glyphs=tuple(reply_glyphs),
        marker=REPLY_MARKER,
        restore_from_rom=True,
        original_patterns=reply_patterns,
        return_code=reply_glyphs[0].tile,
        loader_return_b=0xCD,
    )
    tokiwa_context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x34,
        first_cursor=TOKIWA_FIRST_CURSOR,
        restore_cursor=0x7C if include_shizuna_followup else TOKIWA_RESTORE_CURSOR,
        source_offset=TOKIWA_TEXT_SPAN[0],
        payload=tokiwa_payload,
        glyphs=tuple(tokiwa_glyphs),
        marker=TOKIWA_MARKER,
        restore_from_rom=True,
        original_patterns=tokiwa_patterns,
        return_code=tokiwa_glyphs[0].tile,
        loader_return_b=0xCD,
    )
    contexts = (context, reply_context, tokiwa_context)
    context_patterns = (patterns, reply_patterns, tokiwa_patterns)
    loader_offsets: list[int] = []
    loaders: list[bytes] = []
    pattern_offsets: list[int] = []
    pattern_data_list: list[bytes] = []
    original_offsets: list[int] = []
    original_data_list: list[bytes] = []
    restore_offsets: list[int] = []
    restore_helpers: list[bytes] = []
    cursor = COMPONENTS_START
    for current_context, current_patterns in zip(contexts, context_patterns):
        loader_offset = cursor
        preliminary = build_loader_helper(current_context, 0x4100)
        pattern_offset = (loader_offset + len(preliminary) + 0x0F) & ~0x0F
        loader = build_loader_helper(
            current_context,
            bank_cpu_address(pattern_offset),
        )
        pattern_data = b"".join(glyph.pattern for glyph in current_context.glyphs)
        original_offset = (
            pattern_offset + len(pattern_data) + 0x0F
        ) & ~0x0F
        original_data = b"".join(current_patterns)
        restore_offset = (
            original_offset + len(original_data) + 0x0F
        ) & ~0x0F
        restore = build_restore_helper(
            current_context,
            bank_cpu_address(restore_offset),
            bank_cpu_address(original_offset),
        )
        loader_offsets.append(loader_offset)
        loaders.append(loader)
        pattern_offsets.append(pattern_offset)
        pattern_data_list.append(pattern_data)
        original_offsets.append(original_offset)
        original_data_list.append(original_data)
        restore_offsets.append(restore_offset)
        restore_helpers.append(restore)
        cursor = restore_offset + len(restore)

    restore_dispatcher_offset = (cursor + 0x0F) & ~0x0F
    dispatcher = _build_load_dispatcher(
        context,
        loader_offsets[0],
        reply_context,
        loader_offsets[1],
        tokiwa_context,
        loader_offsets[2],
    )
    restore_dispatcher = build_restore_dispatcher(
        contexts,
        tuple(restore_offsets),
    )
    gate = (
        bytes.fromhex("CD")
        + bank_cpu_address(LOAD_DISPATCHER_OFFSET).to_bytes(2, "little")
        + bytes.fromhex("B7 C0 C3 30 40")
    )
    base_load_jump = bytes.fromhex("C3 30 40")
    base_restore_wrapper = bytes.fromhex(
        "F5 FA F2 C4 FE 87 20 04 F1 C3 00 71 F1 C3 B0 48"
    )
    if base[SOURCE_SIZE + 4:SOURCE_SIZE + 7] != base_load_jump:
        raise ValueError("accepted V2.6 load hook has an unexpected layout")
    if base[SOURCE_SIZE + 0x60:SOURCE_SIZE + 0x70] != base_restore_wrapper:
        raise ValueError("accepted V2.6 restore hook has an unexpected layout")
    if base[LOAD_GATE_OFFSET:LOAD_GATE_OFFSET + len(gate)] != b"\xFF" * len(gate):
        raise ValueError("new V2.6.1 load gate overlaps occupied bytes")
    if base[LOAD_DISPATCHER_OFFSET:LOAD_DISPATCHER_OFFSET + len(dispatcher)] != b"\xFF" * len(dispatcher):
        raise ValueError("new V2.6.1 dispatcher overlaps occupied bytes")

    target = bytearray(base)
    target[SOURCE_SIZE + 4:SOURCE_SIZE + 7] = (
        bytes((0xC3,)) + bank_cpu_address(LOAD_GATE_OFFSET).to_bytes(2, "little")
    )
    target[LOAD_GATE_OFFSET:LOAD_GATE_OFFSET + len(gate)] = gate
    target[LOAD_DISPATCHER_OFFSET:LOAD_DISPATCHER_OFFSET + len(dispatcher)] = dispatcher
    for index, current_context in enumerate(contexts):
        _install(
            target,
            loader_offsets[index],
            loaders[index],
            f"{current_context.bank:02X} dialogue loader",
        )
        _install(
            target,
            pattern_offsets[index],
            pattern_data_list[index],
            f"{current_context.bank:02X} dialogue glyph patterns",
        )
        _install(
            target,
            original_offsets[index],
            original_data_list[index],
            f"{current_context.bank:02X} original glyph backup",
        )
        _install(
            target,
            restore_offsets[index],
            restore_helpers[index],
            f"{current_context.bank:02X} dialogue restore helper",
        )
    _install(
        target,
        restore_dispatcher_offset,
        restore_dispatcher,
        "dialogue restore dispatcher",
    )

    restore_router = _restore_router(
        bank_cpu_address(restore_dispatcher_offset),
    )
    restore_router_offset = RESTORE_WRAPPER_OFFSET
    if len(restore_router) > OLD_RESTORE_WRAPPER_OFFSET - restore_router_offset:
        raise ValueError("new V2.6.1 restore router exceeds its reserved space")
    target[SOURCE_SIZE + 0x60:SOURCE_SIZE + 0x63] = (
        bytes((0xC3,)) + bank_cpu_address(restore_router_offset).to_bytes(2, "little")
    )
    _install(target, restore_router_offset, restore_router, "dialogue restore router")
    _install(
        target,
        OLD_RESTORE_WRAPPER_OFFSET,
        base_restore_wrapper,
        "V2.6 restore wrapper copy",
    )
    if followup_payload is not None:
        _install_macro_overrides(target, base, tokiwa_codes)
    target[TEXT_SPAN[0]:TEXT_SPAN[1]] = payload
    target[REPLY_TEXT_SPAN[0]:REPLY_TEXT_SPAN[1]] = reply_payload
    target[TOKIWA_TEXT_SPAN[0]:TOKIWA_TEXT_SPAN[1]] = tokiwa_payload
    if followup_payload is not None:
        target[
            SHIZUNA_FOLLOWUP_TEXT_SPAN[0]:SHIZUNA_FOLLOWUP_TEXT_SPAN[1]
        ] = followup_payload
    mirror_text = MBC1_MIRROR_OFFSET + TEXT_SPAN[0]
    target[mirror_text:mirror_text + len(payload)] = payload
    reply_mirror = MBC1_MIRROR_OFFSET + REPLY_TEXT_SPAN[0]
    target[reply_mirror:reply_mirror + len(reply_payload)] = reply_payload
    tokiwa_mirror = MBC1_MIRROR_OFFSET + TOKIWA_TEXT_SPAN[0]
    target[tokiwa_mirror:tokiwa_mirror + len(tokiwa_payload)] = tokiwa_payload
    if followup_payload is not None:
        followup_mirror = MBC1_MIRROR_OFFSET + SHIZUNA_FOLLOWUP_TEXT_SPAN[0]
        target[followup_mirror:followup_mirror + len(followup_payload)] = followup_payload
        target[
            MBC1_MIRROR_OFFSET + MACRO_ROUTER_HOOK_OFFSET:
            MBC1_MIRROR_OFFSET
            + MACRO_ROUTER_HOOK_OFFSET
            + len(MACRO_ROUTER_HOOK_EXPECTED)
        ] = target[
            MACRO_ROUTER_HOOK_OFFSET:
            MACRO_ROUTER_HOOK_OFFSET + len(MACRO_ROUTER_HOOK_EXPECTED)
        ]
        bank11_mirror = MBC1_MIRROR_OFFSET + MACRO_OVERRIDE_BANK_OFFSET
        target[bank11_mirror:bank11_mirror + ROM_BANK_SIZE] = target[
            MACRO_OVERRIDE_BANK_OFFSET:
            MACRO_OVERRIDE_BANK_OFFSET + ROM_BANK_SIZE
        ]
        bank12_mirror = MBC1_MIRROR_OFFSET + MACRO_OVERRIDE_DATA_BANK_OFFSET
        target[bank12_mirror:bank12_mirror + ROM_BANK_SIZE] = target[
            MACRO_OVERRIDE_DATA_BANK_OFFSET:
            MACRO_OVERRIDE_DATA_BANK_OFFSET + ROM_BANK_SIZE
        ]
    target[
        MBC1_MIRROR_OFFSET + SOURCE_SIZE:
        MBC1_MIRROR_OFFSET + SOURCE_SIZE + ROM_BANK_SIZE
    ] = target[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]

    target = update_checksums(target)
    if not verify_rom(target).passed:
        raise ValueError("V2.6.1 ROM failed checksum verification")
    if target[TEXT_SPAN[1]] != 0x7F:
        raise ValueError("V2.6.1 dialogue overwrote its terminator")
    if target[REPLY_TEXT_SPAN[1]] != 0x7F:
        raise ValueError("V2.6.1 Shizuna reply overwrote its terminator")
    if target[TOKIWA_TEXT_SPAN[1]] != 0x7E:
        raise ValueError("V2.6.1 Tokiwa dialogue overwrote its page control")
    if followup_payload is None and target[0x01346E:0x01347C] != base[0x01346E:0x01347C]:
        raise ValueError("V2.6.1 changed the deferred Shizuna dialogue")
    if followup_payload is not None and (
        target[0x01346E] != 0x7C
        or target[SHIZUNA_FOLLOWUP_TEXT_SPAN[0]:SHIZUNA_FOLLOWUP_TEXT_SPAN[1]]
        != followup_payload
        or target[SHIZUNA_FOLLOWUP_TEXT_SPAN[1]] != 0x7F
    ):
        raise ValueError("V2.6.2 changed the Shizuna dialogue boundaries")
    if target[0x01348D:0x0134AA] != base[0x01348D:0x0134AA]:
        raise ValueError("V2.6.1 changed the unrelated practice dialogue")

    patch = create_bps_patch(base, target)
    if apply_bps_patch(base, patch) != target:
        raise ValueError("V2.6-to-V2.6.1 BPS round-trip failed")
    version = {
        "schema_version": 1,
        "version_id": "V2.6.1-opening-dialogue",
        "parent_version": {
            "version_id": "V2.6-opening-prologue-preview",
            "path": "../roms/oni5_v2_6_opening_prologue.gb",
            "sha256": EXPECTED_V2_6_SHA256,
        },
        "patch": {
            "path": f"../roms/{OUTPUT_PATCH.name}",
            "size_bytes": len(patch),
            "sha256": hashlib.sha256(patch).hexdigest(),
        },
        "target_rom": {
            "path": f"../roms/{OUTPUT_ROM.name}",
            "size_bytes": len(target),
            "sha256": hashlib.sha256(target).hexdigest(),
            "persisted_by_builder": True,
        },
        "runtime_validation": {
            "status": "pending-user-sameboy",
            "tested_rom_sha256": None,
            "required_sameboy_checks": [
                "Apply this BPS to V2.6 and confirm the target ROM SHA-256.",
                "Confirm the dialogue at $0133EF displays 常叶丸 as fixed Chinese glyphs and renders 静那 as Chinese glyphs instead of the local $AD macro.",
                "Confirm the $01342E dialogue displays 静那 and 「真是的，也不提前说一声，我好准备一下。」, ending at the original $013452 terminator.",
                "At the first $01342E glyph, confirm $C4F2 is $88 rather than a stale $85; after the $013452 terminator at cursor $3453, confirm the marker clears and original glyphs are restored.",
                "Confirm the $013459 dialogue displays 常叶丸 and 「突然想见你了。」, preserves the $01346D page transition, then restores original glyphs before the untouched Shizuna text at $01346E.",
                "Confirm the unrelated $01348D practice dialogue matches V2.6, and that later event data and original glyphs remain unchanged.",
            ],
        },
        "features": [
            "opening-dialogue",
            "shizuna-reply-dialogue",
            "tokiwa-visit-dialogue",
        ],
        "text_records": [RECORD_ID, REPLY_RECORD_ID, TOKIWA_RECORD_ID],
        "builder": {"script": "../scripts/build_v2_6_1_single_dialogue.py"},
        "automated_validation": {
            "checksum": "Target ROM passes ROM checksum verification.",
            "bps_round_trip": "Applying the V2.6-to-V2.6.1 BPS reproduces the target ROM.",
        },
    }
    if include_shizuna_followup:
        version["v2_6_2_build_details"] = {
            "macro_table_bank": "0x11",
            "macro_data_bank": "0x12",
            "tokiwa_glyph_tiles": {
                glyph.character: f"0x{glyph.tile:02X}"
                for glyph in tokiwa_glyphs
            },
            "native_tile_avoidance": [
                f"0x{tile:02X}" for tile in sorted(NEXT_DIALOGUE_NATIVE_TILES)
            ],
            "macro_expansions": {
                "$AD": {
                    "characters": "静那",
                    "input_codes": [tokiwa_codes[character] for character in "静那"],
                    "source_cursor_after": "0x70",
                },
                "$95": {
                    "characters": "常叶丸",
                    "input_codes": [tokiwa_codes[character] for character in "常叶丸"],
                    "source_cursor_after": "0x73",
                },
            },
            "shared_bank_0c_macro_table_modified": False,
        }
    return bytes(target), patch, version


def main() -> None:
    target, patch, version = build()
    OUTPUT_ROM.write_bytes(target)
    OUTPUT_PATCH.write_bytes(patch)
    OUTPUT_VERSION.write_text(
        json.dumps(version, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"ROM SHA-256: {hashlib.sha256(target).hexdigest()}")
    print(f"BPS SHA-256: {hashlib.sha256(patch).hexdigest()}")


if __name__ == "__main__":
    main()
