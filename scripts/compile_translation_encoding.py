"""Compile pilot translations into a candidate context-scoped byte encoding."""
import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOTICEBOARD_RECORD_ID = "oni5-bank0c-pointer-030e33"
WOMAN_RECORD_ID = "oni5-bank0c-pointer-030e8e"
PILOT_RECORD_IDS = (
    NOTICEBOARD_RECORD_ID,
    WOMAN_RECORD_ID,
)
REUSABLE_CONTEXT_RECORD_ID = "oni5-bank0c-pointer-030ee8"
NO_PADDING_RECORD_IDS = {
    WOMAN_RECORD_ID,
}
NON_TEXT_MAP_TILE_IDS = {
    0x88,
    0x8A,
    0x8B,
    0x8D,
    0x8E,
    0x90,
    0x92,
    0x95,
    0x98,
    0x9C,
    0x9D,
    0xA1,
    0xAB,
    0xB1,
    0xB2,
    0xB3,
    0xB6,
    0xB8,
}
NATIVE_TILE_BY_CHARACTER = {
    "？": 0xCA,
    "「": 0xBB,
    "」": 0xBC,
}
NATIVE_CUSTOM_TILE_IDS = {
    tile_id
    for tile_id in NATIVE_TILE_BY_CHARACTER.values()
    if 0x80 <= tile_id < 0xC0
}
ELIGIBLE_CUSTOM_TILE_IDS = [
    tile_id
    for tile_id in range(0x80, 0xC0)
    if tile_id not in NON_TEXT_MAP_TILE_IDS | NATIVE_CUSTOM_TILE_IDS
]
PROVISIONAL_CUSTOM_TILE_IDS = ELIGIBLE_CUSTOM_TILE_IDS[:34]
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
    native_characters = {
        glyph.get("character")
        for glyph in glyphs
        if isinstance(glyph, dict)
        and isinstance(glyph.get("character"), str)
        and glyph["character"] in NATIVE_TILE_BY_CHARACTER
    }
    capacity = len(PROVISIONAL_CUSTOM_TILE_IDS) + len(native_characters)
    if len(glyphs) > capacity:
        raise ValueError(
            f"glyph asset has {len(glyphs)} glyphs, exceeding candidate capacity {capacity}"
        )

    token_map = []
    code_by_character = {}
    seen_characters = set()
    seen_codes = set()
    custom_tiles = iter(PROVISIONAL_CUSTOM_TILE_IDS)
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
        native_tile = NATIVE_TILE_BY_CHARACTER.get(character)
        tile = native_tile if native_tile is not None else next(custom_tiles)
        code = tile - 0x80
        if not 0 <= code < 0x60:
            raise ValueError(f"tile 0x{tile:02X} cannot use direct text code 0x{code:02X}")
        if code == SPACE_CODE or code in seen_codes:
            raise ValueError(f"duplicate or reserved direct input code: 0x{code:02X}")
        seen_codes.add(code)
        code_by_character[character] = code
        token_map.append(
            {
                "character": character,
                "codepoint": codepoint,
                "input_code": f"0x{code:02X}",
                "tile": f"0x{tile:02X}",
                "tile_source": "native" if native_tile is not None else "custom",
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


def compile_encoding(
    manifest: Any,
    glyph_asset: Any,
    record_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = require_object(manifest, "text manifest")
    records = root.get("records")
    if not isinstance(records, list):
        raise ValueError("text manifest.records must be a list")
    selected_record_ids = PILOT_RECORD_IDS if record_ids is None else record_ids
    if (
        not isinstance(selected_record_ids, tuple)
        or not selected_record_ids
        or any(not isinstance(record_id, str) or not record_id for record_id in selected_record_ids)
        or len(set(selected_record_ids)) != len(selected_record_ids)
    ):
        raise ValueError("record_ids must be a non-empty tuple of unique record IDs")
    by_id = {}
    for index, value in enumerate(records):
        record = require_object(value, f"text manifest.records[{index}]")
        record_id = record.get("id")
        if isinstance(record_id, str):
            by_id[record_id] = record

    token_map, code_by_character = create_glyph_map(glyph_asset)
    encoded_records = []
    for record_id in selected_record_ids:
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
        if len(body) > source_length:
            raise ValueError(
                f"{record_id}: encoded text needs {len(body)} bytes, "
                f"but source span has {source_length}"
            )
        padding_code = SPACE_CODE
        padding_count = (
            0 if record_id in NO_PADDING_RECORD_IDS else source_length - len(body)
        )
        body.extend([padding_code] * padding_count)
        body.append(terminator)
        patch_end = start + len(body)
        if record_id == WOMAN_RECORD_ID:
            padding_status = (
                "omitted: trailing 0x4D cells caused an extra scroll; "
                "terminator follows translated text"
            )
        elif record_id == REUSABLE_CONTEXT_RECORD_ID:
            padding_status = (
                "0x4D blank cells preserve the original event/script cursor; verify this "
                "line width does not trigger scrolling"
            )
        else:
            padding_status = "0x4D visual blank verified in SameBoy"
        encoded_records.append(
            {
                "id": record_id,
                "source_start": f"0x{start:06X}",
                "source_end_exclusive": f"0x{payload_end:06X}",
                "patch_end_exclusive": f"0x{patch_end:06X}",
                "source_bytes": payload_end - start,
                "encoded_bytes": len(body),
                "padding_count": padding_count,
                "padding_code": f"0x{padding_code:02X}",
                "padding_status": padding_status,
                "encoded_hex": bytes(body).hex(" ").upper(),
                "decoded_text": text,
            }
        )

    font = require_object(glyph_asset, "glyph asset").get("font")
    custom_glyph_count = sum(
        glyph["tile_source"] == "custom" for glyph in token_map
    )
    context_specific_mapping = record_ids is not None
    tile_allocation_status = "fixed_34_tile_mapping_for_confirmed_contexts_only"
    runtime_requirements = [
        "Activate the custom mapping only for the two listed source ranges.",
        "Restore the original mapping when the source terminator is processed.",
        "For custom glyphs, encode input_code as tile_id - 0x80; the original renderer adds 0x80 for codes below 0x60.",
        "Do not use 0xD6 as padding; a zero expansion length loops 256 times.",
        "0x4D padding preserves the noticeboard source length; the woman stream terminates immediately after translated text to avoid trailing-space scrolling.",
        "Validate custom mapping activation only for the two exact text ranges.",
        "Verify the original Japanese mapping is restored after each 0x7F terminator.",
        "Reserve 0xE0-0xFF globally for dynamic portraits; do not allocate custom glyphs there.",
        "Use the 34 custom tiles only for the two tested dialogue contexts; before adding another text context, audit its visible BG/OAM references and verify tile backups and restoration there.",
        "Prefer native tile reuse for 0xFF1F (0xCA), 0x300C (0xBB), and 0x300D (0xBC); these are the glyph tiles used by the original dialogue text.",
        "Do not allocate custom glyph patterns to native punctuation tiles marked tile_source=native.",
        "Do not custom-allocate 0xCB (native exclamation mark) or the blank 0xCC-0xCD tiles.",
    ]
    if context_specific_mapping:
        tile_allocation_status = "per_context_mapping_reuses_audited_pool"
        runtime_requirements[0] = (
            "Select the custom mapping only for the exact text source context."
        )
        runtime_requirements[4] = (
            "For this context, pad with 0x4D blank cells through the original 0x7F "
            "terminator position to preserve the following event/script cursor."
        )
        runtime_requirements[5] = (
            "Before reusing tile IDs in another context, verify context activation and "
            "original-pattern backup/restoration."
        )
        runtime_requirements[8] = (
            "Reuse tile IDs across text contexts only when the contexts cannot overlap "
            "and each context has verified pattern backup/restoration."
        )
    return {
        "schema_version": 1,
        "status": "candidate_restricted_to_confirmed_dialogue_contexts",
        "tile_allocation_status": tile_allocation_status,
        "provisional_custom_tile_pool": {
            "start": "0x80",
            "end_exclusive": "0xC0",
            "count": custom_glyph_count,
            "eligible_count": len(ELIGIBLE_CUSTOM_TILE_IDS),
            "reserved_native_tile_ids": [
                f"0x{tile_id:02X}" for tile_id in sorted(NATIVE_CUSTOM_TILE_IDS)
            ],
            "excluded_non_text_map_ids": [
                f"0x{tile_id:02X}" for tile_id in sorted(NON_TEXT_MAP_TILE_IDS)
            ],
            "status": "restricted_to_confirmed_contexts_not_global",
        },
        "mode": "context_scoped",
        "font_source_sha256": font["source_sha256"],
        "custom_glyphs": token_map,
        "special_codes": {
            "space": {
                "input_code": f"0x{SPACE_CODE:02X}",
                "tile": "0xCD",
                "status": (
                    "0x4D padding preserves source length for the noticeboard and context "
                    "dialogues; omitted from the woman stream because trailing spaces caused "
                    "an extra scroll"
                ),
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
        "runtime_requirements": runtime_requirements,
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
    parser.add_argument(
        "--record-id",
        action="append",
        dest="record_ids",
        help="compile only this confirmed text context; may be repeated",
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
            tuple(args.record_ids) if args.record_ids else None,
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
