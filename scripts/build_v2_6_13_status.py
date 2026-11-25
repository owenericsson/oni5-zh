"""Optimize status transition checks without changing their safety conditions."""
import argparse
import hashlib
import json

from scripts import build_v2_6_12_status as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, build_menu_candidate
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "a8125cedf3d231b6914d7f3a0fedc3f5506f28259cff75c3bcd0cc16aa192d71"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_13_status_fast.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_13_status_fast.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.13-status-fast.json"


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    original, labels = previous.build_components(parent_v268)
    component = bytearray(original)
    status = previous.previous.previous.previous
    base = status._bank11_address(status.COMPONENT_START)
    code = status.Code(base + len(component))
    code.labels.update(labels)
    code.label("fast_map_setup")
    code.emit(bytes.fromhex("21 00 98 01 00 04 FA F2 C4 FE 80"))
    code.address(0xC2, "reentry_check_map")
    code.address(0x11, "menu_tile_table")
    code.label("fast_map_loop")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE 20"))
    code.address(0xDA, "fast_menu_check")
    code.emit(bytes.fromhex("FE 36"))
    code.address(0xDA, "reentry_fail")
    code.label("fast_menu_check")
    code.emit(bytes.fromhex("5F 1A B7"))
    code.address(0xC2, "reentry_fail")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "fast_map_loop")
    code.address(0xC3, "reentry_snapshot")
    code.emit(bytes((0xFF,)) * (-(code.base + len(code.data)) & 0xFF))
    code.label("menu_tile_table")
    asset = json.loads((ROOT / "data/menu_chinese_glyphs.json").read_text(encoding="utf-8"))
    menu_tiles = {int(glyph["tile"], 16) for glyph in build_menu_candidate(asset)["custom_glyphs"]}
    code.emit(bytes(int(tile in menu_tiles) for tile in range(256)))
    extension = code.finish()
    if status.COMPONENT_START + len(component) + len(extension) > status.COMPONENT_END:
        raise ValueError("fast status extension exceeds bank $11")
    previous.previous.previous._replace_at(
        component, labels["reentry_check_map"] - base - 6, bytes.fromhex("21 00 98 01 00 04"),
        b"\xC3" + code.labels["fast_map_setup"].to_bytes(2, "little") + b"\x00" * 3,
    )
    return bytes(component) + extension, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.12 parent ROM failed hash or checksum verification")
    status = previous.previous.previous.previous
    v268 = status.previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(v268).hexdigest() != status.PARENT_SHA256:
        raise ValueError("V2.6.8 source for component reconstruction has an unexpected hash")
    old, _ = previous.build_components(v268)
    component, locations = build_components(v268)
    expected = old + bytes((0xFF,)) * (len(component) - len(old))
    result = bytearray(parent)
    for start in (status.COMPONENT_START, status.COMPONENT_START + MBC1_MIRROR_OFFSET):
        if parent[start:start + len(expected)] != expected:
            raise ValueError(f"unexpected parent or mirror bytes at ${start:06X}")
        result[start:start + len(component)] = component
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("fast status probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("fast status probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.13-status-fast",
        "parent_version": {"version_id": "V2.6.12-status-reentry", "sha256": PARENT_SHA256},
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
            raise FileExistsError("fast status output exists; pass --overwrite to replace it")
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
