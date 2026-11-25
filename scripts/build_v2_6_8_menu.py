"""Restore the original font before drawing the character status details."""
import argparse
import hashlib
import json

from scripts import build_v2_6_7_dialogue as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_text_comparison_pilot import bank_cpu_address
from scripts.build_v2_6_4_dialogue import ROOT
from scripts.rom_checksums import update_checksums, verify_rom

EXPECTED_PARENT_SHA256 = "50c6d78d588ad87caa7dfc25aab970e586322dc568f692144a8168a9767e8dc9"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_8_status_fix.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_8_status_fix.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.8-status-fix.json"
STATUS_HOOK = 0x89E0
STATUS_WRAPPER = 0xBE63
ROUTER = 0x43058
MENU_RESTORE = 0x6400
OLD_ROUTER = 0x6540
OLD_STATUS_CODE = bytes.fromhex("F5 E5 21 56 20 3E 01 EF")


def build_status_wrapper() -> bytes:
    return bytes.fromhex("E5 CD E0 00 E1") + OLD_STATUS_CODE + bytes.fromhex("C3 E8 49")


def build_router() -> bytes:
    return_address = 0x4000 + STATUS_WRAPPER - 0x8000 + 4
    code = bytearray(bytes.fromhex("C5 D5 E5 F5 F8 0E 2A FE"))
    code.extend((return_address & 0xFF, 0x20, 0))
    low_branch = len(code) - 1
    code.extend(bytes((0x7E, 0xFE, return_address >> 8, 0x20, 0)))
    high_branch = len(code) - 1
    code.extend(bytes.fromhex("F1 E1 D1 C1 CD"))
    code.extend(MENU_RESTORE.to_bytes(2, "little"))
    code.extend(bytes.fromhex("3E 02 C9"))
    fallback = len(code)
    code.extend(bytes.fromhex("F1 E1 D1 C1 C3") + OLD_ROUTER.to_bytes(2, "little"))
    for branch in (low_branch, high_branch):
        code[branch] = fallback - branch - 1
    return bytes(code)


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != EXPECTED_PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.7 parent ROM failed SHA-256 or checksum verification")
    wrapper, router = build_status_wrapper(), build_router()
    if parent[STATUS_HOOK:STATUS_HOOK + len(OLD_STATUS_CODE)] != OLD_STATUS_CODE:
        raise ValueError("unexpected status-screen entry code")
    if parent[STATUS_WRAPPER:STATUS_WRAPPER + len(wrapper)] != b"\xFF" * len(wrapper):
        raise ValueError("status wrapper space is not free")
    if parent[ROUTER:ROUTER + len(router)] != b"\xFF" * len(router):
        raise ValueError("menu transition router space is not free")
    if parent[0x40000:0x40004] != bytes.fromhex("CD 40 65 C9"):
        raise ValueError("unexpected bank $10 gateway")
    if parent[0x61:0x78] != bytes.fromhex("FE 02 28 0F FE 03 28 10 B7 CA F7 00 F1 FA F0 C4 C3 0C 18 F1 21 03 00"):
        raise ValueError("unexpected fixed gateway return handler")
    if parent[0x42400:0x42409] != bytes.fromhex("C5 D5 E5 F5 FA F2 C4 FE 80"):
        raise ValueError("unexpected menu restore helper")
    target = bytearray(parent)
    changes = (
        (STATUS_HOOK, b"\xC3" + (0x4000 + STATUS_WRAPPER - 0x8000).to_bytes(2, "little") + b"\x00" * 5),
        (STATUS_WRAPPER, wrapper),
        (0x40001, bank_cpu_address(ROUTER).to_bytes(2, "little")),
        (ROUTER, router),
    )
    for offset, data in changes:
        mirror = MBC1_MIRROR_OFFSET + offset
        if parent[mirror:mirror + len(data)] != parent[offset:offset + len(data)]:
            raise ValueError(f"parent mirror differs at ${offset:06X}")
        target[offset:offset + len(data)] = data
        target[mirror:mirror + len(data)] = data
    target = update_checksums(target)
    if len(target) != len(parent) or not verify_rom(target).passed:
        raise ValueError("V2.6.8 ROM failed size or checksum verification")
    patch = create_bps_patch(parent, target)
    if apply_bps_patch(parent, patch) != target:
        raise ValueError("V2.6.7-to-V2.6.8 BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.8-status-fix",
        "parent_version": {"version_id": "V2.6.7-opening-dialogue", "sha256": EXPECTED_PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(target).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "The fix targets the observed character status details path only.",
            "Status display, return to the menu, and other paths require SameBoy verification.",
        ]},
    }
    return bytes(target), patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace existing V2.6.8 outputs")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("V2.6.8 output already exists; pass --overwrite to replace it")
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
