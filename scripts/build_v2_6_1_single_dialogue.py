"""Add only the confirmed $0133EF dialogue to the accepted V2.6 ROM."""
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
from scripts.build_noticeboard_glyph_probe import TILE_PATTERN_SIZE
from scripts.build_opening_text_preview_patch import (
    FONT_BANK,
    FONT_DESCRIPTOR,
    FONT_LENGTH,
    create_glyph_mapping,
)
from scripts.build_text_comparison_pilot import (
    PilotContext,
    build_loader_helper,
    build_restore_helper,
    bank_cpu_address,
)
from scripts.build_v2_6_prologue_patch import (
    ADDITIONAL_DIALOGUE_RECORD_ID,
    ADDITIONAL_DIALOGUE_SPAN,
    EXPECTED_SOURCE_SHA256,
    EXPECTED_V2_6_SHA256,
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
LOAD_GATE_OFFSET = SOURCE_SIZE + 0x0100
LOAD_DISPATCHER_OFFSET = SOURCE_SIZE + 0x0200
RESTORE_WRAPPER_OFFSET = SOURCE_SIZE + 0x3040
OLD_RESTORE_WRAPPER_OFFSET = SOURCE_SIZE + 0x3080
COMPONENTS_START = SOURCE_SIZE + 0x32C0
ALLOCATION_END = SOURCE_SIZE + ROM_BANK_SIZE
MACROS = {"常叶丸": (0x95, 3), "{静那}": (0xAD, 3)}


def _install(rom: bytearray, start: int, data: bytes, label: str) -> None:
    end = start + len(data)
    if end > ALLOCATION_END or rom[start:end] != bytes([0xFF]) * len(data):
        raise ValueError(f"{label} overlaps occupied V2.6 bank-10 bytes")
    rom[start:end] = data


def _build_load_dispatcher(context: PilotContext, loader_offset: int) -> bytes:
    code = bytearray.fromhex("FA AA FF FE")
    code.append(context.bank)
    bank_miss = len(code)
    code.extend((0x20, 0x00))

    code.extend(bytes.fromhex("FA AE FF FE"))
    code.append(0x33)
    high34_check = len(code)
    code.extend((0x20, 0x00))
    code.extend(bytes.fromhex("FA AD FF FE"))
    code.append(0xEF)
    before_start = len(code)
    code.extend((0x38, 0x00))
    to_match = len(code)
    code.extend((0x18, 0x00))

    high34_start = len(code)
    code.extend(bytes.fromhex("FA AE FF FE 34"))
    high_miss = len(code)
    code.extend((0x20, 0x00))
    code.extend(bytes.fromhex("FA AD FF FE 09"))
    after_end = len(code)
    code.extend((0x30, 0x00))

    match_start = len(code)
    code.extend(bytes.fromhex("FA F2 C4 B7 28 02 AF C9 CD"))
    code.extend(bank_cpu_address(loader_offset).to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 01 C9"))
    miss_target = len(code)
    code.extend(bytes.fromhex("AF C9"))

    for branch, target in (
        (bank_miss, miss_target),
        (high34_check, high34_start),
        (before_start, miss_target),
        (to_match, match_start),
        (high_miss, miss_target),
        (after_end, miss_target),
    ):
        displacement = target - (branch + 2)
        if not -128 <= displacement <= 127:
            raise ValueError("dialogue loader branch exceeds its signed range")
        code[branch + 1] = displacement & 0xFF
    return bytes(code)


def _restore_router(context: PilotContext, helper_address: int) -> bytes:
    old_wrapper_address = bank_cpu_address(OLD_RESTORE_WRAPPER_OFFSET)
    code = bytearray.fromhex("F5 FA F2 C4 FE")
    code.append(context.marker)
    code.extend((0x20, 0x00))
    code.extend(bytes.fromhex("FA AD FF FE"))
    code.append(context.restore_cursor)
    code.extend((0x20, 0x00, 0xCD))
    code.extend(helper_address.to_bytes(2, "little"))
    code.extend(bytes.fromhex("F1 C3 00 71"))
    mismatch_target = len(code)
    code.extend(bytes.fromhex("F1 C3"))
    code.extend(old_wrapper_address.to_bytes(2, "little"))
    code[7] = mismatch_target - 8
    code[14] = mismatch_target - 15
    return bytes(code)


def build() -> tuple[bytes, bytes, dict[str, object]]:
    base = BASE_ROM.read_bytes()
    source = SOURCE_ROM.read_bytes()
    if hashlib.sha256(base).hexdigest() != EXPECTED_V2_6_SHA256:
        raise ValueError("V2.6 ROM does not match the accepted baseline")
    if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM does not match the expected original")
    if len(base) != MENU_EXPANDED_SIZE or not verify_rom(base).passed:
        raise ValueError("V2.6 ROM failed size or checksum verification")

    manifest = _load_json(ROOT / "data" / "text_manifest.json")
    record = _require_object(
        next(
            item for item in manifest["records"]
            if isinstance(item, dict) and item.get("id") == RECORD_ID
        ),
        "dialogue record",
    )
    text = _translation_text(record, TEXT_SPAN[0], TEXT_SPAN[1])
    glyph_text = text
    for token in MACROS:
        glyph_text = glyph_text.replace(token, "")
    for character in ("\n", "「", "」", "！", "？", "。"):
        glyph_text = glyph_text.replace(character, "")

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
        macro_tokens=MACROS,
    )

    font = decode_resource(source, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    patterns = tuple(
        font[(glyph.tile - 0x80) * TILE_PATTERN_SIZE:
             (glyph.tile - 0x7F) * TILE_PATTERN_SIZE]
        for glyph in glyphs
    )
    if any(len(pattern) != TILE_PATTERN_SIZE for pattern in patterns):
        raise ValueError("original font is missing a dialogue glyph backup pattern")

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
    components = COMPONENTS_START
    loader_offset = components
    pattern_offset = (loader_offset + len(build_loader_helper(context, 0x4100)) + 0x0F) & ~0x0F
    loader = build_loader_helper(context, bank_cpu_address(pattern_offset))
    pattern_offset = (loader_offset + len(loader) + 0x0F) & ~0x0F
    pattern_data = b"".join(glyph.pattern for glyph in context.glyphs)
    original_offset = (pattern_offset + len(pattern_data) + 0x0F) & ~0x0F
    original_data = b"".join(patterns)
    restore_offset = (original_offset + len(original_data) + 0x0F) & ~0x0F
    restore = build_restore_helper(
        context,
        bank_cpu_address(restore_offset),
        bank_cpu_address(original_offset),
    )

    dispatcher = _build_load_dispatcher(context, loader_offset)
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
    _install(target, loader_offset, loader, "dialogue loader")
    _install(target, pattern_offset, pattern_data, "dialogue glyph patterns")
    _install(target, original_offset, original_data, "original glyph backup")
    _install(target, restore_offset, restore, "dialogue restore helper")

    helper_address = bank_cpu_address(restore_offset)
    restore_router = _restore_router(context, helper_address)
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
    target[TEXT_SPAN[0]:TEXT_SPAN[1]] = payload
    mirror_text = MBC1_MIRROR_OFFSET + TEXT_SPAN[0]
    target[mirror_text:mirror_text + len(payload)] = payload
    target[
        MBC1_MIRROR_OFFSET + SOURCE_SIZE:
        MBC1_MIRROR_OFFSET + SOURCE_SIZE + ROM_BANK_SIZE
    ] = target[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]

    target = update_checksums(target)
    if not verify_rom(target).passed:
        raise ValueError("V2.6.1 ROM failed checksum verification")
    if target[TEXT_SPAN[1]] != 0x7F:
        raise ValueError("V2.6.1 dialogue overwrote its terminator")

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
                "Confirm the dialogue at $0133EF displays in Chinese while preserving its original $95 and $AD macro bytes.",
                "Confirm the $013408 terminator and all other V2.6 dialogue remain unchanged.",
                "Confirm the new glyphs restore before later original dialogue.",
            ],
        },
        "features": ["single-confirmed-dialogue"],
        "text_records": [RECORD_ID],
        "builder": {"script": "../scripts/build_v2_6_1_single_dialogue.py"},
        "automated_validation": {
            "checksum": "Target ROM passes ROM checksum verification.",
            "bps_round_trip": "Applying the V2.6-to-V2.6.1 BPS reproduces the target ROM.",
        },
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
