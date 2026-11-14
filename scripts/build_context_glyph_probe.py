"""Build a standalone probe for one context-scoped dialogue translation."""
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
CONTEXT_RECORD_ID = "oni5-bank0c-pointer-030ee8"
CONTEXT_TEXT = "伽罗\n「听大娘说那三日月山之上\n到底藏着什么呢？」"
CONTEXT_SOURCE_OFFSET = 0x30EE8
CONTEXT_SOURCE_SIZE = 32
CONTEXT_SOURCE_BYTES = bytes.fromhex(
    "A9 7D 3B C5 C4 21 0A 08 1B 18 4D 28 0E 6C 0F C3 "
    "1E 7D 4D 22 4D 1D 1E 60 09 31 21 0E 14 2F 3C 7F"
)
CONTEXT_TEXT_BYTES = 25
CONTEXT_PADDING_BYTES = 6
CONTEXT_PATCH_BYTES = CONTEXT_SOURCE_SIZE
CONTEXT_FIRST_CHARACTER_CURSOR = 0xE9
CONTEXT_RESTORE_CURSOR = 0x08
CONTEXT_CUSTOM_GLYPH_COUNT = 20
BACKUP_BYTES = CONTEXT_CUSTOM_GLYPH_COUNT * 16
SPACE_CODE = 0x4D
LINE_ADVANCE_CODE = 0x7D
TERMINATOR_CODE = 0x7F
ROM_BANK_WINDOW_CPU_START = 0x4000
ROM_BANK_WINDOW_FILE_END = SOURCE_SIZE + 0x4000
PATTERN_ALIGNMENT = 0x100


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
    return (value + alignment - 1) & ~(alignment - 1)


def parse_context_inputs(
    tile_cache_plan: Any,
    encoding_candidate: Any,
) -> tuple[list[CachedGlyph], bytes]:
    plan = require_object(tile_cache_plan, "tile cache plan")
    candidate = require_object(encoding_candidate, "encoding candidate")
    if plan.get("schema_version") != 1 or candidate.get("schema_version") != 1:
        raise ValueError("tile cache plan and encoding candidate must use schema_version 1")
    if (
        plan.get("mode") != "per_context_reusable_mapping"
        or candidate.get("mode") != "context_scoped"
    ):
        raise ValueError("context probe requires context-scoped glyph and encoding candidates")
    if plan.get("custom_glyph_count") != CONTEXT_CUSTOM_GLYPH_COUNT:
        raise ValueError("tile cache plan must contain exactly 20 custom glyphs")

    records = candidate.get("records")
    if not isinstance(records, list):
        raise ValueError("encoding candidate.records must be a list")
    record_matches = [
        require_object(record, f"encoding candidate.records[{index}]")
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get("id") == CONTEXT_RECORD_ID
    ]
    if len(record_matches) != 1:
        raise ValueError(f"expected exactly one encoding record for {CONTEXT_RECORD_ID}")
    record = record_matches[0]
    if record.get("source_start") != "0x030EE8":
        raise ValueError("context source must start at 0x030EE8")
    if record.get("source_end_exclusive") != "0x030F08":
        raise ValueError("context source must end at 0x030F08")
    if record.get("patch_end_exclusive") != "0x030F08":
        raise ValueError("context patch must preserve the original end at 0x030F08")
    if record.get("source_bytes") != CONTEXT_SOURCE_SIZE:
        raise ValueError("context source must contain exactly 32 original bytes")
    if record.get("encoded_bytes") != CONTEXT_PATCH_BYTES:
        raise ValueError("context encoding must preserve the original 32-byte span")
    if record.get("padding_count") != CONTEXT_PADDING_BYTES:
        raise ValueError("context encoding must contain exactly six padding cells")
    if record.get("padding_code") != "0x4D":
        raise ValueError("context padding must use the verified blank tile code 0x4D")
    if record.get("decoded_text") != CONTEXT_TEXT:
        raise ValueError("context encoding does not match the confirmed translation")

    mappings = candidate.get("custom_glyphs")
    if not isinstance(mappings, list):
        raise ValueError("encoding candidate.custom_glyphs must be a list")
    mapping_by_character: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(mappings):
        mapping = require_object(value, f"encoding candidate.custom_glyphs[{index}]")
        character = mapping.get("character")
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(f"encoding mapping {index} must have one character")
        if character in mapping_by_character:
            raise ValueError(f"duplicate encoding mapping for {character!r}")
        tile = parse_byte(mapping.get("tile"), f"encoding mapping {index}.tile")
        input_code = parse_byte(mapping.get("input_code"), f"encoding mapping {index}.input_code")
        if tile != input_code + 0x80:
            raise ValueError(f"input code for {character!r} does not map directly to its tile")
        if mapping.get("tile_source") not in {"custom", "native"}:
            raise ValueError(f"invalid tile source for {character!r}")
        mapping_by_character[character] = mapping

    encoded_hex = record.get("encoded_hex")
    if not isinstance(encoded_hex, str):
        raise ValueError("context encoding must include encoded_hex")
    try:
        payload = bytes.fromhex(encoded_hex)
    except ValueError as exc:
        raise ValueError("context encoded_hex is invalid") from exc
    if len(payload) != CONTEXT_PATCH_BYTES or payload[-1] != TERMINATOR_CODE:
        raise ValueError("context payload must preserve 32 bytes and end with the 0x7F terminator")

    expected_payload = bytearray()
    custom_characters: list[str] = []
    seen_characters: set[str] = set()
    for character in CONTEXT_TEXT:
        if character == "\n":
            expected_payload.append(LINE_ADVANCE_CODE)
            continue
        if character == " ":
            expected_payload.append(SPACE_CODE)
            continue
        mapping = mapping_by_character.get(character)
        if mapping is None:
            raise ValueError(f"no encoding mapping for {character!r}")
        expected_payload.append(parse_byte(mapping["input_code"], f"input_code for {character!r}"))
        if mapping["tile_source"] == "custom" and character not in seen_characters:
            custom_characters.append(character)
            seen_characters.add(character)
    if len(expected_payload) != CONTEXT_TEXT_BYTES:
        raise ValueError("context translated text must encode to exactly 25 bytes")
    expected_payload.extend([SPACE_CODE] * CONTEXT_PADDING_BYTES)
    expected_payload.append(TERMINATOR_CODE)
    if payload != expected_payload:
        raise ValueError("encoded payload does not match the confirmed text and character map")
    if len(custom_characters) != CONTEXT_CUSTOM_GLYPH_COUNT:
        raise ValueError(
            f"translation needs {len(custom_characters)} custom glyphs, expected 20"
        )

    entries = plan.get("entries")
    if not isinstance(entries, list):
        raise ValueError("tile cache plan.entries must be a list")
    glyphs = []
    seen_tiles: set[int] = set()
    for character in custom_characters:
        mapping = mapping_by_character[character]
        tile = parse_byte(mapping["tile"], f"tile for {character!r}")
        if not 0x80 <= tile < 0xC0 or tile in seen_tiles:
            raise ValueError(f"invalid or duplicate custom tile 0x{tile:02X}")
        seen_tiles.add(tile)
        matches = [
            require_object(entry, f"tile cache plan entry for {character!r}")
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("character") == character
            and entry.get("tile_source") == "custom"
            and entry.get("tile") == f"0x{tile:02X}"
        ]
        if len(matches) != 1:
            raise ValueError(f"expected one cached custom tile for {character!r}")
        try:
            pattern = bytes.fromhex(matches[0]["glyph_pattern_2bpp_hex"])
            restore_pattern = bytes.fromhex(matches[0]["restore_pattern_2bpp_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"missing or invalid pattern data for {character!r}") from exc
        if len(pattern) != 16 or len(restore_pattern) != 16:
            raise ValueError(f"glyph patterns for {character!r} must contain 16 bytes")
        glyphs.append(CachedGlyph(character, tile, pattern))

    if payload[:1] != bytes((glyphs[0].tile - 0x80,)):
        raise ValueError("context payload must start with the first cached glyph")
    return glyphs, payload


def build_context_entry_code() -> bytes:
    code = bytearray(ENTRY_CODE)
    if code[19] != 0x34:
        raise ValueError("shared entry code layout changed; context cursor gate needs review")
    code[19] = CONTEXT_FIRST_CHARACTER_CURSOR
    return bytes(code)


def build_restore_helper(restore_cpu_address: int) -> bytes:
    return (
        bytes.fromhex("F5 FA AA FF F5 3E 10 EA 00 20")
        + bytes((0xCD, restore_cpu_address & 0xFF, restore_cpu_address >> 8))
        + bytes.fromhex("F1 EA 00 20 F1 21 03 00 C9")
    )


def build_context_bank_layout(
    glyphs: list[CachedGlyph],
) -> tuple[int, int, int, bytes, bytes]:
    if len(glyphs) != CONTEXT_CUSTOM_GLYPH_COUNT:
        raise ValueError("context probe requires exactly 20 cached glyphs")
    loader_offset = BANK_SWITCH_HELPER_OFFSET
    preliminary_loader = build_loader_helper(glyphs)
    pattern_offset = align_up(loader_offset + len(preliminary_loader), PATTERN_ALIGNMENT)
    pattern_cpu_address = ROM_BANK_WINDOW_CPU_START + pattern_offset - SOURCE_SIZE
    loader = build_loader_helper(glyphs, pattern_cpu_address)
    pattern_end = pattern_offset + len(glyphs) * 16
    restore_offset = pattern_end
    restore_cpu_address = ROM_BANK_WINDOW_CPU_START + restore_offset - SOURCE_SIZE
    restore_helper = build_restore_bank_helper(
        glyphs,
        CONTEXT_RESTORE_CURSOR,
        ROM_BANK_WINDOW_CPU_START + pattern_end - SOURCE_SIZE,
    )
    if loader_offset + len(loader) > pattern_offset:
        raise ValueError("context loader overlaps its glyph pattern data")
    if pattern_end > restore_offset:
        raise ValueError("context glyph pattern data overlaps its restore helper")
    if restore_offset + len(restore_helper) > ROM_BANK_WINDOW_FILE_END:
        raise ValueError("context cache helper exceeds the bank-10 ROM window")
    if restore_cpu_address + len(restore_helper) > 0x8000:
        raise ValueError("context restore helper exceeds the bank-10 CPU window")
    return pattern_offset, restore_offset, restore_cpu_address, loader, restore_helper


def build_context_glyph_probe(
    source_rom: bytes,
    glyphs: list[CachedGlyph],
    encoded_payload: bytes,
) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    if len(glyphs) != CONTEXT_CUSTOM_GLYPH_COUNT:
        raise ValueError("context probe requires all 20 unique custom glyphs")
    if len(encoded_payload) != CONTEXT_PATCH_BYTES:
        raise ValueError("context stream must preserve the original 32-byte span")
    if encoded_payload[-1] != TERMINATOR_CODE:
        raise ValueError("context stream must end with the 0x7F terminator")
    if encoded_payload[-CONTEXT_PADDING_BYTES - 1:-1] != bytes(
        [SPACE_CODE] * CONTEXT_PADDING_BYTES
    ):
        raise ValueError("context stream must pad with six 0x4D blank cells before 0x7F")
    if encoded_payload[:1] != bytes((glyphs[0].tile - 0x80,)):
        raise ValueError("context stream must start with the first cached glyph")
    if any(len(glyph.pattern) != 16 for glyph in glyphs):
        raise ValueError("every context glyph pattern must contain exactly 16 bytes")
    if source_rom[
        CONTEXT_SOURCE_OFFSET:CONTEXT_SOURCE_OFFSET + CONTEXT_SOURCE_SIZE
    ] != CONTEXT_SOURCE_BYTES:
        raise ValueError("context source bytes do not match the verified original text")
    if source_rom[
        RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_EXPECTED)
    ] != RESTORE_HOOK_EXPECTED:
        raise ValueError("tile restore hook bytes do not match the expected source")
    restore_helper_template = build_restore_helper(0x4100)
    if source_rom[
        RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_helper_template)
    ] != bytes([0xFF]) * len(restore_helper_template):
        raise ValueError("tile restore helper area is not entirely unused")

    pattern_offset, restore_offset, restore_cpu, loader, restore_bank_helper = (
        build_context_bank_layout(glyphs)
    )
    expanded = bytearray(build_expansion_probe(source_rom))
    if expanded[
        pattern_offset:pattern_offset + len(glyphs) * 16
    ] != bytes([0xFF]) * (len(glyphs) * 16):
        raise ValueError("context glyph pattern area is not entirely unused")
    if expanded[
        restore_offset:restore_offset + len(restore_bank_helper)
    ] != bytes([0xFF]) * len(restore_bank_helper):
        raise ValueError("context restore bank helper area is not entirely unused")
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + ENTRY_AREA_SIZE] = bytes([0xFF]) * ENTRY_AREA_SIZE
    entry_code = build_context_entry_code()
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + len(entry_code)] = entry_code
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + POSTLUDE_AREA_SIZE] = bytes(
        [0xFF]
    ) * POSTLUDE_AREA_SIZE
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)] = POSTLUDE_CODE
    expanded[RESTORE_HOOK_OFFSET:RESTORE_HOOK_OFFSET + len(RESTORE_HOOK_PATCH)] = (
        RESTORE_HOOK_PATCH
    )
    restore_helper = build_restore_helper(restore_cpu)
    expanded[RESTORE_HELPER_OFFSET:RESTORE_HELPER_OFFSET + len(restore_helper)] = restore_helper
    expanded[BANK_SWITCH_HELPER_OFFSET:BANK_SWITCH_HELPER_OFFSET + len(loader)] = loader
    for index, glyph in enumerate(glyphs):
        start = pattern_offset + index * 16
        expanded[start:start + 16] = glyph.pattern
    expanded[restore_offset:restore_offset + len(restore_bank_helper)] = restore_bank_helper
    expanded[
        CONTEXT_SOURCE_OFFSET:CONTEXT_SOURCE_OFFSET + len(encoded_payload)
    ] = encoded_payload
    expanded = bytearray(update_checksums(expanded))
    if len(expanded) != EXPANDED_SIZE or not verify_rom(expanded).passed:
        raise ValueError("generated context probe failed ROM size or checksum verification")
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
    glyphs, payload = parse_context_inputs(plan, encoding)
    probe_rom = build_context_glyph_probe(source_rom, glyphs, payload)
    write_output(output, probe_rom, overwrite)

    written = output.read_bytes()
    if written != probe_rom:
        raise OSError(f"written probe does not match generated ROM: {output}")
    return output, len(probe_rom), hashlib.sha256(probe_rom).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a separate context-scoped dialogue glyph probe ROM."
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
        default=ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json",
        help="validated glyph and original-tile data",
    )
    parser.add_argument(
        "encoding_candidate",
        nargs="?",
        type=Path,
        default=ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json",
        help="per-context text encoding candidate",
    )
    parser.add_argument(
        "output_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_t19_context_probe.gb",
        help="output probe ROM",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output ROM",
    )
    args = parser.parse_args()
    output, size, digest = build_probe_file(
        args.source_rom,
        args.tile_cache_plan,
        args.encoding_candidate,
        args.output_rom,
        args.overwrite,
    )
    print(f"Built {output} ({size} bytes, SHA-256 {digest})")


if __name__ == "__main__":
    main()
