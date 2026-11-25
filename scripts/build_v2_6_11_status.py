"""Handle wrapped background scrolling in the status transition mask."""
import argparse
import hashlib
import json

from scripts import build_v2_6_10_status as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "7d15aa75c524130f62c60383a398ea524988b7ab36e544d3fdd338b56966d578"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_11_status_scroll.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_11_status_scroll.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.11-status-scroll.json"


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    original, labels = previous.build_components(parent_v268)
    component = bytearray(original)
    base = previous.previous._bank11_address(previous.previous.COMPONENT_START)
    code = previous.previous.Code(base + len(component))
    code.labels.update(labels)
    code.label("scroll_mask_enter")
    code.emit(bytes.fromhex("F5 C5 D5 E5 F3 FA F2 C4 B7"))
    code.address(0xC2, "mask_skip")
    for register, expected in ((0x40, 0xC7), (0x4A, 0x88), (0x4B, 0x07)):
        code.emit(bytes((0xF0, register, 0xFE, expected)))
        code.address(0xC2, "mask_fail")
    for register in (0x42, 0x43):
        code.emit(bytes((0xF0, register, 0xE6, 0x07)))
        code.address(0xC2, "mask_fail")
    code.emit(bytes.fromhex("21 00 9C 01 00 04"))
    code.label("scroll_check_window_map")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE CD"))
    code.address(0xC2, "mask_fail")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "scroll_check_window_map")
    code.emit(bytes.fromhex("21 00 98 01 00 04"))
    code.label("scroll_check_visible_tiles")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE 20"))
    code.address(0xDA, "scroll_visible_tile_safe")
    code.emit(bytes.fromhex("FE 36"))
    code.address(0xDA, "mask_fail")
    code.label("scroll_visible_tile_safe")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "scroll_check_visible_tiles")
    code.emit(bytes.fromhex("F0 42 6F 26 00 29 29 01 00 98 09 11 00 9C 3E 12"))
    code.label("snapshot_row")
    code.emit(bytes.fromhex("F5 E5 F0 43 CB 3F CB 3F CB 3F 4F 7D 81 6F 06 14"))
    code.label("snapshot_tile")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 7E 12 13 2C 7D E6 1F"))
    code.address(0xC2, "snapshot_no_column_wrap")
    code.emit(bytes.fromhex("7D D6 20 6F"))
    code.label("snapshot_no_column_wrap")
    code.emit(bytes.fromhex("05"))
    code.address(0xC2, "snapshot_tile")
    code.emit(bytes.fromhex("E1 01 20 00 09 7C FE 9C"))
    code.address(0xC2, "snapshot_no_row_wrap")
    code.emit(bytes.fromhex("26 98"))
    code.label("snapshot_no_row_wrap")
    code.emit(bytes.fromhex("E5 62 6B 01 0C 00 09 54 5D E1 F1 3D"))
    code.address(0xC2, "snapshot_row")
    code.emit(bytes.fromhex("AF E0 4A"))
    code.address(0xC3, "mask_open_active")
    extension = code.finish()
    if previous.previous.COMPONENT_START + len(component) + len(extension) > previous.previous.COMPONENT_END:
        raise ValueError("scroll-aware status mask exceeds bank $11")
    previous._replace_at(component, labels["mask_enter"] - base, bytes.fromhex("F5 C5 D5"),
                         b"\xC3" + code.labels["scroll_mask_enter"].to_bytes(2, "little"))
    return bytes(component) + extension, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.10 parent ROM failed hash or checksum verification")
    v268 = previous.previous.previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(v268).hexdigest() != previous.previous.PARENT_SHA256:
        raise ValueError("V2.6.8 source for component reconstruction has an unexpected hash")
    old, _ = previous.build_components(v268)
    component, locations = build_components(v268)
    expected = old + bytes((0xFF,)) * (len(component) - len(old))
    result = bytearray(parent)
    for start in (previous.previous.COMPONENT_START,
                  previous.previous.COMPONENT_START + MBC1_MIRROR_OFFSET):
        if parent[start:start + len(expected)] != expected:
            raise ValueError(f"unexpected parent or mirror bytes at ${start:06X}")
        result[start:start + len(component)] = component
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("scroll-aware status probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("status scroll probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.11-status-scroll",
        "parent_version": {"version_id": "V2.6.10-status-timing", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental: initial status entry only, with tile-aligned scrolling.",
            "An exclamation mark indicates that scene-specific safety checks did not pass.",
            "Skill-window return, other characters and scenes remain unverified.",
        ]},
        "implementation": {"bank11": {name: f"0x{value:04X}" for name, value in locations.items()}},
    }
    return result, patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("status scroll output exists; pass --overwrite to replace it")
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
