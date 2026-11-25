"""Explore split status tile allocation around the observed $3B background tile."""
import argparse
import hashlib
import json

from scripts import build_v2_6_14_status as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "4450c40bbadd67e00c17a39fc306332d27eb0e4378a3cfbc26905d1038f4e271"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_15_status_split.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_15_status_split.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.15-status-split.json"


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    status, timing = previous.status, previous.timing
    original, labels = previous.build_components(parent_v268)
    component = bytearray(original)
    base = status._bank11_address(status.COMPONENT_START)
    code = status.Code(base + len(component))
    code.labels.update(labels)

    checks = (
        ("check_map", "map_safe", "draw_error"),
        ("reentry_check_map", "reentry_tile_safe", "reentry_fail"),
        ("fast_map_loop", "fast_menu_check", "reentry_fail"),
    )
    for source, safe, fail in checks:
        code.label(f"split_{source}")
        code.emit(bytes.fromhex("FE 27"))
        code.address(0xDA, safe)
        code.emit(bytes.fromhex("FE 3B"))
        code.address(0xCA, safe)
        code.emit(bytes.fromhex("FE 3E"))
        code.address(0xDA, fail)
        code.address(0xC3, safe)

    patterns = labels["patterns"]
    for name, first_src, first_dst, last_src, last_dst in (
        ("split_backup", 0x9270, 0x9E40, 0x93C0, 0x9F80),
        ("split_load", patterns, 0x9270, patterns + 0x140, 0x93C0),
        ("split_restore", 0x9E40, 0x9270, 0x9F80, 0x93C0),
    ):
        code.label(name)
        code.emit(status._copy(first_src, first_dst, 0x140))
        code.emit(status._copy(last_src, last_dst, 0x20))
        code.emit(b"\xC9")
    extension = code.finish()
    if status.COMPONENT_START + len(component) + len(extension) > status.COMPONENT_END:
        raise ValueError("split status extension exceeds bank $11")

    for source, safe, fail in checks:
        start = labels[source] - base + 7
        expected = (bytes.fromhex("FE 27 DA") + labels[safe].to_bytes(2, "little")
                    + bytes.fromhex("FE 3D DA") + labels[fail].to_bytes(2, "little"))
        replacement = b"\xC3" + code.labels[f"split_{source}"].to_bytes(2, "little") + b"\x00" * 7
        timing._replace_at(component, start, expected, replacement)
    for name, source, destination in (
        ("split_backup", 0x9270, 0x9E40),
        ("split_load", patterns, 0x9270),
        ("split_restore", 0x9E40, 0x9270),
    ):
        expected = status._copy(source, destination, 0x160)
        replacement = b"\xCD" + code.labels[name].to_bytes(2, "little") + b"\x00" * (len(expected) - 3)
        timing._replace_all(component, expected, replacement, 1)

    text_labels, _ = status.compile_labels(parent_v268)
    old = bytearray.fromhex("21 00 00")
    new = bytearray(old)
    for column, row, tiles, voiced in text_labels:
        old.extend((0x11, column, row))
        new.extend((0x11, column, row))
        for index, tile in enumerate(tiles):
            if index in voiced:
                old.extend(bytes.fromhex("3E CD 15 CD E5 19 14"))
                new.extend(bytes.fromhex("3E CD 15 CD E5 19 14"))
            old_tile = tile + 7 if tile != status.BG_BLANK else tile
            new_tile = old_tile + 1 if old_tile in (0x3B, 0x3C) else old_tile
            suffix = bytes.fromhex("CD E5 19 1C")
            old.extend(bytes((0x3E, old_tile)) + suffix)
            new.extend(bytes((0x3E, new_tile)) + suffix)
    timing._replace_at(component, labels["draw_ready"] - base, bytes(old), bytes(new))
    return bytes(component) + extension, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.14 parent ROM failed hash or checksum verification")
    v268 = previous.status.previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(v268).hexdigest() != previous.status.PARENT_SHA256:
        raise ValueError("V2.6.8 source for component reconstruction has an unexpected hash")
    old, _ = previous.build_components(v268)
    component, locations = build_components(v268)
    expected = old + bytes((0xFF,)) * (len(component) - len(old))
    result = bytearray(parent)
    for offset in (previous.status.COMPONENT_START, previous.status.COMPONENT_START + MBC1_MIRROR_OFFSET):
        if parent[offset:offset + len(expected)] != expected:
            raise ValueError(f"unexpected parent or mirror bytes at ${offset:06X}")
        result[offset:offset + len(component)] = component
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("split status probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("split status probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.15-status-split",
        "parent_version": {"version_id": "V2.6.14-status-overworld", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental split status tiles: $27-$3A and $3C-$3D.",
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
            raise FileExistsError("split status output exists; pass --overwrite to replace it")
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
