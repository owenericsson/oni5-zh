"""Build a fixed-slot party-name experiment from V2.6.19."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from scripts import build_v2_6_19_currency as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "231d55ddc843b3922996bfce1d4dba0c23177adec7cc9b847668cac2e4e13072"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_19_1_party_fixed.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_19_1_party_fixed.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.19.1-party-fixed.json"
ASSEMBLY = ROOT / "scripts/party_fixed_v2_6_19_1.asm"
RUNTIME_START = 0x44200
RUNTIME_END = 0x44560


def assemble_runtime() -> bytes:
    with tempfile.TemporaryDirectory(prefix="oni5-fixed-party-") as directory:
        obj = Path(directory) / "runtime.o"
        image = Path(directory) / "runtime.gb"
        symbols = Path(directory) / "runtime.sym"
        for command in (
            ["rgbasm", "-o", str(obj), str(ASSEMBLY)],
            ["rgblink", "-p", "255", "-o", str(image), "-n", str(symbols), str(obj)],
        ):
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
            except FileNotFoundError as exc:
                raise ValueError(f"{command[0]} not found; install RGBDS and add it to PATH") from exc
            except subprocess.CalledProcessError as exc:
                raise ValueError(f"{command[0]} failed: {exc.stderr.strip()}") from exc
        expected = {
            "Entry": "11:4200", "GaroPatterns": "11:4500",
            "NativePatterns": "11:4520", "Currency0": "11:4540",
            "Currency1": "11:4550",
        }
        found = {}
        for line in symbols.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1] in expected:
                found[fields[1]] = fields[0].lower()
        if found != expected:
            raise ValueError(f"unexpected fixed-party runtime layout: {found}")
        data = image.read_bytes()
        if len(data) < RUNTIME_END:
            raise ValueError("assembled image is shorter than the runtime section")
        runtime = data[RUNTIME_START:RUNTIME_END]
        if runtime[0x300:] != bytes(0x60):
            raise ValueError("fixed-party pattern placeholders are not empty")
        return runtime


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.19 parent ROM failed hash or checksum verification")
    asset = json.loads(
        (ROOT / "data/chinese_glyphs_oni5_bank0c_030ee8.json").read_text(encoding="utf-8")
    )
    if asset.get("font", {}).get("source_sha256") != previous.FONT_SHA256:
        raise ValueError("party name glyphs do not match the verified font")
    glyphs = {glyph["character"]: glyph for glyph in asset["glyphs"]}
    patterns = []
    for character in ("伽", "罗"):
        glyph = glyphs[character]
        pattern = bytes.fromhex(glyph["tile_2bpp_hex"])
        if glyph["codepoint"] != f"U+{ord(character):04X}" or len(pattern) != 16:
            raise ValueError(f"invalid glyph for {character}")
        patterns.append(pattern)
    native = bytes.fromhex(
        "04 04 84 84 BE BE 84 84 84 84 9C 9C A6 A6 18 18 "
        "00 00 F0 F0 20 20 44 44 84 84 86 86 88 88 70 70"
    )
    if parent[0x40760:0x40780] != native:
        raise ValueError("fixed-slot native font differs from the observed patterns")
    runtime = bytearray(assemble_runtime())
    runtime[0x300:0x320] = b"".join(patterns)
    runtime[0x320:0x340] = native
    runtime[0x340:0x350] = parent[0x42180:0x42190]
    runtime[0x350:0x360] = parent[0x42190:0x421A0]
    switch = bytes.fromhex("F5 3E 11 EA 00 20 CD 00 42 3E 10 EA 00 20 F1 C9")
    changes = (
        (0x9EE6, bytes.fromhex("11 01 00"), bytes.fromhex("CD E0 00")),
        (0x40001, bytes.fromhex("58 70"), bytes.fromhex("2B 65")),
        (0x423AB, bytes.fromhex("3E 80 EA F2 C4"), bytes.fromhex("CD 30 70 00 00")),
        (0x424B4, bytes.fromhex("AF EA F2 C4"), bytes.fromhex("CD 30 70 00")),
        (0x42525, bytes.fromhex("3E 01 E1 D1 C1 C9"), bytes.fromhex("CD 00 63 C3 19 65")),
        (0x4252B, b"\xFF" * 21, bytes.fromhex(
            "F5 E5 F8 0A 2A FE E9 20 07 E1 F1 3E 02 C3 30 70 E1 F1 C3 58 70")),
        (0x43030, b"\xFF" * len(switch), switch),
        (0x47030, b"\xFF" * len(switch), switch),
        (0x421F0, b"\xFF" * 6, bytes.fromhex("EA 00 20 C3 58 70")),
        (0x461F0, b"\xFF" * 6, bytes.fromhex("EA 00 20 C3 58 70")),
        (RUNTIME_START, b"\xFF" * len(runtime), bytes(runtime)),
    )
    result = bytearray(parent)
    for offset, expected, replacement in changes:
        if len(expected) != len(replacement):
            raise ValueError(f"replacement changes length at ${offset:06X}")
        for start in (offset, offset + MBC1_MIRROR_OFFSET):
            if parent[start:start + len(expected)] != expected:
                raise ValueError(f"unexpected parent or mirror bytes at ${start:06X}")
            result[start:start + len(replacement)] = replacement
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("fixed-party experiment failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("fixed-party BPS round-trip failed")
    version = {
        "schema_version": 1,
        "version_id": "V2.6.19.1-party-fixed",
        "parent_version": {"version_id": "V2.6.19-currency", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Fixed tiles A2 and A3 replace native glyphs while the menu font is loaded.",
            "Fixed slots and restored currency are not collision-scanned; other names, sprites and scenes may be corrupted.",
            "Real party, menu, status, transitions and title-screen behavior require user verification.",
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
            raise FileExistsError("fixed-party output exists; pass --overwrite to replace it")
        OUTPUT_ROM.write_bytes(target)
        OUTPUT_PATCH.write_bytes(patch)
        OUTPUT_VERSION.write_text(json.dumps(version, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(f"ROM: {OUTPUT_ROM}")
    print(f"SHA-256: {hashlib.sha256(target).hexdigest()}")
    print(f"BPS: {OUTPUT_PATCH}")


if __name__ == "__main__":
    main()
