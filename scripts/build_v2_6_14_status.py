"""Explore an alternate status tile range for the observed overworld scene."""
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
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_14_status_overworld.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_14_status_overworld.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.14-status-overworld.json"
FIRST_TILE = 0x27


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    original, labels = previous.build_components(parent_v268)
    component = bytearray(original)
    base = status._bank11_address(status.COMPONENT_START)
    replace = timing._replace_at
    for name in ("check_map", "reentry_check_map", "fast_map_loop"):
        start = labels[name] - base
        end = start + 18
        section = bytes(component[start:end])
        if section.count(b"\xFE\x20") != 1 or section.count(b"\xFE\x36") != 1:
            raise ValueError(f"unexpected tile range checks at {name}")
        replacement = section.replace(b"\xFE\x20", bytes((0xFE, FIRST_TILE)))
        replacement = replacement.replace(b"\xFE\x36", bytes((0xFE, FIRST_TILE + 22)))
        replace(component, start, section, replacement)
    timing._replace_all(
        component, bytes.fromhex("21 00 92"), bytes.fromhex("21 70 92"), 1
    )
    timing._replace_all(
        component, bytes.fromhex("11 00 92"), bytes.fromhex("11 70 92"), 2
    )

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
            suffix = bytes.fromhex("CD E5 19 1C")
            old.extend(bytes((0x3E, tile)) + suffix)
            new_tile = tile + FIRST_TILE - status.FIRST_TILE if tile != status.BG_BLANK else tile
            new.extend(bytes((0x3E, new_tile)) + suffix)
    replace(component, labels["draw_ready"] - base, bytes(old), bytes(new))
    return bytes(component), labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.13 parent ROM failed hash or checksum verification")
    v268 = status.previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(v268).hexdigest() != status.PARENT_SHA256:
        raise ValueError("V2.6.8 source for component reconstruction has an unexpected hash")
    old, _ = previous.build_components(v268)
    component, locations = build_components(v268)
    result = bytearray(parent)
    for start in (status.COMPONENT_START, status.COMPONENT_START + MBC1_MIRROR_OFFSET):
        if parent[start:start + len(old)] != old:
            raise ValueError(f"unexpected parent or mirror bytes at ${start:06X}")
        result[start:start + len(component)] = component
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("overworld status probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("overworld status probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.14-status-overworld",
        "parent_version": {"version_id": "V2.6.13-status-fast", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental: alternate tiles observed in the overworld only; village and other scenes remain unverified.",
            "Party-list name corruption is not fixed by this status tile probe.",
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
            raise FileExistsError("status overworld output exists; pass --overwrite to replace it")
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
