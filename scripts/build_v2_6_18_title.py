"""Restore the title's SGB attribute transfer without changing status hooks."""
import argparse
import hashlib
import json

from scripts import build_v2_6_17_status as previous
from scripts import build_v2_6_7_dialogue as original
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "cc3851e1fe9bc3b5140447fd31e77503da05b9dc413c08da2cf00031402fb38b"
ORIGINAL_SHA256 = "50c6d78d588ad87caa7dfc25aab970e586322dc568f692144a8168a9767e8dc9"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_18_title_sgb.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_18_title_sgb.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.18-title-sgb.json"
COPY_HOOK = 0xBCFA
SOURCE = 0xBE27
SOURCE_SIZE = 0xB4
COMPONENT = 0x47C00
HELPER_ADDRESS = 0x7C00
HELPER_SIZE = 13
OLD_COPY = bytes.fromhex("21 27 7E 01 B4 00 CD 21 05")
NEW_COPY = bytes.fromhex("F5 E5 21 00 7C 3E 11 EF 00")


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    source = original.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.17 parent ROM failed hash or checksum verification")
    if hashlib.sha256(source).hexdigest() != ORIGINAL_SHA256 or not verify_rom(source).passed:
        raise ValueError("V2.6.7 title source failed hash or checksum verification")
    title_data = source[SOURCE:SOURCE + SOURCE_SIZE]
    if len(title_data) != SOURCE_SIZE:
        raise ValueError("incomplete title attribute data")
    helper = (b"\x21" + (HELPER_ADDRESS + HELPER_SIZE).to_bytes(2, "little")
              + bytes.fromhex("01 B4 00 CD 21 05 21 DB 7E C9"))
    if len(helper) != HELPER_SIZE:
        raise ValueError("unexpected title helper size")
    component = helper + title_data
    result = bytearray(parent)
    for offset in (0, MBC1_MIRROR_OFFSET):
        if parent[COPY_HOOK + offset:COPY_HOOK + offset + len(OLD_COPY)] != OLD_COPY:
            raise ValueError(f"unexpected title copy hook at ${COPY_HOOK + offset:06X}")
        if source[SOURCE + offset:SOURCE + offset + SOURCE_SIZE] != title_data:
            raise ValueError("original title attribute mirror differs")
        if parent[COMPONENT + offset:COMPONENT + offset + len(component)] != b"\xFF" * len(component):
            raise ValueError(f"extension space is occupied at ${COMPONENT + offset:06X}")
        result[COPY_HOOK + offset:COPY_HOOK + offset + len(NEW_COPY)] = NEW_COPY
        result[COMPONENT + offset:COMPONENT + offset + len(component)] = component
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("title SGB candidate failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("title SGB candidate BPS round-trip failed")
    version = {
        "schema_version": 1,
        "version_id": "V2.6.18-title-sgb",
        "parent_version": {"version_id": "V2.6.17-status-snapshot", "sha256": PARENT_SHA256},
        "title_source": {"version_id": "V2.6.7-opening-dialogue", "sha256": ORIGINAL_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "The original attribute block is relocated for the observed title transfer only.",
            "Status wrappers remain in the original bank; other possible consumers remain unverified.",
            "Party-list name corruption is not fixed; other scenes and characters remain unverified.",
        ]},
        "implementation": {"title_copy_hook": "0x7CFA", "bank11_helper": "0x7C00",
                           "bank11_attribute_data": "0x7C0D", "attribute_size": SOURCE_SIZE},
    }
    return result, patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        result, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("title SGB candidate already exists; pass --overwrite to replace it")
        OUTPUT_ROM.write_bytes(result)
        OUTPUT_PATCH.write_bytes(patch)
        OUTPUT_VERSION.write_text(json.dumps(version, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"ROM: {OUTPUT_ROM}")
    print(f"SHA-256: {hashlib.sha256(result).hexdigest()}")
    print(f"BPS: {OUTPUT_PATCH}")


if __name__ == "__main__":
    main()
