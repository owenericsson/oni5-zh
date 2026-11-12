"""Compile Chinese and original tile patterns into a blocked cache plan."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .decode_gb_resource import decode_resource
    from .rom_checksums import verify_rom
else:
    from decode_gb_resource import decode_resource
    from rom_checksums import verify_rom

ROOT = Path(__file__).resolve().parents[1]
FONT_BANK = 0x03
FONT_DESCRIPTOR = 0x5CA4
FONT_LENGTH = 0x800
CUSTOM_TILE_RANGE = range(0x80, 0xC0)
EXPECTED_CUSTOM_GLYPH_COUNT = 34


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


def parse_pattern(value: Any, field: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a hexadecimal string")
    try:
        pattern = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid hexadecimal") from exc
    if len(pattern) != 16:
        raise ValueError(f"{field} must contain exactly 16 bytes")
    return pattern


def compile_tile_cache_plan(
    rom: bytes,
    candidate: Any,
    glyph_asset: Any,
) -> dict[str, Any]:
    candidate_root = require_object(candidate, "encoding candidate")
    glyph_root = require_object(glyph_asset, "glyph asset")
    font = require_object(glyph_root.get("font"), "glyph asset.font")
    if glyph_root.get("schema_version") != 1:
        raise ValueError("glyph asset schema_version must be 1")
    if candidate_root.get("font_source_sha256") != font.get("source_sha256"):
        raise ValueError("encoding candidate and glyph asset font hashes do not match")

    verification = verify_rom(rom)
    if not verification.passed:
        raise ValueError("source ROM failed size or checksum verification")

    glyph_values = glyph_root.get("glyphs")
    if not isinstance(glyph_values, list):
        raise ValueError("glyph asset.glyphs must be a list")
    glyph_by_character = {}
    for index, value in enumerate(glyph_values):
        glyph = require_object(value, f"glyph asset.glyphs[{index}]")
        character = glyph.get("character")
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(f"glyph asset.glyphs[{index}].character must be one code point")
        if character in glyph_by_character:
            raise ValueError(f"duplicate glyph character: {character!r}")
        glyph_by_character[character] = glyph

    decoded_font = decode_resource(
        rom,
        FONT_BANK,
        FONT_DESCRIPTOR,
        FONT_LENGTH,
    )
    mappings = candidate_root.get("custom_glyphs")
    if not isinstance(mappings, list):
        raise ValueError("encoding candidate.custom_glyphs must be a list")

    entries = []
    custom_tiles = set()
    custom_count = 0
    for index, value in enumerate(mappings):
        mapping = require_object(value, f"encoding candidate.custom_glyphs[{index}]")
        character = mapping.get("character")
        if not isinstance(character, str) or character not in glyph_by_character:
            raise ValueError(f"candidate glyph {character!r} is missing from glyph asset")
        glyph = glyph_by_character[character]
        if mapping.get("codepoint") != glyph.get("codepoint"):
            raise ValueError(f"codepoint mismatch for {character!r}")

        tile_source = mapping.get("tile_source")
        entry = {
            "character": character,
            "codepoint": mapping["codepoint"],
            "input_code": mapping.get("input_code"),
            "tile": mapping.get("tile"),
            "tile_source": tile_source,
            "glyph_pattern_2bpp_hex": None,
            "restore_pattern_2bpp_hex": None,
            "font_output_offset": None,
        }
        if tile_source == "native":
            entries.append(entry)
            continue
        if tile_source != "custom":
            raise ValueError(f"unsupported tile_source for {character!r}: {tile_source!r}")

        tile = parse_byte(mapping.get("tile"), f"candidate tile for {character!r}")
        if tile not in CUSTOM_TILE_RANGE:
            raise ValueError(f"custom tile 0x{tile:02X} is outside 0x80-0xBF")
        if tile in custom_tiles:
            raise ValueError(f"duplicate custom tile assignment: 0x{tile:02X}")
        custom_tiles.add(tile)
        custom_count += 1

        glyph_pattern = parse_pattern(
            glyph.get("tile_2bpp_hex"),
            f"glyph asset pattern for {character!r}",
        )
        output_offset = (tile - 0x80) * 16
        restore_pattern = decoded_font[output_offset:output_offset + 16]
        if len(restore_pattern) != 16:
            raise ValueError(f"missing original font pattern for tile 0x{tile:02X}")

        entry.update(
            {
                "glyph_pattern_2bpp_hex": glyph_pattern.hex(" ").upper(),
                "restore_pattern_2bpp_hex": restore_pattern.hex(" ").upper(),
                "font_output_offset": f"0x{output_offset:03X}",
            }
        )
        entries.append(entry)

    if custom_count != EXPECTED_CUSTOM_GLYPH_COUNT:
        raise ValueError(
            f"expected {EXPECTED_CUSTOM_GLYPH_COUNT} custom glyphs, found {custom_count}"
        )

    return {
        "schema_version": 1,
        "status": "blocked_pending_runtime_loader_and_restore_validation",
        "mode": "fixed_tile_mapping",
        "source_rom_sha256": hashlib.sha256(rom).hexdigest(),
        "font_resource": {
            "bank": f"0x{FONT_BANK:02X}",
            "descriptor": f"0x{FONT_DESCRIPTOR:04X}",
            "decoded_length": len(decoded_font),
            "decoded_sha256": hashlib.sha256(decoded_font).hexdigest(),
        },
        "tile_pool": candidate_root.get("provisional_custom_tile_pool"),
        "custom_glyph_count": custom_count,
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile custom and original 2BPP patterns into a tile cache plan."
    )
    parser.add_argument(
        "--rom",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
        help="verified original ROM",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
        help="blocked translation encoding candidate",
    )
    parser.add_argument(
        "--glyphs",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs.json",
        help="Chinese 2BPP glyph asset",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_candidate.json",
        help="tile cache plan output",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace existing output")
    args = parser.parse_args()

    try:
        rom_path = args.rom.resolve(strict=True)
        candidate_path = args.candidate.resolve(strict=True)
        glyph_path = args.glyphs.resolve(strict=True)
        output_path = args.output.resolve()
        if output_path in {rom_path, candidate_path, glyph_path}:
            raise ValueError("output must differ from all input files")
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"output already exists: {output_path}; pass --overwrite to replace it"
            )
        plan = compile_tile_cache_plan(
            rom_path.read_bytes(),
            json.loads(candidate_path.read_text(encoding="utf-8")),
            json.loads(glyph_path.read_text(encoding="utf-8")),
        )
        output_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(
        f"Wrote blocked tile cache plan for {plan['custom_glyph_count']} custom glyphs "
        f"to {output_path}"
    )


if __name__ == "__main__":
    main()
