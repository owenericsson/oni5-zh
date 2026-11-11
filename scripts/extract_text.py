"""Extract explicitly bounded text records from a ROM as JSONL."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOKEN_KINDS = {
    "control",
    "glyph_code",
    "macro_ref",
    "special_glyph",
    "terminator",
    "unknown",
}


def parse_hex(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.lower().startswith("0x"):
        raise ValueError(f"{field} must be a hexadecimal string such as 0x1234")

    try:
        parsed = int(value[2:], 16)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid hexadecimal: {value!r}") from exc

    if parsed < 0:
        raise ValueError(f"{field} must not be negative")
    return parsed


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def extract_record(rom: bytes, template: dict[str, Any], rom_sha256: str) -> dict[str, Any]:
    record_id = template.get("id")
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("record id must be a non-empty string")

    source_template = require_object(template.get("source"), f"{record_id}.source")
    bank = require_object(source_template.get("bank"), f"{record_id}.source.bank")
    bank_size = parse_hex(bank.get("size"), f"{record_id}.source.bank.size")
    if bank_size != 0x4000:
        raise ValueError(f"{record_id}: only 16 KB ROM banks are supported")

    parse_hex(bank.get("logical"), f"{record_id}.source.bank.logical")
    physical_bank = parse_hex(bank.get("physical"), f"{record_id}.source.bank.physical")
    event_value = source_template.get("event_command")
    pointer_value = source_template.get("pointer")
    if (event_value is None) == (pointer_value is None):
        raise ValueError(f"{record_id}: source must contain exactly one of event_command or pointer")

    payload = require_object(source_template.get("payload"), f"{record_id}.source.payload")
    payload_start = parse_hex(payload.get("start"), f"{record_id}.payload.start")
    payload_end = parse_hex(payload.get("end_exclusive"), f"{record_id}.payload.end_exclusive")
    terminator = parse_hex(payload.get("terminator"), f"{record_id}.payload.terminator")

    if payload_end <= payload_start:
        raise ValueError(f"{record_id}: payload range must be non-empty")
    if payload_end > len(rom):
        raise ValueError(f"{record_id}: payload range exceeds ROM size")
    if payload_start // bank_size != physical_bank or (payload_end - 1) // bank_size != physical_bank:
        raise ValueError(f"{record_id}: payload crosses or disagrees with the declared physical bank")
    if terminator > 0xFF:
        raise ValueError(f"{record_id}: terminator must fit in one byte")

    if event_value is not None:
        event = require_object(event_value, f"{record_id}.source.event_command")
        event_offset = parse_hex(event.get("rom_offset"), f"{record_id}.event_command.rom_offset")
        event_opcode = parse_hex(event.get("opcode"), f"{record_id}.event_command.opcode")
        cpu_address = parse_hex(event.get("cpu_address"), f"{record_id}.event_command.cpu_address")
        if event_opcode > 0xFF:
            raise ValueError(f"{record_id}: event opcode must fit in one byte")
        if payload_start != event_offset + 1:
            raise ValueError(f"{record_id}: inline payload must immediately follow its event command")
        if event_offset >= len(rom):
            raise ValueError(f"{record_id}: event or payload range exceeds ROM size")
        if event_offset // bank_size != physical_bank:
            raise ValueError(f"{record_id}: event offset does not match the declared physical bank")
        if cpu_address != 0x4000 + event_offset % bank_size:
            raise ValueError(f"{record_id}: CPU address does not match the event ROM offset")
        if rom[event_offset] != event_opcode:
            raise ValueError(
                f"{record_id}: event opcode mismatch at 0x{event_offset:06X}; "
                f"expected 0x{event_opcode:02X}, found 0x{rom[event_offset]:02X}"
            )
    else:
        pointer = require_object(pointer_value, f"{record_id}.source.pointer")
        pointer_address = parse_hex(pointer.get("cpu_address"), f"{record_id}.pointer.cpu_address")
        window = pointer.get("window")
        if window == "lower" and pointer_address < bank_size:
            mapped_offset = physical_bank * bank_size + pointer_address
        elif window == "upper" and bank_size <= pointer_address < 2 * bank_size:
            mapped_offset = physical_bank * bank_size + pointer_address - bank_size
        else:
            raise ValueError(
                f"{record_id}: pointer must use the lower (0x0000-0x3FFF) "
                "or upper (0x4000-0x7FFF) ROM window"
            )
        if payload_start != mapped_offset:
            raise ValueError(
                f"{record_id}: pointer maps to ROM offset 0x{mapped_offset:06X}, "
                f"not payload start 0x{payload_start:06X}"
            )

    raw_payload = rom[payload_start:payload_end]
    if raw_payload[-1] != terminator:
        raise ValueError(
            f"{record_id}: terminator mismatch at 0x{payload_end - 1:06X}; "
            f"expected 0x{terminator:02X}, found 0x{raw_payload[-1]:02X}"
        )
    if raw_payload.count(terminator) != 1:
        raise ValueError(f"{record_id}: terminator must occur exactly once at the payload end")

    annotation_list = template.get("token_annotations", [])
    if not isinstance(annotation_list, list):
        raise ValueError(f"{record_id}.token_annotations must be a list")
    annotations: dict[int, dict[str, Any]] = {}
    for index, value in enumerate(annotation_list):
        annotation = require_object(value, f"{record_id}.token_annotations[{index}]")
        offset = parse_hex(annotation.get("offset"), f"{record_id}.token_annotations[{index}].offset")
        code = parse_hex(annotation.get("code"), f"{record_id}.token_annotations[{index}].code")
        kind = annotation.get("kind")
        if not isinstance(kind, str):
            raise ValueError(f"{record_id}: token kind at annotation {index} must be a string")
        if offset < payload_start or offset >= payload_end:
            raise ValueError(f"{record_id}: token annotation offset is outside the payload")
        if code > 0xFF or rom[offset] != code:
            raise ValueError(f"{record_id}: token annotation code does not match ROM at 0x{offset:06X}")
        if kind not in TOKEN_KINDS:
            raise ValueError(f"{record_id}: unsupported token kind {kind!r} at 0x{offset:06X}")
        if offset in annotations:
            raise ValueError(f"{record_id}: duplicate token annotation at 0x{offset:06X}")
        if (code == terminator) != (kind == "terminator"):
            raise ValueError(f"{record_id}: terminator token annotation is inconsistent at 0x{offset:06X}")
        for field in ("meaning", "display"):
            if field in annotation and not isinstance(annotation[field], str):
                raise ValueError(f"{record_id}: token {field} at 0x{offset:06X} must be a string")
        annotations[offset] = annotation

    tokens = []
    unknown_tokens = []
    for offset in range(payload_start, payload_end):
        code = rom[offset]
        annotation = annotations.get(offset)
        if annotation:
            kind = annotation["kind"]
        elif offset == payload_end - 1:
            kind = "terminator"
        else:
            kind = "unknown"
        token: dict[str, Any] = {
            "offset": f"0x{offset:06X}",
            "raw_hex": f"{code:02X}",
            "kind": kind,
        }
        if annotation:
            for key in ("meaning", "display"):
                if key in annotation:
                    token[key] = annotation[key]
        tokens.append(token)
        if kind == "unknown":
            unknown_tokens.append({"offset": token["offset"], "raw_hex": token["raw_hex"]})

    source = dict(source_template)
    source["rom_sha256"] = rom_sha256
    result: dict[str, Any] = {
        "schema_version": 1,
        "id": record_id,
        "source": source,
        "raw_hex": raw_payload.hex(" ").upper(),
        "tokens": tokens,
        "observations": template.get("observations", []),
        "translation": template.get(
            "translation",
            {"status": "untranslated", "segments": []},
        ),
        "verification": template.get("verification", []),
        "diagnostics": {"unknown_tokens": unknown_tokens},
    }
    return result


def load_manifest(path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    root = require_object(manifest, "manifest")
    if root.get("schema_version") != 1:
        raise ValueError("manifest schema_version must be 1")
    records = root.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("manifest records must be a non-empty list")
    templates = [require_object(record, f"records[{index}]") for index, record in enumerate(records)]
    record_ids = [record.get("id") for record in templates]
    if any(not isinstance(record_id, str) or not record_id for record_id in record_ids):
        raise ValueError("every manifest record must have a non-empty string id")
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("manifest record ids must be unique")
    return templates


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract explicitly bounded inline text records as JSONL."
    )
    parser.add_argument("rom", type=Path, help="read-only source ROM")
    parser.add_argument("manifest", type=Path, help="curated JSON boundary and annotation manifest")
    args = parser.parse_args()

    try:
        rom = args.rom.read_bytes()
        rom_sha256 = hashlib.sha256(rom).hexdigest()
        templates = load_manifest(args.manifest)
        records = [extract_record(rom, template, rom_sha256) for template in templates]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    for record in records:
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        for token in record["diagnostics"]["unknown_tokens"]:
            print(
                f"{record['id']}: unknown byte 0x{token['raw_hex']} "
                f"at ROM offset {token['offset']}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
