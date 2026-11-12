"""Build a fixed-cache probe for the woman's two-screen dialogue."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .build_mbc1_expansion_probe import (
        BANK_SWITCH_HELPER_OFFSET,
        ENTRY_OFFSET,
        EXPANDED_SIZE,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
    )
    from .build_noticeboard_glyph_probe import (
        ENTRY_AREA_SIZE,
        ENTRY_CODE,
        POSTLUDE_AREA_SIZE,
        POSTLUDE_CODE,
        RESTORE_HELPER_OFFSET,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        CachedGlyph,
        build_loader_helper,
        build_restore_bank_helper,
    )
    from .build_rom import write_output
    from .rom_checksums import update_checksums, verify_rom
else:
    from build_mbc1_expansion_probe import (
        BANK_SWITCH_HELPER_OFFSET,
        ENTRY_OFFSET,
        EXPANDED_SIZE,
        POSTLUDE_OFFSET,
        SOURCE_SIZE,
        build_expansion_probe,
    )
    from build_noticeboard_glyph_probe import (
        ENTRY_AREA_SIZE,
        ENTRY_CODE,
        POSTLUDE_AREA_SIZE,
        POSTLUDE_CODE,
        RESTORE_HELPER_OFFSET,
        RESTORE_HOOK_EXPECTED,
        RESTORE_HOOK_OFFSET,
        RESTORE_HOOK_PATCH,
        CachedGlyph,
        build_loader_helper,
        build_restore_bank_helper,
    )
    from build_rom import write_output
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
WOMAN_RECORD_ID = "oni5-bank0c-pointer-030e8e"
WOMAN_TEXT = "女子\n「差点便被带去\n宿木堂了。宿木堂\n在何处？不知，听妖怪\n言确有此地」"
WOMAN_SOURCE_OFFSET = 0x30E8E
WOMAN_SOURCE_BYTES = bytes.fromhex(
    "B9 7D 3B 2B 0B 15 12 14 6D 4D 15 10 2B 6E 0B 1E "
    "4D 1A 32 1B 7D 4D 0A 0E 32 31 1C 12 33 6A 08 18 "
    "21 4D 15 10 2B 6E 0B 7D 4D 60 6E 12 0E 08 1B CF "
    "13 09 4D 14 2F 1D 0A 11 6E 7D 4D A0 60 0A 08 1B "
    "18 21 3C 7F"
)
WOMAN_PAYLOAD_SIZE = 68
WOMAN_PATCH_BYTES = 38
WOMAN_FIRST_CHARACTER_CURSOR = 0x8F
WOMAN_RESTORE_CURSOR = 0xB4
SPACE_CODE = 0x4D
LINE_ADVANCE_CODE = 0x7D
TERMINATOR_CODE = 0x7F
ROM_BANK_WINDOW_CPU_START = 0x4000
ROM_BANK_WINDOW_FILE_END = SOURCE_SIZE + 0x4000
PATTERN_ALIGNMENT = 0x100
CUSTOM_BACKUP_BYTES = 27 * 16


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def parse_woman_inputs(
    tile_cache_plan: Any,
    encoding_candidate: Any,
) -> tuple[list[CachedGlyph], bytes]:
    plan = require_object(tile_cache_plan, "tile cache plan")
    candidate = require_object(encoding_candidate, "encoding candidate")
    if plan.get("schema_version") != 1:
        raise ValueError("tile cache plan schema_version must be 1")
    if plan.get("source_rom_sha256") != EXPECTED_SOURCE_SHA256:
        raise ValueError("tile cache plan source ROM hash does not match")
    font = require_object(plan.get("font_resource"), "tile cache plan.font_resource")
    if not isinstance(font.get("decoded_sha256"), str):
        raise ValueError("tile cache plan font_resource must include decoded_sha256")
    if candidate.get("schema_version") != 1:
        raise ValueError("encoding candidate schema_version must be 1")

    records = candidate.get("records")
    if not isinstance(records, list):
        raise ValueError("encoding candidate.records must be a list")
    matches = [
        require_object(value, f"encoding candidate.records[{index}]")
        for index, value in enumerate(records)
        if isinstance(value, dict) and value.get("id") == WOMAN_RECORD_ID
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one encoding record {WOMAN_RECORD_ID!r}")
    record = matches[0]
    if record.get("decoded_text") != WOMAN_TEXT:
        raise ValueError("woman translation does not match the confirmed text")
    if record.get("source_start") != "0x030E8E" or record.get("source_end_exclusive") != "0x030ED2":
        raise ValueError("woman source range does not match the verified 68-byte payload")
    if record.get("source_bytes") != WOMAN_PAYLOAD_SIZE:
        raise ValueError("woman source span must remain 68 bytes")
    if record.get("encoded_bytes") != WOMAN_PATCH_BYTES:
        raise ValueError("woman stream must contain 37 text bytes and one terminator")
    if record.get("padding_count") != 0:
        raise ValueError("woman stream must not contain trailing padding")
    if record.get("patch_end_exclusive") != "0x030EB4":
        raise ValueError("woman terminator must end at cursor 0x0EB4")
    try:
        payload = bytes.fromhex(record["encoded_hex"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("woman encoded_hex is missing or invalid") from exc
    if len(payload) != WOMAN_PATCH_BYTES or payload[-1] != TERMINATOR_CODE:
        raise ValueError("woman stream must contain 38 bytes and end in 0x7F")

    mappings = candidate.get("custom_glyphs")
    if not isinstance(mappings, list):
        raise ValueError("encoding candidate.custom_glyphs must be a list")
    mapping_by_character = {}
    for index, value in enumerate(mappings):
        mapping = require_object(value, f"encoding candidate.custom_glyphs[{index}]")
        character = mapping.get("character")
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(f"encoding candidate glyph {index} has an invalid character")
        if character in mapping_by_character:
            raise ValueError(f"duplicate encoding candidate character {character!r}")
        mapping_by_character[character] = mapping

    expected_body = bytearray()
    custom_characters = []
    seen_characters = set()
    for character in WOMAN_TEXT:
        if character == "\n":
            expected_body.append(LINE_ADVANCE_CODE)
            continue
        if character == " ":
            expected_body.append(SPACE_CODE)
            continue
        mapping = mapping_by_character.get(character)
        if mapping is None:
            raise ValueError(f"woman glyph {character!r} is missing from the encoding candidate")
        try:
            input_code = int(mapping["input_code"], 16)
            tile = int(mapping["tile"], 16)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid input code or tile for {character!r}") from exc
        if input_code + 0x80 != tile:
            raise ValueError(f"glyph {character!r} does not use direct input_code = tile - 0x80")
        expected_body.append(input_code)
        if mapping.get("tile_source") == "custom" and character not in seen_characters:
            custom_characters.append(character)
            seen_characters.add(character)

    expected_payload = bytes(expected_body) + bytes([TERMINATOR_CODE])
    if payload != expected_payload:
        raise ValueError("woman encoded stream does not match its translation and terminator")
    if len(expected_body) != WOMAN_PATCH_BYTES - 1:
        raise ValueError("woman translation body length changed; review terminator and restore cursor")

    entries = plan.get("entries")
    if not isinstance(entries, list):
        raise ValueError("tile cache plan entries must be a list")
    entries_by_character = {}
    for index, value in enumerate(entries):
        entry = require_object(value, f"tile cache plan.entries[{index}]")
        character = entry.get("character")
        if isinstance(character, str):
            entries_by_character.setdefault(character, []).append(entry)

    glyphs = []
    seen_tiles = set()
    for character in custom_characters:
        mapping = mapping_by_character[character]
        try:
            tile = int(mapping["tile"], 16)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid custom tile for {character!r}") from exc
        if not 0x80 <= tile < 0xC0 or tile in seen_tiles:
            raise ValueError(f"invalid or duplicate custom tile 0x{tile:02X} for {character!r}")
        seen_tiles.add(tile)
        entry_matches = [
            entry
            for entry in entries_by_character.get(character, [])
            if entry.get("tile_source") == "custom" and entry.get("tile") == f"0x{tile:02X}"
        ]
        if len(entry_matches) != 1:
            raise ValueError(f"expected one cached custom tile for {character!r}")
        try:
            pattern = bytes.fromhex(entry_matches[0]["glyph_pattern_2bpp_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"missing or invalid 2BPP pattern for {character!r}") from exc
        if len(pattern) != 16:
            raise ValueError(f"2BPP pattern for {character!r} must be 16 bytes")
        glyphs.append(CachedGlyph(character, tile, pattern))

    if len(glyphs) != 27:
        raise ValueError(f"expected 27 custom woman glyphs, found {len(glyphs)}")
    return glyphs, payload


def build_entry_code() -> bytes:
    code = bytearray(ENTRY_CODE)
    if code[19] != 0x34:
        raise ValueError("shared entry code layout changed; woman cursor gate needs review")
    code[19] = WOMAN_FIRST_CHARACTER_CURSOR
    return bytes(code)


def build_restore_helper(restore_cpu_address: int) -> bytes:
    return (
        bytes.fromhex("F5 FA AA FF F5 3E 10 EA 00 20")
        + bytes((0xCD, restore_cpu_address & 0xFF, restore_cpu_address >> 8))
        + bytes.fromhex("F1 EA 00 20 F1 21 03 00 C9")
    )


def build_bank_layout(
    glyphs: list[CachedGlyph],
) -> tuple[int, int, int, bytes, bytes]:
    preliminary_loader = build_loader_helper(glyphs)
    loader_offset = BANK_SWITCH_HELPER_OFFSET
    pattern_offset = align_up(loader_offset + len(preliminary_loader), PATTERN_ALIGNMENT)
    pattern_cpu_address = ROM_BANK_WINDOW_CPU_START + pattern_offset - SOURCE_SIZE
    loader = build_loader_helper(glyphs, pattern_cpu_address)
    pattern_end = pattern_offset + len(glyphs) * 16
    restore_offset = pattern_end
    restore_cpu_address = ROM_BANK_WINDOW_CPU_START + restore_offset - SOURCE_SIZE
    restore_helper = build_restore_bank_helper(
        glyphs,
        WOMAN_RESTORE_CURSOR,
        ROM_BANK_WINDOW_CPU_START + pattern_end - SOURCE_SIZE,
    )
    if loader_offset + len(loader) > pattern_offset:
        raise ValueError("woman loader overlaps its glyph pattern data")
    if pattern_end > restore_offset:
        raise ValueError("woman glyph pattern data overlaps its restore helper")
    if restore_offset + len(restore_helper) > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("woman cache helper exceeds the bank-10 ROM window")
    if restore_cpu_address + len(restore_helper) > 0x8000:
        raise ValueError("woman restore helper exceeds the bank-10 CPU window")
    return pattern_offset, restore_offset, restore_cpu_address, loader, restore_helper


def build_woman_glyph_probe(
    source_rom: bytes,
    glyphs: list[CachedGlyph],
    encoded_payload: bytes,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    if len(glyphs) != 27:
        raise ValueError("woman probe requires all 27 unique custom glyphs")
    if len(encoded_payload) != WOMAN_PATCH_BYTES:
        raise ValueError("woman stream must contain exactly 38 bytes")
    if encoded_payload[-1] != TERMINATOR_CODE:
        raise ValueError("woman stream must end with the 0x7F terminator")
    if encoded_payload[:1] != bytes([glyphs[0].tile - 0x80]):
        raise ValueError("woman stream must start with the first cached glyph")
    if any(len(glyph.pattern) != 16 for glyph in glyphs):
        raise ValueError("every woman glyph pattern must contain exactly 16 bytes")
    if source_rom[
        WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + WOMAN_PAYLOAD_SIZE
    ] != WOMAN_SOURCE_BYTES:
        raise ValueError("woman source bytes do not match the verified original text")
    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("tile restore hook bytes do not match the expected source")
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(build_restore_helper(0x4170))
    ] != bytes([0xFF]) * len(build_restore_helper(0x4170)):
        raise ValueError("tile restore helper area is not entirely unused")

    pattern_offset, restore_offset, restore_cpu, loader, restore_bank_helper = (
        build_bank_layout(glyphs)
    )
    expanded = bytearray(build_expansion_probe(source_rom))
    if expanded[
        pattern_offset:pattern_offset + len(glyphs) * 16
    ] != bytes([0xFF]) * (len(glyphs) * 16):
        raise ValueError("woman glyph pattern area is not entirely unused")
    if expanded[
        restore_offset:restore_offset + len(restore_bank_helper)
    ] != bytes([0xFF]) * len(restore_bank_helper):
        raise ValueError("woman restore bank helper area is not entirely unused")
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = bytes([0xFF]) * ENTRY_AREA_SIZE
    entry_code = build_entry_code()
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + len(entry_code)] = entry_code
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = bytes([0xFF]) * POSTLUDE_AREA_SIZE
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)] = POSTLUDE_CODE
    expanded[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)] = (
        RESTORE_HOOK_PATCH
    )
    restore_helper = build_restore_helper(restore_cpu)
    expanded[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_helper)
    ] = restore_helper
    expanded[BANK_SWITCH_HELPER_OFFSET:BANK_SWITCH_HELPER_OFFSET + len(loader)] = loader
    for index, glyph in enumerate(glyphs):
        start = pattern_offset + index * 16
        expanded[start:start + 16] = glyph.pattern
    expanded[restore_offset:restore_offset + len(restore_bank_helper)] = restore_bank_helper
    expanded[WOMAN_SOURCE_OFFSET:WOMAN_SOURCE_OFFSET + len(encoded_payload)] = encoded_payload
    expanded = bytearray(update_checksums(expanded))
    if len(expanded) != EXPANDED_SIZE or not verify_rom(expanded).passed:
        raise ValueError("generated woman probe failed ROM size or checksum verification")
    return bytes(expanded)


def build_probe_file(
    source_path: Path,
    plan_path: Path,
    encoding_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, int, str]:
    source = source_path.resolve(strict=True)
    plan_file = plan_path.resolve(strict=True)
    encoding_file = encoding_path.resolve(strict=True)
    if not source.is_file() or not plan_file.is_file() or not encoding_file.is_file():
        raise ValueError("source ROM, tile cache plan, and encoding candidate must be files")
    output = output_path.resolve()
    if output in {source, plan_file, encoding_file}:
        raise ValueError("output must differ from all input files")
    if not output.parent.is_dir():
        raise ValueError(f"output directory does not exist: {output.parent}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output}; pass --overwrite to replace it")

    source_rom = source.read_bytes()
    source_digest = hashlib.sha256(source_rom).hexdigest()
    if source_digest != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "source ROM SHA-256 mismatch: "
            f"expected {EXPECTED_SOURCE_SHA256}, found {source_digest}"
        )
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    encoding = json.loads(encoding_file.read_text(encoding="utf-8"))
    glyphs, payload = parse_woman_inputs(plan, encoding)
    probe_rom = build_woman_glyph_probe(source_rom, glyphs, payload)
    write_output(output, probe_rom, overwrite)

    written = output.read_bytes()
    if written != probe_rom:
        raise OSError(f"written probe does not match generated ROM: {output}")
    return output, len(probe_rom), hashlib.sha256(probe_rom).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a separate woman-dialogue probe without trailing-space scrolling."
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
        help="validated glyph and original-tile data",
    )
    parser.add_argument(
        "output_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_t14c6_woman_short_terminator_probe.gb",
        help="new probe ROM output path",
    )
    parser.add_argument(
        "--encoding-candidate",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
        help="candidate encoding containing the confirmed woman dialogue",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output")
    args = parser.parse_args()

    try:
        output, size, digest = build_probe_file(
            args.source_rom,
            args.tile_cache_plan,
            args.encoding_candidate,
            args.output_rom,
            args.overwrite,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {output} ({size} bytes)")
    print(f"SHA-256: {digest}")
    print(f"Backed up {CUSTOM_BACKUP_BYTES} bytes for the 27 custom glyphs.")
    print("A cursor-gated close hook restores the complete cache after the final map cleanup.")


if __name__ == "__main__":
    main()
