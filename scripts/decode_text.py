"""Decode extracted JSONL text records without discarding unknown tokens."""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

MAP_GROUPS = ("glyph_codes", "special_glyphs", "macro_refs", "controls")


def load_code_map(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    code_map = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(code_map, dict) or code_map.get("schema_version") != 1:
        raise ValueError("decode map schema_version must be 1")

    validated: dict[str, dict[str, dict[str, Any]]] = {}
    for group in MAP_GROUPS:
        entries = code_map.get(group)
        if not isinstance(entries, dict):
            raise ValueError(f"decode map field {group!r} must be an object")
        validated[group] = {}
        for key, entry in entries.items():
            if not isinstance(key, str) or not key.lower().startswith("0x"):
                raise ValueError(f"{group} code keys must be hexadecimal strings")
            try:
                code = int(key[2:], 16)
            except ValueError as exc:
                raise ValueError(f"invalid code-map key: {key!r}") from exc
            if not 0 <= code <= 0xFF:
                raise ValueError(f"code-map key is outside one byte: {key!r}")
            if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
                raise ValueError(f"{group}[{key!r}] must define string text")
            if entry.get("status") not in {"confirmed", "unresolved"}:
                raise ValueError(f"{group}[{key!r}] has an unsupported status")
            normalized_key = f"0x{code:02X}"
            if normalized_key in validated[group]:
                raise ValueError(f"duplicate {group} code: {key!r}")
            validated[group][normalized_key] = entry
    return validated


def decode_record(
    record: dict[str, Any],
    code_map: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    record_id = record.get("id")
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("input record id must be a non-empty string")
    tokens = record.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError(f"{record_id}: tokens must be a list")

    decoded_parts = []
    unknown_tokens = []
    unresolved_tokens = []
    for index, value in enumerate(tokens):
        if not isinstance(value, dict):
            raise ValueError(f"{record_id}: token {index} must be an object")
        offset = value.get("offset")
        raw_hex = value.get("raw_hex")
        kind = value.get("kind")
        if not isinstance(offset, str) or not isinstance(raw_hex, str) or not isinstance(kind, str):
            raise ValueError(f"{record_id}: token {index} needs string offset, raw_hex, and kind")
        try:
            raw_bytes = bytes.fromhex(raw_hex)
        except ValueError as exc:
            raise ValueError(f"{record_id}: invalid raw_hex at {offset}") from exc

        if len(raw_bytes) != 1:
            unknown_tokens.append({"offset": offset, "raw_hex": raw_hex, "kind": kind})
            decoded_parts.append(f"[UNKNOWN {raw_hex}]")
            continue

        code = raw_bytes[0]
        code_key = f"0x{code:02X}"
        if kind == "glyph_code":
            group = "glyph_codes"
        elif kind == "special_glyph":
            group = "special_glyphs"
        elif kind == "macro_ref":
            group = "macro_refs"
        elif kind in {"control", "terminator"}:
            group = "controls"
        else:
            group = ""

        entry = code_map.get(group, {}).get(code_key)
        if entry is None:
            unknown_tokens.append({"offset": offset, "raw_hex": f"{code:02X}", "kind": kind})
            decoded_parts.append(f"[UNKNOWN ${code:02X}]")
            continue

        decoded_parts.append(entry["text"])
        if entry["status"] == "unresolved":
            unresolved_tokens.append(
                {
                    "offset": offset,
                    "raw_hex": f"{code:02X}",
                    "kind": kind,
                    "note": entry.get("note", ""),
                }
            )

    decoded = dict(record)
    decoded["decoded_text"] = "".join(decoded_parts)
    decoded["decode_diagnostics"] = {
        "unknown_tokens": unknown_tokens,
        "unresolved_tokens": unresolved_tokens,
    }
    return decoded


def read_records(text: str, source_name: str) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source_name}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{source_name}:{line_number}: each JSONL item must be an object")
        records.append(record)
    return records


def main() -> None:
    default_map = Path(__file__).resolve().parents[1] / "data" / "text_decode_map.json"
    parser = argparse.ArgumentParser(
        description="Decode extracted JSONL records; unknown tokens remain visible."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="JSONL input file; read standard input when omitted or set to -",
    )
    parser.add_argument("--map", type=Path, default=default_map, help="character/control code map")
    args = parser.parse_args()

    try:
        code_map = load_code_map(args.map)
        if args.input == "-":
            source_text = sys.stdin.read()
            source_name = "<stdin>"
        else:
            input_path = Path(args.input)
            source_text = input_path.read_text(encoding="utf-8")
            source_name = str(input_path)
        records = read_records(source_text, source_name)
        decoded_records = [decode_record(record, code_map) for record in records]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    for record in decoded_records:
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        for token in record["decode_diagnostics"]["unknown_tokens"]:
            print(
                f"{record['id']}: unknown {token['kind']} 0x{token['raw_hex']} "
                f"at {token['offset']}",
                file=sys.stderr,
            )
        for token in record["decode_diagnostics"]["unresolved_tokens"]:
            print(
                f"{record['id']}: unresolved meaning for {token['kind']} "
                f"0x{token['raw_hex']} at {token['offset']}: {token['note']}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
