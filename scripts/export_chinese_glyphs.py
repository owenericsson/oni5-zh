"""Export confirmed 8px BDF glyphs as Game Boy 2bpp tile bytes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FONT_SOURCE_URL = (
    "https://fontpixel.com/downloads/"
    "chill-bitmap--ChillBitmap7x-8px.bdf.gz"
)
FONT_LICENSE_URL = "https://github.com/Warren2060/ChillBitmap/blob/main/License"


def parse_bdf(data: bytes) -> dict[int, dict[str, Any]]:
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    text = data.decode("ascii")
    glyphs = {}
    current: dict[str, Any] | None = None
    reading_bitmap = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if line.startswith("STARTCHAR "):
            if current is not None:
                raise ValueError(f"BDF line {line_number}: nested STARTCHAR")
            current = {"bitmap": []}
            reading_bitmap = False
        elif current is None:
            continue
        elif line == "BITMAP":
            reading_bitmap = True
        elif line == "ENDCHAR":
            encoding = current.get("encoding")
            if isinstance(encoding, int) and encoding >= 0:
                if encoding in glyphs:
                    raise ValueError(f"BDF contains duplicate encoding {encoding}")
                glyphs[encoding] = current
            current = None
            reading_bitmap = False
        elif reading_bitmap:
            current["bitmap"].append(line)
        elif line.startswith("ENCODING "):
            current["encoding"] = int(line.split()[1])
        elif line.startswith("DWIDTH "):
            current["dwidth"] = [int(value) for value in line.split()[1:]]
        elif line.startswith("BBX "):
            current["bbx"] = [int(value) for value in line.split()[1:]]

    if current is not None:
        raise ValueError("BDF ended before ENDCHAR")
    return glyphs


def encode_glyph(record: dict[str, Any], character: str) -> bytes:
    width, height, x_offset, y_offset = record["bbx"]
    if record.get("dwidth") != [8, 0]:
        raise ValueError(f"{character!r}: expected an 8-pixel horizontal advance")
    if not (0 < width <= 8 and 0 < height <= 8):
        raise ValueError(f"{character!r}: glyph dimensions do not fit an 8x8 tile")

    x_end = x_offset + width
    y_top = 7 + y_offset - height + 1
    y_end = y_top + height
    if x_offset < 0 or x_end > 8 or y_top < 0 or y_end > 8:
        raise ValueError(f"{character!r}: BDF bounding box does not fit an 8x8 tile")

    rows = record.get("bitmap", [])
    if len(rows) != height:
        raise ValueError(f"{character!r}: expected {height} bitmap rows, found {len(rows)}")

    tile_rows = [0] * 8
    row_byte_count = (width + 7) // 8
    for row_index, encoded_row in enumerate(rows):
        try:
            row_bytes = bytes.fromhex(encoded_row)
        except ValueError as exc:
            raise ValueError(f"{character!r}: invalid BDF bitmap row {row_index}") from exc
        if len(row_bytes) != row_byte_count:
            raise ValueError(f"{character!r}: invalid byte width in bitmap row {row_index}")
        for x in range(width):
            if row_bytes[x // 8] & (0x80 >> (x % 8)):
                tile_x = x_offset + x
                tile_rows[y_top + row_index] |= 0x80 >> tile_x

    return bytes(value for row in tile_rows for value in (row, row))


def collect_required_characters(
    manifest: Any,
    record_ids: list[str] | None = None,
) -> list[str]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("records"), list):
        raise ValueError("text manifest must contain a records list")
    if record_ids is not None and (
        not record_ids
        or any(not isinstance(record_id, str) or not record_id for record_id in record_ids)
    ):
        raise ValueError("record_ids must contain at least one non-empty string")

    selected_ids = set(record_ids) if record_ids is not None else None
    selected_records = set()
    characters = set()
    confirmed_count = 0
    for index, record in enumerate(manifest["records"]):
        if not isinstance(record, dict):
            raise ValueError(f"records[{index}] must be an object")
        record_id = record.get("id")
        if selected_ids is not None:
            if not isinstance(record_id, str) or record_id not in selected_ids:
                continue
            selected_records.add(record_id)
        translation = record.get("translation", {})
        if selected_ids is not None and (
            not isinstance(translation, dict)
            or translation.get("status") != "confirmed"
        ):
            raise ValueError(f"{record_id}: selected translation must be confirmed")
        if not isinstance(translation, dict) or translation.get("status") != "confirmed":
            continue
        segments = translation.get("segments")
        if not isinstance(segments, list):
            raise ValueError(f"records[{index}].translation.segments must be a list")
        confirmed_count += 1
        for segment_index, segment in enumerate(segments):
            if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                raise ValueError(
                    f"records[{index}].translation.segments[{segment_index}].text "
                    "must be a string"
                )
            for character in segment["text"]:
                if character in {" ", "\r", "\n"}:
                    continue
                if character.isspace():
                    raise ValueError(
                        f"unsupported whitespace U+{ord(character):04X} in confirmed text"
                    )
                characters.add(character)

    if selected_ids is not None:
        missing_ids = selected_ids - selected_records
        if missing_ids:
            missing = ", ".join(sorted(missing_ids))
            raise ValueError(f"manifest is missing selected record(s): {missing}")
    if confirmed_count == 0:
        raise ValueError("text manifest contains no confirmed translations")
    return sorted(characters, key=ord)


def export_glyphs(
    font_data: bytes,
    manifest: Any,
    record_ids: list[str] | None = None,
) -> dict[str, Any]:
    required = collect_required_characters(manifest, record_ids)
    bdf_glyphs = parse_bdf(font_data)
    glyphs = []
    for character in required:
        codepoint = ord(character)
        record = bdf_glyphs.get(codepoint)
        if record is None:
            raise ValueError(f"font has no glyph for U+{codepoint:04X} {character!r}")
        tile = encode_glyph(record, character)
        glyphs.append(
            {
                "character": character,
                "codepoint": f"U+{codepoint:04X}",
                "tile_2bpp_hex": tile.hex(" ").upper(),
            }
        )

    return {
        "schema_version": 1,
        "font": {
            "family": "ChillBitmap",
            "variant": "8px Regular Proportional",
            "source_url": FONT_SOURCE_URL,
            "source_sha256": hashlib.sha256(font_data).hexdigest(),
            "license": "SIL Open Font License 1.1",
            "license_url": FONT_LICENSE_URL,
        },
        "glyphs": glyphs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export confirmed translation glyphs from an 8px ChillBitmap BDF."
    )
    parser.add_argument("font", type=Path, help="BDF or gzip-compressed BDF source")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "text_manifest.json",
        help="translation manifest (default: data/text_manifest.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs.json",
        help="output glyph asset (default: data/chinese_glyphs.json)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing glyph asset",
    )
    parser.add_argument(
        "--record-id",
        action="append",
        dest="record_ids",
        help="include only this confirmed translation record; may be repeated",
    )
    args = parser.parse_args()

    try:
        font_path = args.font.resolve(strict=True)
        manifest_path = args.manifest.resolve(strict=True)
        output_path = args.output.resolve()
        if output_path in {font_path, manifest_path}:
            raise ValueError("output path must differ from the font and translation manifest")
        if output_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"output already exists: {output_path}; pass --overwrite to replace it"
            )
        asset = export_glyphs(
            font_path.read_bytes(),
            json.loads(manifest_path.read_text(encoding="utf-8")),
            args.record_ids,
        )
        output_path.write_text(
            json.dumps(asset, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    print(
        f"Wrote {len(asset['glyphs'])} glyphs to {output_path} "
        f"(font SHA-256: {asset['font']['source_sha256']})"
    )


if __name__ == "__main__":
    main()
