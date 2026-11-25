"""Replace the two menu currency glyphs without changing historical assets."""
import argparse
import hashlib
import json

from scripts import build_v2_6_18_title as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, build_menu_candidate
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "a2edf9b7e89d510f21776935476938e039df2ae0be30c274821e41bb9ae476e3"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_19_currency.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_19_currency.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.19-currency.json"
PATTERN_START = 0x42100
CURRENCY_TEXT = 0x66B9
FONT_SHA256 = "37b51f4f2a094a952a3cb481090c2185922a65b90c228e5bdad7b4c445ca7939"


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.18 parent ROM failed hash or checksum verification")
    old = json.loads((ROOT / "data/menu_chinese_glyphs.json").read_text(encoding="utf-8"))
    new = json.loads((ROOT / "data/chinese_glyphs_oni5_currency.json").read_text(encoding="utf-8"))
    if new.get("schema_version") != 1 or new.get("font", {}).get("source_sha256") != FONT_SHA256:
        raise ValueError("currency glyph source does not match the verified font")
    if [glyph["character"] for glyph in new["glyphs"]] != ["金", "币"]:
        raise ValueError("currency glyphs must be 金 and 币 in that order")
    mapping = build_menu_candidate(old)["custom_glyphs"]
    old_by_character = {glyph["character"]: glyph for glyph in old["glyphs"]}
    new_by_character = {glyph["character"]: glyph for glyph in new["glyphs"]}
    result = bytearray(parent)
    for old_character, new_character, expected_tile in (("盘", "金", 0x89), ("缠", "币", 0x8C)):
        index = next(i for i, glyph in enumerate(mapping) if glyph["character"] == old_character)
        if int(mapping[index]["tile"], 16) != expected_tile:
            raise ValueError(f"unexpected tile for {old_character}")
        old_pattern = bytes.fromhex(old_by_character[old_character]["tile_2bpp_hex"])
        glyph = new_by_character[new_character]
        if glyph["codepoint"] != f"U+{ord(new_character):04X}":
            raise ValueError(f"unexpected codepoint for {new_character}")
        new_pattern = bytes.fromhex(glyph["tile_2bpp_hex"])
        if len(old_pattern) != 16 or len(new_pattern) != 16:
            raise ValueError("currency patterns must be 16 bytes")
        for mirror in (0, MBC1_MIRROR_OFFSET):
            offset = PATTERN_START + index * 16 + mirror
            if parent[offset:offset + 16] != old_pattern:
                raise ValueError(f"unexpected menu glyph bytes at ${offset:06X}")
            result[offset:offset + 16] = new_pattern
    for mirror in (0, MBC1_MIRROR_OFFSET):
        if parent[CURRENCY_TEXT + mirror:CURRENCY_TEXT + mirror + 6] != bytes.fromhex("09 0C 4D 4D 4D 7F"):
            raise ValueError("unexpected currency text encoding")
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("currency candidate failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("currency candidate BPS round-trip failed")
    version = {
        "schema_version": 1,
        "version_id": "V2.6.19-currency",
        "parent_version": {"version_id": "V2.6.18-title-sgb", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Currency glyphs replace 盘缠 with 金币 in the existing menu tile slots.",
            "Party-list name corruption is not fixed; real menu and status transitions require verification.",
        ]},
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
            raise FileExistsError("currency candidate already exists; pass --overwrite to replace it")
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
