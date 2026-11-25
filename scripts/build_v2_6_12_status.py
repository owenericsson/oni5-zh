"""Handle menu and cached status markers during the status transition."""
import argparse
import hashlib
import json

from scripts import build_v2_6_11_status as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, build_menu_candidate
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "d541bb0af526d76a708a7c709a4bc062014becf84710a1feab0f5d38c4e8202c"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_12_status_reentry.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_12_status_reentry.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.12-status-reentry.json"
CACHED_FAILURE = 0x96


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    original, labels = previous.build_components(parent_v268)
    component = bytearray(original)
    base = previous.previous.previous._bank11_address(previous.previous.previous.COMPONENT_START)
    code = previous.previous.previous.Code(base + len(component))
    code.labels.update(labels)
    code.label("reentry_mask")
    code.emit(bytes.fromhex("F5 C5 D5 E5 F3 FA F2 C4 B7"))
    code.address(0xCA, "reentry_check_registers")
    code.emit(bytes.fromhex("FE 80"))
    code.address(0xCA, "reentry_check_registers")
    code.emit(bytes.fromhex("FE 94"))
    code.address(0xC2, "mask_skip")
    code.label("reentry_check_registers")
    for register, expected in ((0x40, 0xC7), (0x4A, 0x88), (0x4B, 0x07)):
        code.emit(bytes((0xF0, register, 0xFE, expected)))
        code.address(0xC2, "reentry_fail")
    for register in (0x42, 0x43):
        code.emit(bytes((0xF0, register, 0xE6, 0x07)))
        code.address(0xC2, "reentry_fail")

    code.emit(bytes.fromhex("21 00 9C 01 40 02"))
    code.label("reentry_check_snapshot")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE CD"))
    code.address(0xC2, "reentry_fail")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "reentry_check_snapshot")

    code.emit(bytes.fromhex("FA F2 C4 FE 94"))
    code.address(0xCA, "reentry_snapshot")
    code.emit(bytes.fromhex("21 40 9E 01 C0 01"))
    code.label("reentry_check_backup")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE CD"))
    code.address(0xC2, "reentry_fail")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "reentry_check_backup")

    code.emit(bytes.fromhex("21 00 98 01 00 04"))
    code.label("reentry_check_map")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE 20"))
    code.address(0xDA, "reentry_tile_safe")
    code.emit(bytes.fromhex("FE 36"))
    code.address(0xDA, "reentry_fail")
    code.label("reentry_tile_safe")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "reentry_check_map")

    code.emit(bytes.fromhex("FA F2 C4 FE 80"))
    code.address(0xC2, "reentry_snapshot")
    menu_asset = json.loads((ROOT / "data/menu_chinese_glyphs.json").read_text(encoding="utf-8"))
    menu_tiles = [int(glyph["tile"], 16) for glyph in build_menu_candidate(menu_asset)["custom_glyphs"]]
    code.emit(bytes.fromhex("21 00 98 01 00 04"))
    code.label("reentry_check_menu_tiles")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A"))
    for tile in menu_tiles:
        code.emit(bytes((0xFE, tile)))
        code.address(0xCA, "reentry_fail")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "reentry_check_menu_tiles")

    code.label("reentry_snapshot")
    code.emit(bytes.fromhex("F0 42 6F 26 00 29 29 01 00 98 09 11 00 9C 3E 12"))
    code.address(0xC3, "snapshot_row")

    code.label("reentry_fail")
    code.emit(bytes.fromhex("FA F2 C4 FE 80"))
    code.address(0xCA, "mask_skip")
    code.emit(bytes.fromhex("FE 94"))
    code.address(0xC2, "mask_fail")
    code.emit(bytes((0x3E, CACHED_FAILURE)) + bytes.fromhex("EA F2 C4"))
    code.address(0xC3, "mask_skip")

    code.label("reentry_restore")
    code.emit(bytes.fromhex("F5 FA F2 C4 FE") + bytes((CACHED_FAILURE,)))
    code.address(0xC2, "reentry_restore_done")
    code.emit(bytes.fromhex("3E 94 EA F2 C4"))
    code.label("reentry_restore_done")
    code.emit(bytes.fromhex("F1 F5 C5 D5"))
    code.labels["restore_dispatch_tail"] = labels["restore_dispatch"] + 3
    code.address(0xC3, "restore_dispatch_tail")

    extension = code.finish()
    if previous.previous.previous.COMPONENT_START + len(component) + len(extension) > previous.previous.previous.COMPONENT_END:
        raise ValueError("status reentry extension exceeds bank $11")
    for name, target in (("scroll_mask_enter", "reentry_mask"), ("restore_dispatch", "reentry_restore")):
        previous.previous._replace_at(component, labels[name] - base, bytes.fromhex("F5 C5 D5"),
                                      b"\xC3" + code.labels[target].to_bytes(2, "little"))
    return bytes(component) + extension, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.11 parent ROM failed hash or checksum verification")
    v268 = previous.previous.previous.previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(v268).hexdigest() != previous.previous.previous.PARENT_SHA256:
        raise ValueError("V2.6.8 source for component reconstruction has an unexpected hash")
    old, _ = previous.build_components(v268)
    component, locations = build_components(v268)
    expected = old + bytes((0xFF,)) * (len(component) - len(old))
    result = bytearray(parent)
    for start in (previous.previous.previous.COMPONENT_START,
                  previous.previous.previous.COMPONENT_START + MBC1_MIRROR_OFFSET):
        if parent[start:start + len(expected)] != expected:
            raise ValueError(f"unexpected parent or mirror bytes at ${start:06X}")
        result[start:start + len(component)] = component
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("status reentry probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("status reentry probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.12-status-reentry",
        "parent_version": {"version_id": "V2.6.11-status-scroll", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental: observed village, current character and empty skill window only.",
            "An exclamation mark indicates that scene-specific safety checks did not pass.",
            "Other characters, learned skills and scenes remain unverified.",
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
            raise FileExistsError("status reentry output exists; pass --overwrite to replace it")
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
