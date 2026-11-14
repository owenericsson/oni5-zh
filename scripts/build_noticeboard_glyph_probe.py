"""Build an automatic multi-glyph loading and restoration probe for the noticeboard."""
import argparse
import hashlib
import json
from dataclasses import dataclass
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
    from build_rom import write_output
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
ENTRY_AREA_SIZE = 0x20
POSTLUDE_AREA_SIZE = 0x20
GLYPH_PATTERN_OFFSET = 0x40100
BACKUP_ADDRESS = 0xC000
TILE_PATTERN_SIZE = 0x10
NOTICEBOARD_RECORD_ID = "oni5-bank0c-pointer-030e33"
NOTICEBOARD_TEXT = "欢迎来到小中村"
NOTICEBOARD_SOURCE_OFFSET = 0x30E33
NOTICEBOARD_SOURCE_BYTES = bytes.fromhex("12 1D 0E C6 1E 2E 0B 12 17 7F")
NOTICEBOARD_PAYLOAD_SIZE = len(NOTICEBOARD_SOURCE_BYTES)
NOTICEBOARD_PADDING_CODE = 0x4D
NOTICEBOARD_TERMINATOR = 0x7F
RESTORE_HOOK_OFFSET = 0x1BE8
RESTORE_HOOK_EXPECTED = bytes.fromhex("21 03 00")
RESTORE_HOOK_PATCH = bytes.fromhex("CD 61 00")
RESTORE_HELPER_OFFSET = 0x0061
RESTORE_BANK_HELPER_OFFSET = SOURCE_SIZE + 0x0170
RESTORE_BANK_HELPER_CPU_ADDRESS = 0x4170
RESTORE_MARKER_ADDRESS = 0xC4F2
RESTORE_CURSOR_ADDRESS = 0xFFAD
RESTORE_CURSOR_VALUE = 0x3D
FIRST_GLYPH_TILE = 0xA5
ENTRY_CODE = bytes.fromhex(
    "F5 FA AA FF FE 0C 20 4F FA AE FF FE 0E 20 48 "
    "FA AD FF FE 34 20 41 06 CD C3 E0 00"
)
POSTLUDE_CODE = bytes.fromhex(
    "FA AA FF F5 3E 10 EA 00 20 CD 00 40 F1 EA 00 20 "
    "F1 FA F2 C4 C3 0C 18 F1 FE 60 D2 15 18 C3 07 18"
)
RESTORE_HELPER = bytes.fromhex(
    "F5 FA AA FF F5 3E 10 EA 00 20 CD 70 41 F1 EA 00 20 "
    "F1 21 03 00 C9"
)


@dataclass(frozen=True)
class CachedGlyph:
    character: str
    tile: int
    pattern: bytes


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def parse_noticeboard_inputs(
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
        if isinstance(value, dict) and value.get("id") == NOTICEBOARD_RECORD_ID
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one encoding record {NOTICEBOARD_RECORD_ID!r}")
    record = matches[0]
    if record.get("decoded_text") != NOTICEBOARD_TEXT:
        raise ValueError("noticeboard translation does not match the confirmed text")
    if record.get("source_start") != "0x030E33" or record.get("source_end_exclusive") != "0x030E3D":
        raise ValueError("noticeboard source range does not match the verified 10-byte payload")
    if record.get("source_bytes") != NOTICEBOARD_PAYLOAD_SIZE:
        raise ValueError("noticeboard source span must remain 10 bytes")
    if record.get("encoded_bytes") != NOTICEBOARD_PAYLOAD_SIZE:
        raise ValueError("noticeboard encoded stream must remain 10 bytes")
    if record.get("padding_count") != 2:
        raise ValueError("noticeboard payload must retain two padding cells")
    try:
        payload = bytes.fromhex(record["encoded_hex"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("noticeboard encoded_hex is missing or invalid") from exc
    if len(payload) != NOTICEBOARD_PAYLOAD_SIZE:
        raise ValueError("noticeboard payload must contain exactly 10 bytes")
    if payload[-3:-1] != bytes([NOTICEBOARD_PADDING_CODE]) * 2:
        raise ValueError("noticeboard payload must retain two verified blank cells")
    if payload[-1] != NOTICEBOARD_TERMINATOR:
        raise ValueError("noticeboard payload must end with the original 0x7F terminator")

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
    encoded_character_codes = []
    for character in NOTICEBOARD_TEXT:
        mapping = mapping_by_character.get(character)
        if mapping is None or mapping.get("tile_source") != "custom":
            raise ValueError(f"noticeboard glyph {character!r} must have a custom tile mapping")
        try:
            tile = int(mapping["tile"], 16)
            input_code = int(mapping["input_code"], 16)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid tile or input code for {character!r}") from exc
        if not 0x80 <= tile < 0xC0 or input_code + 0x80 != tile:
            raise ValueError(f"glyph {character!r} does not use direct input_code = tile - 0x80")
        if tile in seen_tiles:
            raise ValueError(f"duplicate noticeboard custom tile 0x{tile:02X}")
        seen_tiles.add(tile)
        encoded_character_codes.append(input_code)

        matches_for_character = [
            entry
            for entry in entries_by_character.get(character, [])
            if entry.get("tile_source") == "custom" and entry.get("tile") == f"0x{tile:02X}"
        ]
        if len(matches_for_character) != 1:
            raise ValueError(f"expected one cached custom tile for {character!r} at 0x{tile:02X}")
        try:
            pattern = bytes.fromhex(matches_for_character[0]["glyph_pattern_2bpp_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"missing or invalid 2BPP pattern for {character!r}") from exc
        if len(pattern) != TILE_PATTERN_SIZE:
            raise ValueError(f"2BPP pattern for {character!r} must be 16 bytes")
        glyphs.append(CachedGlyph(character, tile, pattern))

    if payload[:len(encoded_character_codes)] != bytes(encoded_character_codes):
        raise ValueError("noticeboard payload codes do not match the direct tile mapping")
    return glyphs, payload


def tile_vram_address(tile: int) -> int:
    if not 0x80 <= tile < 0xC0:
        raise ValueError(f"custom tile 0x{tile:02X} is outside 0x80-0xBF")
    return 0x8000 + tile * TILE_PATTERN_SIZE


def build_copy_code(source_address: int, destination_address: int) -> bytes:
    return (
        bytes((0x21, source_address & 0xFF, source_address >> 8))
        + bytes((0x11, destination_address & 0xFF, destination_address >> 8))
        + bytes.fromhex("01 10 00 CD 21 05")
    )


def build_loader_helper(
    glyphs: list[CachedGlyph],
    pattern_cpu_address: int = 0x4100,
    return_a_value: int | None = None,
) -> bytes:
    code = bytearray.fromhex("C5 D5 E5")
    for index, glyph in enumerate(glyphs):
        code.extend(
            build_copy_code(
                tile_vram_address(glyph.tile),
                BACKUP_ADDRESS + index * TILE_PATTERN_SIZE,
            )
        )
    for index, glyph in enumerate(glyphs):
        code.extend(
            build_copy_code(
                pattern_cpu_address + index * TILE_PATTERN_SIZE,
                tile_vram_address(glyph.tile),
            )
        )
    code.extend(bytes((0x3E, glyphs[0].tile)) + bytes.fromhex("EA F2 C4"))
    if return_a_value is not None:
        if not 0 <= return_a_value <= 0xFF:
            raise ValueError("loader return A value must fit in one byte")
        code.extend((0x3E, return_a_value))
    code.extend(bytes.fromhex("E1 D1 C1 C9"))
    return bytes(code)


def build_restore_bank_helper(
    glyphs: list[CachedGlyph],
    restore_cursor_value: int = RESTORE_CURSOR_VALUE,
    helper_cpu_address: int = RESTORE_BANK_HELPER_CPU_ADDRESS,
) -> bytes:
    if not glyphs:
        raise ValueError("at least one glyph is required for restoration")
    use_absolute_branches = len(glyphs) > 9
    code = bytearray.fromhex("C5 D5 F5 FA F2 C4 FE")
    code.append(glyphs[0].tile)
    if use_absolute_branches:
        code.extend(bytes.fromhex("C2 00 00 FA AD FF FE"))
        code.append(restore_cursor_value)
        code.extend(bytes.fromhex("C2 00 00"))
        branch_offsets = (9, 17)
    else:
        code.extend(bytes.fromhex("20 00 FA AD FF FE"))
        code.extend(bytes((restore_cursor_value, 0x20, 0x00)))
        branch_offsets = (8, 15)
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
    if use_absolute_branches:
        target = helper_cpu_address + common_offset
        if target > 0xFFFF:
            raise ValueError("restore helper return target exceeds the 16-bit address range")
        for operand_offset in branch_offsets:
            code[operand_offset:operand_offset + 2] = bytes(
                (target & 0xFF, target >> 8)
            )
    else:
        for branch_offset in branch_offsets:
            displacement = common_offset - (branch_offset + 2)
            if not -128 <= displacement <= 127:
                raise ValueError("restore helper branch exceeds the signed relative-jump range")
            code[branch_offset + 1] = displacement & 0xFF
    return bytes(code)


def build_noticeboard_glyph_probe(
    source_rom: bytes,
    glyphs: list[CachedGlyph],
    encoded_payload: bytes,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    if len(glyphs) != len(NOTICEBOARD_TEXT):
        raise ValueError(f"noticeboard probe requires {len(NOTICEBOARD_TEXT)} glyphs")
    if "".join(glyph.character for glyph in glyphs) != NOTICEBOARD_TEXT:
        raise ValueError("noticeboard glyphs must be ordered as the confirmed translation")
    if len(encoded_payload) != NOTICEBOARD_PAYLOAD_SIZE:
        raise ValueError("noticeboard payload must contain exactly 10 bytes")
    if encoded_payload[-3:-1] != bytes([NOTICEBOARD_PADDING_CODE]) * 2:
        raise ValueError("noticeboard payload must retain two padding cells")
    if encoded_payload[-1] != NOTICEBOARD_TERMINATOR:
        raise ValueError("noticeboard payload must preserve the 0x7F terminator")
    if bytes(glyph.tile for glyph in glyphs) != bytes(
        encoded_payload[index] + 0x80 for index in range(len(NOTICEBOARD_TEXT))
    ):
        raise ValueError("noticeboard glyph sequence does not match its encoded input codes")
    if len({glyph.tile for glyph in glyphs}) != len(glyphs):
        raise ValueError("noticeboard glyph tiles must be unique")
    for glyph in glyphs:
        if len(glyph.pattern) != TILE_PATTERN_SIZE:
            raise ValueError(f"glyph pattern for {glyph.character!r} must contain 16 bytes")
    if source_rom[
        NOTICEBOARD_SOURCE_OFFSET:
        NOTICEBOARD_SOURCE_OFFSET + NOTICEBOARD_PAYLOAD_SIZE
    ] != NOTICEBOARD_SOURCE_BYTES:
        raise ValueError("noticeboard source bytes do not match the verified original text")
    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("tile restore hook bytes do not match the expected source")
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(RESTORE_HELPER)
    ] != bytes([0xFF]) * len(RESTORE_HELPER):
        raise ValueError("tile restore helper area is not entirely unused")

    loader_helper = build_loader_helper(glyphs)
    restore_bank_helper = build_restore_bank_helper(glyphs)
    expanded = bytearray(build_expansion_probe(source_rom))
    if expanded[
        RESTORE_BANK_HELPER_OFFSET:
        RESTORE_BANK_HELPER_OFFSET + len(restore_bank_helper)
    ] != bytes([0xFF]) * len(restore_bank_helper):
        raise ValueError("tile restore bank helper area is not entirely unused")
    if len(loader_helper) > GLYPH_PATTERN_OFFSET - SOURCE_SIZE:
        raise ValueError("multi-glyph loader exceeds its reserved bank-10 code area")
    if GLYPH_PATTERN_OFFSET + len(glyphs) * TILE_PATTERN_SIZE > RESTORE_BANK_HELPER_OFFSET:
        raise ValueError("glyph pattern data overlaps the restore helper")
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = bytes([0xFF]) * ENTRY_AREA_SIZE
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + len(ENTRY_CODE)] = ENTRY_CODE
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = bytes([0xFF]) * POSTLUDE_AREA_SIZE
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)] = POSTLUDE_CODE
    expanded[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)] = (
        RESTORE_HOOK_PATCH
    )
    expanded[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(RESTORE_HELPER)] = RESTORE_HELPER
    expanded[
        RESTORE_BANK_HELPER_OFFSET:
        RESTORE_BANK_HELPER_OFFSET + len(restore_bank_helper)
    ] = restore_bank_helper
    expanded[BANK_SWITCH_HELPER_OFFSET:BANK_SWITCH_HELPER_OFFSET + len(loader_helper)] = (
        loader_helper
    )
    for index, glyph in enumerate(glyphs):
        pattern_offset = GLYPH_PATTERN_OFFSET + index * TILE_PATTERN_SIZE
        expanded[pattern_offset:pattern_offset + TILE_PATTERN_SIZE] = glyph.pattern
    expanded[
        NOTICEBOARD_SOURCE_OFFSET:
        NOTICEBOARD_SOURCE_OFFSET + NOTICEBOARD_PAYLOAD_SIZE
    ] = encoded_payload
    expanded = bytearray(update_checksums(expanded))
    if len(expanded) != EXPANDED_SIZE or not verify_rom(expanded).passed:
        raise ValueError("generated glyph probe failed ROM size or checksum verification")
    return bytes(expanded)


def build_probe_file(
    source_path: Path,
    plan_path: Path,
    output_path: Path,
    overwrite: bool = False,
    encoding_path: Path = ROOT / "data" / "translation_encoding_candidate.json",
) -> tuple[Path, int, str]:
    source = source_path.resolve(strict=True)
    plan_file = plan_path.resolve(strict=True)
    encoding_file = encoding_path.resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"source ROM is not a file: {source}")
    if not plan_file.is_file():
        raise ValueError(f"tile cache plan is not a file: {plan_file}")
    if not encoding_file.is_file():
        raise ValueError(f"encoding candidate is not a file: {encoding_file}")
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
    glyphs, payload = parse_noticeboard_inputs(plan, encoding)
    probe_rom = build_noticeboard_glyph_probe(source_rom, glyphs, payload)
    write_output(output, probe_rom, overwrite)

    written = output.read_bytes()
    if written != probe_rom:
        raise OSError(f"written probe does not match generated ROM: {output}")
    return output, len(probe_rom), hashlib.sha256(probe_rom).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a separate ROM that loads and restores all noticeboard glyphs."
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
        default=ROOT / "roms" / "oni5_t14c5_full_noticeboard_probe.gb",
        help="new probe ROM output path",
    )
    parser.add_argument(
        "--encoding-candidate",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
        help="candidate encoding containing the confirmed noticeboard payload",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output")
    args = parser.parse_args()

    try:
        output, size, digest = build_probe_file(
            args.source_rom,
            args.tile_cache_plan,
            args.output_rom,
            args.overwrite,
            args.encoding_candidate,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {output} ({size} bytes)")
    print(f"SHA-256: {digest}")
    print(f"Loaded {len(NOTICEBOARD_TEXT)} custom glyphs and patched the confirmed 10-byte text stream.")
    print("A guarded hook restores all seven tile patterns after the noticeboard map cleanup.")


if __name__ == "__main__":
    main()
