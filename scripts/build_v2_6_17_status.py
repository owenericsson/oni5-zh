"""Guard menu font restoration against the actual masked snapshot."""
import argparse
import hashlib
import json

from scripts import build_v2_6_16_status as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "eabcb26669d372e2da70172b363d0db54e7ec0c97f323f36884aba9e0d587773"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_17_status_snapshot.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_17_status_snapshot.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.17-status-snapshot.json"


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    status, timing = previous.status, previous.timing
    original, labels = previous.build_components(parent_v268)
    component = bytearray(original)
    base = status._bank11_address(status.COMPONENT_START)
    code = status.Code(base + len(component))
    code.labels.update(labels)
    code.label("snapshot_menu_guard")
    code.emit(bytes.fromhex("FA F2 C4 FE 80"))
    code.address(0xC2, "mask_open_active")
    code.emit(bytes.fromhex("21 00 9C 01 40 02"))
    code.address(0x11, "menu_tile_table")
    code.label("snapshot_menu_scan")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A 5F 1A B7"))
    code.address(0xC2, "snapshot_menu_fail")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "snapshot_menu_scan")
    code.address(0xC3, "mask_open_active")
    code.label("snapshot_menu_fail")
    code.emit(bytes.fromhex("3E 88 E0 4A 21 00 9C 01 40 02 3E CD CD 00 05"))
    code.address(0xC3, "reentry_fail")
    extension = code.finish()
    if status.COMPONENT_START + len(component) + len(extension) > status.COMPONENT_END:
        raise ValueError("snapshot guard extension exceeds bank $11")
    timing._replace_at(component, labels["fast_map_setup"] - base, bytes.fromhex("21 00 98"),
                       b"\xC3" + labels["reentry_snapshot"].to_bytes(2, "little"))
    old = bytes.fromhex("AF E0 4A C3") + labels["mask_open_active"].to_bytes(2, "little")
    new = bytes.fromhex("AF E0 4A C3") + code.labels["snapshot_menu_guard"].to_bytes(2, "little")
    timing._replace_all(component, old, new, 1)
    return bytes(component) + extension, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.16 parent ROM failed hash or checksum verification")
    status = previous.status
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
        raise ValueError("snapshot guard probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("snapshot guard probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.17-status-snapshot",
        "parent_version": {"version_id": "V2.6.16-status-dynamic", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental: checks the full temporary window snapshot before restoring menu glyphs.",
            "Party-list name corruption is not fixed; visible menu glyphs still reject masking.",
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
            raise FileExistsError("snapshot status output exists; pass --overwrite to replace it")
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
