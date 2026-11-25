"""Explore guarded dynamic status tile selection from the monitored tile pool."""
import argparse
import hashlib
import json

from scripts import build_v2_6_13_status as previous
from scripts import build_v2_6_9_status_probe as status
from scripts import build_v2_6_10_status as timing
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "d6c1262731774e79f78c4b11b9341a49f03d95d067902a67ce6f8fe5c2f498f4"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_16_status_dynamic.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_16_status_dynamic.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.16-status-dynamic.json"


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    original, labels = previous.build_components(parent_v268)
    component = bytearray(original)
    base = status._bank11_address(status.COMPONENT_START)
    code = status.Code(base + len(component))
    code.labels.update(labels)

    code.label("dynamic_allocate")
    code.emit(bytes.fromhex("21 A0 9F 01 60 00"))
    code.label("dynamic_check_metadata")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE CD"))
    code.address(0xC2, "draw_error")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "dynamic_check_metadata")
    code.emit(bytes.fromhex("21 C0 9F 01 20 00 AF CD 00 05"))
    code.emit(bytes.fromhex("21 00 98 01 40 06"))
    code.label("dynamic_scan")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE 20"))
    code.address(0xDA, "dynamic_scan_next")
    code.emit(bytes.fromhex("FE 40"))
    code.address(0xD2, "dynamic_scan_next")
    code.emit(bytes.fromhex("D6 20 C6 C0 5F 16 9F F0 41 E6 02 20 FA 3E 01 12"))
    code.label("dynamic_scan_next")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "dynamic_scan")

    code.emit(bytes.fromhex("21 C0 9F 11 A0 9F 06 20 0E 16"))
    code.label("dynamic_select")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A B7"))
    code.address(0xC2, "dynamic_select_next")
    code.emit(bytes.fromhex("7D 3D D6 A0 F5 F0 41 E6 02 20 FA F1 12 13 0D"))
    code.address(0xCA, "dynamic_selected")
    code.label("dynamic_select_next")
    code.emit(bytes.fromhex("05"))
    code.address(0xC2, "dynamic_select")
    code.address(0xCD, "dynamic_clear_metadata")
    code.address(0xC3, "draw_error")
    code.label("dynamic_selected")
    code.address(0xCD, "dynamic_backup")
    code.address(0xCD, "dynamic_load")
    code.emit(bytes.fromhex("3E 94 EA F2 C4"))
    code.address(0xC3, "draw_ready")

    for name, stream, reverse in (
        ("dynamic_backup", 0x9E40, False),
        ("dynamic_load", labels["patterns"], True),
        ("dynamic_restore", 0x9E40, True),
    ):
        code.label(name)
        code.emit(bytes.fromhex("21 A0 9F 11") + stream.to_bytes(2, "little") + bytes.fromhex("06 16"))
        code.label(f"{name}_loop")
        code.emit(bytes.fromhex(
            "C5 F0 41 E6 02 20 FA 2A E5 D5 6F 26 00 29 29 29 29 11 00 90 19 D1"
        ))
        if reverse:
            code.emit(bytes.fromhex("E5 D5 E1 D1"))
        code.emit(bytes.fromhex("01 10 00 CD 21 05"))
        if reverse:
            code.emit(bytes.fromhex("54 5D"))
        code.emit(bytes.fromhex("E1 C1 05"))
        code.address(0xC2, f"{name}_loop")
        if name == "dynamic_restore":
            code.address(0xCD, "dynamic_clear_metadata")
        code.emit(b"\xC9")

    code.label("dynamic_clear_metadata")
    code.emit(bytes.fromhex("21 A0 9F 01 60 00 3E CD CD 00 05 C9"))

    code.label("dynamic_draw")
    code.emit(bytes.fromhex("FE 20"))
    code.address(0xDA, "dynamic_draw_native")
    code.emit(bytes.fromhex("FE 36"))
    code.address(0xD2, "dynamic_draw_native")
    code.emit(bytes.fromhex("E5 D6 20 C6 A0 6F 26 9F F0 41 E6 02 20 FA 7E E1"))
    code.label("dynamic_draw_native")
    code.emit(bytes.fromhex("C3 E5 19"))

    extension = code.finish()
    if status.COMPONENT_START + len(component) + len(extension) > status.COMPONENT_END:
        raise ValueError("dynamic status extension exceeds bank $11")

    timing._replace_at(component, labels["reentry_check_map"] - base,
                       bytes.fromhex("F0 41 E6"),
                       b"\xC3" + labels["reentry_snapshot"].to_bytes(2, "little"))
    fast_check = labels["fast_map_loop"] - base + 7
    expected = (bytes.fromhex("FE 20 DA") + labels["fast_menu_check"].to_bytes(2, "little")
                + bytes.fromhex("FE 36 DA") + labels["reentry_fail"].to_bytes(2, "little"))
    timing._replace_at(component, fast_check, expected,
                       b"\xC3" + labels["fast_menu_check"].to_bytes(2, "little") + b"\x00" * 7)
    timing._replace_at(component, labels["check_map"] - base, bytes.fromhex("F0 41 E6"),
                       b"\xC3" + code.labels["dynamic_allocate"].to_bytes(2, "little"))
    restore = status._copy(0x9E40, 0x9200, 0x160)
    timing._replace_all(component, restore,
                        b"\xCD" + code.labels["dynamic_restore"].to_bytes(2, "little")
                        + b"\x00" * (len(restore) - 3), 1)

    start, end = labels["draw_ready"] - base, labels["draw_error"] - base
    draw = bytes(component[start:end])
    old_call = bytes.fromhex("CD E5 19")
    if draw.count(old_call) == 0:
        raise ValueError("status draw routine has no glyph calls")
    replacement = draw.replace(old_call, b"\xCD" + code.labels["dynamic_draw"].to_bytes(2, "little"))
    timing._replace_at(component, start, draw, replacement)
    return bytes(component) + extension, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.13 parent ROM failed hash or checksum verification")
    v268 = status.previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(v268).hexdigest() != status.PARENT_SHA256:
        raise ValueError("V2.6.8 source for component reconstruction has an unexpected hash")
    old, _ = previous.build_components(v268)
    component, locations = build_components(v268)
    expected = old + bytes((0xFF,)) * (len(component) - len(old))
    result = bytearray(parent)
    for offset in (status.COMPONENT_START, status.COMPONENT_START + MBC1_MIRROR_OFFSET):
        if parent[offset:offset + len(expected)] != expected:
            raise ValueError(f"unexpected parent or mirror bytes at ${offset:06X}")
        result[offset:offset + len(component)] = component
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("dynamic status probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("dynamic status probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.16-status-dynamic",
        "parent_version": {"version_id": "V2.6.13-status-fast", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental: dynamically selects 22 tiles in $20-$3F after scanning both active map and snapshot.",
            "Party-list name corruption is not fixed; menu tile collisions still reject masking.",
            "Other scenes, characters, and skills remain unverified.",
        ]},
        "implementation": {"bank11": {name: f"0x{value:04X}" for name, value in locations.items()}},
    }
    return bytes(result), patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("dynamic status output exists; pass --overwrite to replace it")
        OUTPUT_ROM.write_bytes(target)
        OUTPUT_PATCH.write_bytes(patch)
        OUTPUT_VERSION.write_text(json.dumps(version, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"ROM: {OUTPUT_ROM}")
    print(f"SHA-256: {hashlib.sha256(target).hexdigest()}")
    print(f"BPS: {OUTPUT_PATCH}")


if __name__ == "__main__":
    main()
