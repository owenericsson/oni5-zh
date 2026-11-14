"""Build a guarded ROM pilot for the confirmed main-command menu translations."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .build_mbc1_expansion_probe import (
        GATEWAY_EXPECTED,
        GATEWAY_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
    )
    from .build_noticeboard_glyph_probe import (
        BACKUP_ADDRESS,
        CachedGlyph,
        build_copy_code,
        build_loader_helper,
        tile_vram_address,
    )
    from .build_rom import apply_patch_manifest, build_rom, write_output
    from .compile_tile_cache_plan import compile_tile_cache_plan
    from .compile_translation_encoding import (
        ELIGIBLE_CUSTOM_TILE_IDS,
        SPACE_CODE,
        TERMINATOR_CODE,
        create_glyph_map,
        encode_text,
    )
    from .rom_checksums import update_checksums, verify_rom
else:
    from build_mbc1_expansion_probe import (
        GATEWAY_EXPECTED,
        GATEWAY_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
    )
    from build_noticeboard_glyph_probe import (
        BACKUP_ADDRESS,
        CachedGlyph,
        build_copy_code,
        build_loader_helper,
        tile_vram_address,
    )
    from build_rom import apply_patch_manifest, build_rom, write_output
    from compile_tile_cache_plan import compile_tile_cache_plan
    from compile_translation_encoding import (
        ELIGIBLE_CUSTOM_TILE_IDS,
        SPACE_CODE,
        TERMINATOR_CODE,
        create_glyph_map,
        encode_text,
    )
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
MENU_MANIFEST_PATH = ROOT / "data" / "menu_text_manifest.json"
MENU_GLYPH_ASSET_PATH = ROOT / "data" / "menu_chinese_glyphs.json"

MENU_ITEMS = (
    ("oni5-menu-status", 0x669B, bytes.fromhex("66 07 0B 18 0A 7F"), "状态"),
    ("oni5-menu-spells", 0x66A1, bytes.fromhex("66 06 1A 4D 4D 7F"), "法术"),
    ("oni5-menu-items", 0x66A7, bytes.fromhex("6E 0B 62 4D 4D 7F"), "道具"),
    ("oni5-menu-important-items", 0x66AD, bytes.fromhex("66 06 0B 2E 0B 7F"), "重要物品"),
    ("oni5-menu-equipment", 0x66B3, bytes.fromhex("17 0B 75 4D 4D 7F"), "装备"),
    ("oni5-menu-currency", 0x66B9, bytes.fromhex("14 07 66 0F 36 7F"), "盘缠"),
)
MENU_PADDING_CODE = SPACE_CODE
MENU_TERMINATOR = TERMINATOR_CODE
MENU_GLYPH_COUNT = 14
MENU_EXPANDED_SIZE = 0x100000
MENU_ROM_SIZE_CODE = 0x05
MBC1_MIRROR_OFFSET = 0x80000
MENU_EXTENSION_ALIAS_OFFSET = 0xC0000
ROM_BANK_SIZE = 0x4000
MENU_CONTEXT_DISPATCHER_OFFSET = SOURCE_SIZE
MENU_CONTEXT_DISPATCHER_CPU_ADDRESS = 0x4000
LOADER_CODE_OFFSET = SOURCE_SIZE + 0x0040
LOADER_CODE_CPU_ADDRESS = 0x4040
GLYPH_PATTERN_OFFSET = SOURCE_SIZE + 0x0200
RESTORE_BANK_HELPER_OFFSET = SOURCE_SIZE + 0x0400
RESTORE_BANK_HELPER_CPU_ADDRESS = 0x4400
GLYPH_LOAD_HOOK_OFFSET = 0x19E5
GLYPH_LOAD_HOOK_EXPECTED = bytes.fromhex("E5 D5 F5")
GLYPH_LOAD_HOOK_PATCH = bytes.fromhex("C3 A0 00")
OPEN_HELPER_OFFSET = 0x00A0
OPEN_HELPER_SIZE = 0x20
RESTORE_HOOK_OFFSET = 0x8946
RESTORE_HOOK_EXPECTED = bytes.fromhex("3E FF EA 39 D2")
RESTORE_HOOK_PATCH = bytes.fromhex("CD E0 00 00 00")
RESTORE_HELPER_OFFSET = 0x00E0
RESTORE_HELPER_SIZE = 0x20
TILE_PATTERN_SIZE = 0x10


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def build_menu_candidate(glyph_asset: Any) -> dict[str, Any]:
    glyph_root = require_object(glyph_asset, "glyph asset")
    font = require_object(glyph_root.get("font"), "glyph asset.font")
    token_map, _ = create_glyph_map(glyph_root)
    if len(token_map) != MENU_GLYPH_COUNT:
        raise ValueError(f"menu glyph asset must map exactly {MENU_GLYPH_COUNT} glyphs")
    return {
        "schema_version": 1,
        "font_source_sha256": font.get("source_sha256"),
        "custom_glyphs": token_map,
        "tile_allocation_status": "per_context_mapping_reuses_audited_pool",
        "provisional_custom_tile_pool": {
            "start": "0x80",
            "end_exclusive": "0xC0",
            "count": sum(mapping["tile_source"] == "custom" for mapping in token_map),
            "eligible_count": len(ELIGIBLE_CUSTOM_TILE_IDS),
            "status": "restricted_to_the_main_command_menu_context",
        },
    }


def compile_menu_payloads(
    source_rom: bytes,
    manifest: Any,
    glyph_asset: Any,
) -> tuple[list[dict[str, Any]], list[CachedGlyph]]:
    root = require_object(manifest, "menu manifest")
    if root.get("schema_version") != 1 or root.get("scope") != "oni5-main-command-menu":
        raise ValueError("menu manifest schema or scope is not supported")
    if root.get("source_rom_sha256") != EXPECTED_SOURCE_SHA256:
        raise ValueError("menu manifest source ROM hash does not match the verified original")

    records = root.get("records")
    if not isinstance(records, list):
        raise ValueError("menu manifest.records must be a list")
    records_by_id = {}
    for index, value in enumerate(records):
        record = require_object(value, f"menu manifest.records[{index}]")
        record_id = record.get("id")
        if not isinstance(record_id, str) or record_id in records_by_id:
            raise ValueError(f"menu manifest.records[{index}] has a missing or duplicate id")
        records_by_id[record_id] = record

    candidate = build_menu_candidate(glyph_asset)
    token_map, code_by_character = create_glyph_map(glyph_asset)
    cache_plan = compile_tile_cache_plan(source_rom, candidate, glyph_asset)
    cache_entries = cache_plan.get("entries")
    if not isinstance(cache_entries, list):
        raise ValueError("compiled tile cache plan.entries must be a list")
    entries_by_character = {}
    for index, value in enumerate(cache_entries):
        entry = require_object(value, f"tile cache plan.entries[{index}]")
        character = entry.get("character")
        if not isinstance(character, str) or character in entries_by_character:
            raise ValueError(f"tile cache plan.entries[{index}] has a missing or duplicate character")
        entries_by_character[character] = entry

    glyphs = []
    seen_tiles = set()
    for index, mapping in enumerate(token_map):
        character = mapping["character"]
        if mapping["tile_source"] != "custom":
            raise ValueError(f"menu glyph {character!r} must use a custom tile")
        tile = int(mapping["tile"], 16)
        input_code = int(mapping["input_code"], 16)
        if tile in seen_tiles or tile < 0x80 or tile >= 0xC0:
            raise ValueError(f"menu glyph {character!r} has a duplicate or invalid tile")
        if input_code != tile - 0x80:
            raise ValueError(f"menu glyph {character!r} must use tile - 0x80 as its input code")
        seen_tiles.add(tile)
        entry = entries_by_character.get(character)
        if (
            entry is None
            or entry.get("tile_source") != "custom"
            or entry.get("tile") != mapping["tile"]
        ):
            raise ValueError(f"tile cache plan does not match menu glyph {character!r}")
        try:
            pattern = bytes.fromhex(entry["glyph_pattern_2bpp_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"menu glyph {character!r} has no valid 2BPP pattern") from exc
        if len(pattern) != TILE_PATTERN_SIZE:
            raise ValueError(f"menu glyph {character!r} pattern must be 16 bytes")
        glyphs.append(CachedGlyph(character, tile, pattern))

    compiled_records = []
    expected_ids = {item[0] for item in MENU_ITEMS}
    if set(records_by_id) != expected_ids:
        raise ValueError("menu manifest must contain exactly the six confirmed menu records")

    for record_id, offset, expected_source, expected_text in MENU_ITEMS:
        record = records_by_id[record_id]
        source = require_object(record.get("source"), f"{record_id}.source")
        payload_source = require_object(source.get("payload"), f"{record_id}.source.payload")
        if source.get("kind") != "rom_string_table":
            raise ValueError(f"{record_id}: unsupported source kind")
        if source.get("rom_offset") != f"0x{offset:06X}":
            raise ValueError(f"{record_id}: source offset does not match the verified menu table")
        if payload_source.get("start") != f"0x{offset:06X}":
            raise ValueError(f"{record_id}: payload start does not match the verified menu table")
        payload_end = offset + len(expected_source)
        if payload_source.get("end_exclusive") != f"0x{payload_end:06X}":
            raise ValueError(f"{record_id}: payload end does not match the verified menu table")
        if payload_source.get("terminator") != f"0x{MENU_TERMINATOR:02X}":
            raise ValueError(f"{record_id}: unsupported source terminator")
        if payload_source.get("raw_hex") != expected_source.hex(" ").upper():
            raise ValueError(f"{record_id}: source bytes do not match the verified menu table")
        if source_rom[offset:payload_end] != expected_source:
            raise ValueError(f"{record_id}: original ROM bytes do not match the menu manifest")

        translation = require_object(record.get("translation"), f"{record_id}.translation")
        if translation.get("status") != "confirmed":
            raise ValueError(f"{record_id}: translation must be confirmed")
        segments = translation.get("segments")
        if not isinstance(segments, list) or len(segments) != 1:
            raise ValueError(f"{record_id}: expected exactly one confirmed translation segment")
        segment = require_object(segments[0], f"{record_id}.translation.segments[0]")
        if segment.get("source_start") != f"0x{offset:06X}":
            raise ValueError(f"{record_id}: translation source start does not match")
        if segment.get("source_end_exclusive") != f"0x{payload_end - 1:06X}":
            raise ValueError(f"{record_id}: translation must stop before the original terminator")
        text = segment.get("text")
        if text != expected_text:
            raise ValueError(f"{record_id}: translation does not match the user-confirmed text")

        body = encode_text(text, code_by_character)
        source_text_length = len(expected_source) - 1
        if len(body) > source_text_length:
            raise ValueError(f"{record_id}: encoded translation exceeds its original menu slot")
        padding_count = source_text_length - len(body)
        payload = bytes(body + [MENU_PADDING_CODE] * padding_count + [MENU_TERMINATOR])
        if len(payload) != len(expected_source):
            raise ValueError(f"{record_id}: encoded menu payload changed its original length")
        compiled_records.append(
            {
                "id": record_id,
                "offset": offset,
                "source_hex": expected_source.hex(" ").upper(),
                "encoded_hex": payload.hex(" ").upper(),
                "text": text,
                "padding_count": padding_count,
            }
        )

    if len(entries_by_character) != len(glyphs):
        raise ValueError("tile cache plan contains unexpected menu glyph entries")
    return compiled_records, glyphs


def build_open_helper(
    dispatcher_cpu_address: int = MENU_CONTEXT_DISPATCHER_CPU_ADDRESS,
) -> bytes:
    if not 0 <= dispatcher_cpu_address <= 0xFFFF:
        raise ValueError("dispatcher CPU address must fit in 16 bits")
    code = bytearray.fromhex(
        "F5 7C FE 66 20 00 7D FE 9C 20 00 "
        "F3 3E 10 EA 00 20"
    )
    code.extend(
        bytes((0xCD, dispatcher_cpu_address & 0xFF, dispatcher_cpu_address >> 8))
    )
    code.extend(bytes.fromhex("EA 00 20 FB F1 E5 D5 F5 C3 E8 19"))
    skip_target = len(code) - 7
    for offset in (5, 10):
        displacement = skip_target - offset - 1
        if not -128 <= displacement <= 127:
            raise ValueError("menu context branch exceeds the signed relative-jump range")
        code[offset] = displacement & 0xFF
    return bytes(code)


def build_menu_context_dispatcher(
    loader_cpu_address: int = LOADER_CODE_CPU_ADDRESS,
) -> bytes:
    if not 0 <= loader_cpu_address <= 0xFFFF:
        raise ValueError("loader CPU address must fit in 16 bits")
    code = bytearray.fromhex("FA F2 C4 B7 28 03 3E 01 C9")
    code.extend((0xC3, loader_cpu_address & 0xFF, loader_cpu_address >> 8))
    return bytes(code)


def build_restore_bank_helper(
    glyphs: list[CachedGlyph],
    helper_cpu_address: int = RESTORE_BANK_HELPER_CPU_ADDRESS,
) -> bytes:
    if not glyphs:
        raise ValueError("at least one menu glyph is required for restoration")
    code = bytearray.fromhex("C5 D5 F5 FA F2 C4 FE")
    code.append(glyphs[0].tile)
    code.extend(bytes.fromhex("C2 00 00"))
    for index, glyph in enumerate(glyphs):
        code.extend(
            build_copy_code(
                BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
                tile_vram_address(glyph.tile),
            )
        )
    code.extend(bytes.fromhex("AF EA F2 C4"))
    common_offset = len(code)
    code.extend(bytes.fromhex("F1 D1 C1 C9"))
    target = helper_cpu_address + common_offset
    if target > 0xFFFF:
        raise ValueError("restore helper return target exceeds the 16-bit address range")
    code[9:11] = bytes((target & 0xFF, target >> 8))
    return bytes(code)


def build_restore_hook_helper(
    bank_helper_cpu_address: int = RESTORE_BANK_HELPER_CPU_ADDRESS,
) -> bytes:
    return (
        bytes.fromhex("F5 C5 D5 E5 F3 3E 10 EA 00 20")
        + bytes((0xCD, bank_helper_cpu_address & 0xFF, bank_helper_cpu_address >> 8))
        + bytes.fromhex("3E 02 EA 00 20 FB E1 D1 C1 F1 3E FF EA 39 D2 C9")
    )


def build_menu_pilot(
    source_rom: bytes,
    menu_manifest: Any,
    glyph_asset: Any,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    source_hash = hashlib.sha256(source_rom).hexdigest()
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ROM SHA-256 does not match the verified original")
    if source_rom[
        GLYPH_LOAD_HOOK_OFFSET:
        GLYPH_LOAD_HOOK_OFFSET + len(GLYPH_LOAD_HOOK_EXPECTED)
    ] != GLYPH_LOAD_HOOK_EXPECTED:
        raise ValueError("menu glyph-load hook bytes do not match the verified source")
    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("menu restore hook bytes do not match the verified source")

    compiled_records, glyphs = compile_menu_payloads(source_rom, menu_manifest, glyph_asset)
    open_helper = build_open_helper()
    context_dispatcher = build_menu_context_dispatcher()
    restore_hook_helper = build_restore_hook_helper()
    loader_helper = build_loader_helper(
        glyphs,
        GLYPH_PATTERN_OFFSET - SOURCE_SIZE + 0x4000,
        return_a_value=0x01,
    )
    restore_bank_helper = build_restore_bank_helper(glyphs)
    if source_rom[
        OPEN_HELPER_OFFSET:OPEN_HELPER_OFFSET + OPEN_HELPER_SIZE
    ] != bytes([0xFF]) * OPEN_HELPER_SIZE:
        raise ValueError("menu open helper area is not entirely unused")
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + RESTORE_HELPER_SIZE
    ] != bytes([0xFF]) * RESTORE_HELPER_SIZE:
        raise ValueError("menu restore helper area is not entirely unused")
    if len(open_helper) > OPEN_HELPER_SIZE:
        raise ValueError("menu open helper overlaps the restore helper area")
    if len(restore_hook_helper) > RESTORE_HELPER_SIZE:
        raise ValueError("menu restore helper exceeds its reserved area")
    if (
        MENU_CONTEXT_DISPATCHER_OFFSET + len(context_dispatcher)
        > LOADER_CODE_OFFSET
    ):
        raise ValueError("menu context dispatcher overlaps the glyph loader")
    if LOADER_CODE_OFFSET + len(loader_helper) > GLYPH_PATTERN_OFFSET:
        raise ValueError("menu glyph loader overlaps its pattern data")
    if (
        GLYPH_PATTERN_OFFSET + len(glyphs) * TILE_PATTERN_SIZE
        > RESTORE_BANK_HELPER_OFFSET
    ):
        raise ValueError("menu glyph patterns overlap the bank-10 restore helper")
    if RESTORE_BANK_HELPER_OFFSET + len(restore_bank_helper) > MENU_EXPANDED_SIZE:
        raise ValueError("menu restore helper exceeds the expanded ROM")

    expansion = build_expansion_probe(source_rom)
    expanded = bytearray([0xFF]) * MENU_EXPANDED_SIZE
    expanded[:len(expansion)] = expansion
    expanded[GATEWAY_OFFSET:GATEWAY_OFFSET + len(GATEWAY_EXPECTED)] = GATEWAY_EXPECTED
    expanded[OPEN_HELPER_OFFSET:OPEN_HELPER_OFFSET + OPEN_HELPER_SIZE] = (
        bytes([0xFF]) * OPEN_HELPER_SIZE
    )
    expanded[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + RESTORE_HELPER_SIZE] = (
        bytes([0xFF]) * RESTORE_HELPER_SIZE
    )
    expanded[SOURCE_SIZE:MENU_EXPANDED_SIZE] = bytes([0xFF]) * (
        MENU_EXPANDED_SIZE - SOURCE_SIZE
    )
    expanded[OPEN_HELPER_OFFSET:OPEN_HELPER_OFFSET + len(open_helper)] = open_helper
    expanded[
        GLYPH_LOAD_HOOK_OFFSET:
        GLYPH_LOAD_HOOK_OFFSET + len(GLYPH_LOAD_HOOK_PATCH)
    ] = GLYPH_LOAD_HOOK_PATCH
    expanded[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_hook_helper)
    ] = restore_hook_helper
    expanded[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)
    ] = RESTORE_HOOK_PATCH
    expanded[
        MENU_CONTEXT_DISPATCHER_OFFSET:
        MENU_CONTEXT_DISPATCHER_OFFSET + len(context_dispatcher)
    ] = context_dispatcher
    expanded[LOADER_CODE_OFFSET:LOADER_CODE_OFFSET + len(loader_helper)] = loader_helper
    for index, glyph in enumerate(glyphs):
        pattern_offset = GLYPH_PATTERN_OFFSET + index * TILE_PATTERN_SIZE
        expanded[pattern_offset:pattern_offset + TILE_PATTERN_SIZE] = glyph.pattern
    expanded[
        RESTORE_BANK_HELPER_OFFSET:
        RESTORE_BANK_HELPER_OFFSET + len(restore_bank_helper)
    ] = restore_bank_helper
    for record in compiled_records:
        offset = record["offset"]
        payload = bytes.fromhex(record["encoded_hex"])
        expanded[offset:offset + len(payload)] = payload

    expanded[0x148] = MENU_ROM_SIZE_CODE
    expanded[MBC1_MIRROR_OFFSET:MBC1_MIRROR_OFFSET + SOURCE_SIZE] = expanded[:SOURCE_SIZE]
    expanded[
        MBC1_MIRROR_OFFSET + 0x0134:
        MBC1_MIRROR_OFFSET + 0x0150
    ] = source_rom[0x0134:0x0150]
    expanded[
        MENU_EXTENSION_ALIAS_OFFSET:
        MENU_EXTENSION_ALIAS_OFFSET + ROM_BANK_SIZE
    ] = expanded[SOURCE_SIZE:SOURCE_SIZE + ROM_BANK_SIZE]

    result = update_checksums(expanded)
    if len(result) != MENU_EXPANDED_SIZE or not verify_rom(result).passed:
        raise ValueError("menu pilot failed ROM size or checksum verification")
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
                "id": f"menu-pilot-range-{len(patches) + 1:03d}",
                "offset": f"0x{start:06X}",
                "expected_hex": bytes(baseline[start:offset]).hex(" ").upper(),
                "replacement_hex": target_rom[start:offset].hex(" ").upper(),
            }
        )
    if not patches:
        raise ValueError("menu pilot produced no ROM changes")
    return {
        "schema_version": 1,
        "source_rom_sha256": hashlib.sha256(source_rom).hexdigest(),
        "target_size": f"0x{len(target_rom):X}",
        "extension_fill_byte": "0xFF",
        "scope": (
            "confirmed main-command menu labels, temporary glyph cache, "
            "and MBC1 bank mirrors"
        ),
        "patches": patches,
    }


def build_pilot_files(
    source_path: Path,
    manifest_path: Path,
    output_path: Path,
    overwrite: bool = False,
    menu_manifest_path: Path = MENU_MANIFEST_PATH,
    glyph_asset_path: Path = MENU_GLYPH_ASSET_PATH,
) -> tuple[Path, Path, int, str, int]:
    source = source_path.resolve(strict=True)
    menu_file = menu_manifest_path.resolve(strict=True)
    glyph_file = glyph_asset_path.resolve(strict=True)
    manifest_output = manifest_path.resolve()
    output = output_path.resolve()
    inputs = {source, menu_file, glyph_file}
    if (
        manifest_output in inputs
        or output in inputs
        or manifest_output == output
    ):
        raise ValueError("manifest and output paths must differ from each other and all inputs")
    if not manifest_output.parent.is_dir() or not output.parent.is_dir():
        raise ValueError("manifest and ROM output directories must already exist")
    if not overwrite and (manifest_output.exists() or output.exists()):
        raise FileExistsError("manifest or ROM output already exists; pass --overwrite to replace")

    source_rom = source.read_bytes()
    source_digest = hashlib.sha256(source_rom).hexdigest()
    if source_digest != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "source ROM SHA-256 mismatch: "
            f"expected {EXPECTED_SOURCE_SHA256}, found {source_digest}"
        )
    menu_manifest = json.loads(menu_file.read_text(encoding="utf-8"))
    glyph_asset = json.loads(glyph_file.read_text(encoding="utf-8"))
    pilot_rom = build_menu_pilot(source_rom, menu_manifest, glyph_asset)
    patch_manifest = create_patch_manifest(source_rom, pilot_rom)
    rebuilt = update_checksums(apply_patch_manifest(source_rom, patch_manifest))
    if rebuilt != pilot_rom:
        raise ValueError("patch manifest does not reproduce the generated menu pilot ROM")

    manifest_bytes = (
        json.dumps(patch_manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    write_output(manifest_output, manifest_bytes, overwrite)
    built_path, size, digest, patch_count = build_rom(
        source,
        manifest_output,
        output,
        overwrite,
    )
    if built_path.read_bytes() != pilot_rom:
        raise OSError("manifest-built ROM differs from the directly generated menu pilot")
    return built_path, manifest_output, size, digest, patch_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a guarded 1 MiB ROM pilot for the confirmed main-command menu."
    )
    parser.add_argument(
        "source_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
        help="verified original ROM",
    )
    parser.add_argument(
        "patch_manifest",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_menu_pilot_patches.json",
        help="new guarded patch manifest output",
    )
    parser.add_argument(
        "output_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_menu_pilot.gb",
        help="new menu pilot ROM output",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    args = parser.parse_args()

    try:
        output, manifest, size, digest, patch_count = build_pilot_files(
            args.source_rom,
            args.patch_manifest,
            args.output_rom,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote menu pilot ROM {output} ({size} bytes), {patch_count} guarded patch range(s)")
    print(f"Wrote patch manifest {manifest}")
    print(f"SHA-256: {digest}")
    print(
        "Scope includes the six confirmed menu labels, temporary glyph cache, "
        "and MBC1 bank mirrors."
    )


if __name__ == "__main__":
    main()
