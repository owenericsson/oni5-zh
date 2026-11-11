"""Compile pilot translations into a candidate context-scoped byte encoding."""
import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOTICEBOARD_RECORD_ID = "oni5-bank0c-pointer-030e33"
PILOT_RECORD_IDS = (
    NOTICEBOARD_RECORD_ID,
    "oni5-bank0c-pointer-030e8e",
)
CUSTOM_TOKEN_CODES = [
    code for code in range(0x2A, 0x55) if code != 0x4D
]
TILE_IDS = [*range(0xC0, 0xCA), 0xCB, *range(0xE0, 0xFF)]
SPACE_CODE = 0x4D
LINE_ADVANCE_CODE = 0x7D
PAGE_TRANSITION_CODE = 0x7E
TERMINATOR_CODE = 0x7F
EMPTY_MACRO_PADDING_CODE = 0xD6


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def create_glyph_map(glyph_asset: Any) -> tuple[list[dict[str, str]], dict[str, int]]:
    root = require_object(glyph_asset, "glyph asset")
    if root.get("schema_version") != 1:
        raise ValueError("glyph asset schema_version must be 1")
    font = require_object(root.get("font"), "glyph asset.font")
    glyphs = root.get("glyphs")
    if not isinstance(glyphs, list) or not glyphs:
        raise ValueError("glyph asset.glyphs must be a non-empty list")
    capacity = min(len(CUSTOM_TOKEN_CODES), len(TILE_IDS))
    if len(glyphs) > capacity:
        raise ValueError(
            f"glyph asset has {len(glyphs)} glyphs, exceeding candidate capacity {capacity}"
        )

    token_map = []
    code_by_character = {}
    seen_characters = set()
    for index, value in enumerate(glyphs):
        glyph = require_object(value, f"glyph asset.glyphs[{index}]")
        character = glyph.get("character")
        codepoint = glyph.get("codepoint")
        tile_hex = glyph.get("tile_2bpp_hex")
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(f"glyph asset.glyphs[{index}].character must be one code point")
        if codepoint != f"U+{ord(character):04X}":
            raise ValueError(f"glyph asset codepoint mismatch for {character!r}")
        if character in seen_characters:
            raise ValueError(f"duplicate glyph character: {character!r}")
        if not isinstance(tile_hex, str):
            raise ValueError(f"glyph asset has no tile data for {character!r}")
        try:
            tile_data = bytes.fromhex(tile_hex)
        except ValueError as exc:
            raise ValueError(f"invalid tile data for {character!r}") from exc
        if len(tile_data) != 16:
            raise ValueError(f"tile data for {character!r} must be 16 bytes")

        seen_characters.add(character)
        code = CUSTOM_TOKEN_CODES[index]
        tile = TILE_IDS[index]
        code_by_character[character] = code
        token_map.append(
            {
                "character": character,
                "codepoint": codepoint,
                "input_code": f"0x{code:02X}",
                "tile": f"0x{tile:02X}",
            }
        )

    if font.get("source_sha256") is None:
        raise ValueError("glyph asset.font.source_sha256 is required")
    return token_map, code_by_character


def encode_text(text: str, code_by_character: dict[str, int]) -> list[int]:
    result = []
    for character in text:
        if character == "\n":
            result.append(LINE_ADVANCE_CODE)
        elif character == " ":
            result.append(SPACE_CODE)
        elif character.isspace():
            raise ValueError(f"unsupported whitespace U+{ord(character):04X}")
        else:
            code = code_by_character.get(character)
            if code is None:
                raise ValueError(f"no custom input code for {character!r}")
            result.append(code)

    return result


def compile_encoding(manifest: Any, glyph_asset: Any) -> dict[str, Any]:
    root = require_object(manifest, "text manifest")
    records = root.get("records")
    if not isinstance(records, list):
        raise ValueError("text manifest.records must be a list")
    by_id = {}
    for index, value in enumerate(records):
        record = require_object(value, f"text manifest.records[{index}]")
        record_id = record.get("id")
        if isinstance(record_id, str):
            by_id[record_id] = record

    token_map, code_by_character = create_glyph_map(glyph_asset)
    encoded_records = []
    for record_id in PILOT_RECORD_IDS:
        record = by_id.get(record_id)
        if record is None:
            raise ValueError(f"missing pilot record {record_id!r}")
        translation = require_object(record.get("translation"), f"{record_id}.translation")
        if translation.get("status") != "confirmed":
            raise ValueError(f"{record_id}: translation must be confirmed")
        segments = translation.get("segments")
        if not isinstance(segments, list) or len(segments) != 1:
            raise ValueError(f"{record_id}: expected exactly one confirmed translation segment")
        segment = require_object(segments[0], f"{record_id}.translation.segments[0]")
        text = segment.get("text")
        if not isinstance(text, str):
            raise ValueError(f"{record_id}: translation text must be a string")

        source = require_object(record.get("source"), f"{record_id}.source")
        payload = require_object(source.get("payload"), f"{record_id}.source.payload")
        start = int(segment.get("source_start", ""), 16)
        end = int(segment.get("source_end_exclusive", ""), 16)
        payload_end = int(payload.get("end_exclusive", ""), 16)
        terminator = int(payload.get("terminator", ""), 16)
        if end <= start or end != payload_end - 1:
            raise ValueError(f"{record_id}: translation range must end immediately before terminator")
        if terminator != TERMINATOR_CODE:
            raise ValueError(f"{record_id}: unsupported source terminator 0x{terminator:02X}")

        body = encode_text(text, code_by_character)
        source_length = end - start
        padding_count = source_length - len(body)
        if padding_count < 0:
            raise ValueError(
                f"{record_id}: encoded text needs {len(body)} bytes, "
                f"but source span has {source_length}"
            )
        padding_code = SPACE_CODE
        body.extend([padding_code] * padding_count)
        body.append(terminator)
        encoded_records.append(
            {
                "id": record_id,
                "source_start": f"0x{start:06X}",
                "source_end_exclusive": f"0x{payload_end:06X}",
                "source_bytes": payload_end - start,
                "encoded_bytes": len(body),
                "padding_count": padding_count,
                "padding_code": f"0x{padding_code:02X}",
                "padding_status": "0x4D visual blank verified in SameBoy",
                "encoded_hex": bytes(body).hex(" ").upper(),
                "decoded_text": text,
            }
        )

    font = require_object(glyph_asset, "glyph asset").get("font")
    return {
        "schema_version": 1,
        "status": "pending_context_runtime_probe",
        "mode": "context_scoped",
        "font_source_sha256": font["source_sha256"],
        "custom_glyphs": token_map,
        "special_codes": {
            "space": {
                "input_code": f"0x{SPACE_CODE:02X}",
                "tile": "0xCD",
                "status": "0x4D padding verified for noticeboard (2 cells) and woman (30 cells)",
            },
            "line_advance": f"0x{LINE_ADVANCE_CODE:02X}",
            "page_transition": f"0x{PAGE_TRANSITION_CODE:02X}",
            "terminator": f"0x{TERMINATOR_CODE:02X}",
            "phrase_aliases": [],
            "padding": {
                "input_code": f"0x{EMPTY_MACRO_PADDING_CODE:02X}",
                "status": (
                    "rejected: zero length underflows the parser counter to 256; "
                    "SameBoy displayed gibberish and corrupted the text cursor"
                ),
            },
        },
        "records": encoded_records,
        "runtime_requirements": [
            "Activate the custom mapping only for the two listed source ranges.",
            "Restore the original mapping when the source terminator is processed.",
            "Do not use 0xD6 as padding; a zero expansion length loops 256 times.",
            "0x4D padding preserves source length and terminator in both tested records.",
            "Validate custom mapping activation only for the two exact text ranges.",
            "Verify the original Japanese mapping is restored after each 0x7F terminator.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile confirmed pilot text into a candidate contextual byte encoding."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "text_manifest.json",
        help="translation manifest",
    )
    parser.add_argument(
        "--glyphs",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs.json",
        help="exported Chinese glyph asset",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
        help="candidate encoding output",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace existing output")
    args = parser.parse_args()

    try:
        manifest_path = args.manifest.resolve(strict=True)
        glyph_path = args.glyphs.resolve(strict=True)
        output_path = args.output.resolve()
        if output_path in {manifest_path, glyph_path}:
            raise ValueError("output must differ from the manifest and glyph asset")
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"output already exists: {output_path}; pass --overwrite to replace it"
            )
        plan = compile_encoding(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            json.loads(glyph_path.read_text(encoding="utf-8")),
        )
        output_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote candidate encoding for {len(plan['records'])} pilot texts to {output_path}")


if __name__ == "__main__":
    main()
