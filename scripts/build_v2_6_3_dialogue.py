"""Build the short Shizuna dialogue from the accepted V2.6.2 ROM."""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, MENU_EXPANDED_SIZE
from scripts.build_noticeboard_glyph_probe import CachedGlyph
from scripts.build_opening_text_preview_patch import (
    FONT_BANK,
    FONT_DESCRIPTOR,
    FONT_LENGTH,
    load_glyph_patterns,
)
from scripts.build_text_comparison_pilot import (
    PilotContext,
    align_up,
    bank_cpu_address,
    build_loader_helper,
    build_restore_helper,
)
from scripts.build_v2_6_1_single_dialogue import RESTORE_WRAPPER_OFFSET, SOURCE_ROM, SOURCE_SIZE
from scripts.build_v2_6_2_dialogue import OUTPUT_ROM as V2_6_2_ROM
from scripts.build_v2_6_prologue_patch import EXPECTED_SOURCE_SHA256
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_V2_6_2_SHA256 = "6f831505dccb94d250a58b2f8098750aae51d94a0ab83cff1271fa990bbe5cf9"
OUTPUT_ROM = ROOT / "roms" / "oni5_v2_6_3_opening_dialogue.gb"
OUTPUT_PATCH = ROOT / "roms" / "oni5_v2_6_3_opening_dialogue.bps"
OUTPUT_VERSION = ROOT / "versions" / "V2.6.3-opening-dialogue.json"
HELPER_START = SOURCE_SIZE + 0x0900
HELPER_END = SOURCE_SIZE + 0x0B00
MARKER = 0x8A
RESTORE_CURSOR = 0x17
TEXT_START = 0x013411
ORIGINAL_TEXT = bytes.fromhex("AD 7D 3B 95 CC")
TRANSLATED_TEXT = bytes.fromhex("C6 7D 3B B6 CC")
GLYPH_TILES = (("静", 0xA9), ("那", 0xAF), ("常", 0x9D), ("叶", 0x8E), ("丸", 0xA7))


def _read_macro(rom: bytes, code: int) -> bytes:
    base = 0x0C * 0x4000
    table = base + 0x200 + 2 * (code - 0x80)
    pointer = int.from_bytes(rom[table:table + 2], "little")
    if pointer >= 0x4000:
        raise ValueError(f"macro ${code:02X} points outside bank $0C")
    size = rom[base + pointer]
    return rom[base + pointer + 1:base + pointer + 1 + size]


def _build_preload_wrapper(address: int, old_restore_body: int, loader: int) -> bytes:
    # The old restore body ends with POP AF/DE/BC; the trampoline supplies that stack frame.
    code = bytearray(bytes.fromhex("CD"))
    code.extend((address + 17).to_bytes(2, "little"))
    code.extend(bytes.fromhex("F5 FA F0 C4 F5 CD"))
    code.extend(loader.to_bytes(2, "little"))
    code.extend(bytes.fromhex("F1 EA F0 C4 F1 C9"))
    code.extend(bytes.fromhex("C5 D5 F5 C3"))
    code.extend(old_restore_body.to_bytes(2, "little"))
    return bytes(code)


def _build_restore_dispatcher(old_dispatcher: int, wrapper: int, restore: int) -> bytes:
    code = bytearray(bytes.fromhex("CD"))
    code.extend(old_dispatcher.to_bytes(2, "little"))
    code.extend(bytes.fromhex("FA F2 C4 FE 85 20 00 F0 AA FE 04 20 00 F0 AE FE 34 20 00 F0 AD FE 09 20 00 CD"))
    branches = (9, 15, 21, 27)
    code.extend(wrapper.to_bytes(2, "little"))
    next_check = len(code)
    for operand in branches:
        displacement = next_check - (operand + 1)
        if not -128 <= displacement <= 127:
            raise ValueError("restore dispatcher branch is out of range")
        code[operand] = displacement & 0xFF
    code.extend(bytes.fromhex("FA F2 C4 FE"))
    code.append(MARKER)
    code.extend(bytes.fromhex("C0 F0 AA FE 04 C0 F0 AE FE 34 C0 F0 AD FE"))
    code.append(RESTORE_CURSOR)
    code.extend(bytes.fromhex("C0 C3"))
    code.extend(restore.to_bytes(2, "little"))
    return bytes(code)


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = V2_6_2_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != EXPECTED_V2_6_2_SHA256:
        raise ValueError("V2.6.2 parent ROM SHA-256 mismatch")
    if len(parent) != MENU_EXPANDED_SIZE or not verify_rom(parent).passed:
        raise ValueError("V2.6.2 parent ROM failed size or checksum verification")
    if parent[TEXT_START - 1:TEXT_START + 6] != b"\x7c" + ORIGINAL_TEXT + b"\x7f":
        raise ValueError("short dialogue does not match the V2.6.2 parent")
    for code, expected in ((0xC6, b"\x29\x2f"), (0xB6, b"\x1d\x0e\x27"), (0xCC, b"\x4b\x4a\x3c")):
        if _read_macro(parent, code) != expected:
            raise ValueError(f"native macro ${code:02X} has an unexpected expansion")

    assets = tuple(
        json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        for name in (
            "chinese_glyphs_oni5_bank04_prologue_v26.json",
            "chinese_glyphs_oni5_bank04_prologue_v261.json",
            "chinese_glyphs_oni5_v261_remaining_dialogues.json",
            "chinese_glyphs_oni5_bank04_01342e.json",
            "chinese_glyphs_oni5_bank04_01330d.json",
            "chinese_glyphs_oni5_bank04_01346f.json",
        )
    )
    patterns = load_glyph_patterns(assets, [character for character, _ in GLYPH_TILES])
    glyphs = tuple(CachedGlyph(character, tile, patterns[character]) for character, tile in GLYPH_TILES)
    source = SOURCE_ROM.read_bytes()
    if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("original ROM SHA-256 mismatch")
    font = decode_resource(source, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    originals = tuple(font[(glyph.tile - 0x80) * 16:(glyph.tile - 0x7F) * 16] for glyph in glyphs)
    if any(len(pattern) != 16 for pattern in originals):
        raise ValueError("original font does not cover all short-dialogue tiles")
    context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x34,
        first_cursor=0x11,
        restore_cursor=RESTORE_CURSOR,
        source_offset=TEXT_START,
        payload=TRANSLATED_TEXT,
        glyphs=glyphs,
        marker=MARKER,
        restore_from_rom=True,
        original_patterns=originals,
        return_code=glyphs[0].tile,
    )

    router = parent[RESTORE_WRAPPER_OFFSET:RESTORE_WRAPPER_OFFSET + 8]
    if router[:2] != bytes.fromhex("F5 CD") or router[4:] != bytes.fromhex("F1 C3 80 70"):
        raise ValueError("V2.6.2 restore router has an unexpected layout")
    old_dispatcher = int.from_bytes(router[2:4], "little")
    dispatcher_offset = SOURCE_SIZE + old_dispatcher - 0x4000
    if parent[dispatcher_offset:dispatcher_offset + 17] != bytes.fromhex(
        "FA F2 C4 FE 85 20 0A FA AD FF FE 08 20 03 CA C0 75"
    ):
        raise ValueError("V2.6.2 previous-dialogue restore dispatch has an unexpected layout")
    old_restore = 0x75C0
    old_restore_offset = SOURCE_SIZE + old_restore - 0x4000
    if parent[old_restore_offset:old_restore_offset + 19] != bytes.fromhex(
        "C5 D5 F5 FA F2 C4 FE 85 C2 A3 76 FA AD FF FE 08 C2 A3 76"
    ):
        raise ValueError("V2.6.2 previous-dialogue restore helper has an unexpected layout")

    loader_offset = HELPER_START
    pattern_offset = align_up(loader_offset + len(build_loader_helper(context, 0x4100)), 16)
    pattern_data = b"".join(glyph.pattern for glyph in glyphs)
    original_offset = align_up(pattern_offset + len(pattern_data), 16)
    original_data = b"".join(originals)
    restore_offset = align_up(original_offset + len(original_data), 16)
    loader = build_loader_helper(context, bank_cpu_address(pattern_offset))
    restore = build_restore_helper(context, bank_cpu_address(restore_offset), bank_cpu_address(original_offset))
    wrapper_offset = restore_offset + len(restore)
    wrapper = _build_preload_wrapper(
        bank_cpu_address(wrapper_offset), old_restore + 19, bank_cpu_address(loader_offset)
    )
    new_dispatcher_offset = wrapper_offset + len(wrapper)
    dispatcher = _build_restore_dispatcher(
        old_dispatcher, bank_cpu_address(wrapper_offset), bank_cpu_address(restore_offset)
    )
    helper_end = new_dispatcher_offset + len(dispatcher)
    if helper_end > HELPER_END or parent[HELPER_START:helper_end] != b"\xff" * (helper_end - HELPER_START):
        raise ValueError("short-dialogue helpers overlap occupied bank-10 bytes")

    target = bytearray(parent)
    target[TEXT_START:TEXT_START + len(TRANSLATED_TEXT)] = TRANSLATED_TEXT
    target[MBC1_MIRROR_OFFSET + TEXT_START:MBC1_MIRROR_OFFSET + TEXT_START + len(TRANSLATED_TEXT)] = TRANSLATED_TEXT
    target[loader_offset:loader_offset + len(loader)] = loader
    target[pattern_offset:pattern_offset + len(pattern_data)] = pattern_data
    target[original_offset:original_offset + len(original_data)] = original_data
    target[restore_offset:restore_offset + len(restore)] = restore
    target[wrapper_offset:wrapper_offset + len(wrapper)] = wrapper
    target[new_dispatcher_offset:helper_end] = dispatcher
    target[RESTORE_WRAPPER_OFFSET + 2:RESTORE_WRAPPER_OFFSET + 4] = bank_cpu_address(new_dispatcher_offset).to_bytes(2, "little")
    target[MBC1_MIRROR_OFFSET + SOURCE_SIZE:MBC1_MIRROR_OFFSET + SOURCE_SIZE + 0x4000] = target[
        SOURCE_SIZE:SOURCE_SIZE + 0x4000
    ]
    target = update_checksums(target)
    if not verify_rom(target).passed:
        raise ValueError("V2.6.3 ROM failed checksum verification")
    patch = create_bps_patch(parent, target)
    if apply_bps_patch(parent, patch) != target:
        raise ValueError("V2.6.2-to-V2.6.3 BPS round-trip failed")
    version = {
        "schema_version": 1,
        "version_id": "V2.6.3-opening-dialogue",
        "parent_version": {"version_id": "V2.6.2-opening-dialogue", "sha256": EXPECTED_V2_6_2_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(target).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {
            "status": "sameboy-confirmed-by-user",
            "tested_rom_sha256": None,
            "confirmation": "User reported that V2.6.3 passed acceptance and selected it as the new baseline; the tested ROM hash was not independently confirmed.",
            "required_sameboy_checks": [
                "Check the preceding Chinese dialogue and the transition to 静那「常叶丸！？」.",
                "Check that the background and portrait remain correct while the two dialogues change.",
                "Continue through the following V2.6.2 dialogues and check that original glyphs return.",
            ],
        },
        "implementation": {
            "text_start": f"0x{TEXT_START:06X}",
            "glyph_tiles": {glyph.character: f"0x{glyph.tile:02X}" for glyph in glyphs},
            "loader_offset": f"0x{loader_offset:06X}",
            "pattern_offset": f"0x{pattern_offset:06X}",
            "original_pattern_offset": f"0x{original_offset:06X}",
            "restore_offset": f"0x{restore_offset:06X}",
            "wrapper_offset": f"0x{wrapper_offset:06X}",
            "dispatcher_offset": f"0x{new_dispatcher_offset:06X}",
            "helper_end": f"0x{helper_end:06X}",
        },
    }
    return target, patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace existing V2.6.3 outputs")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("V2.6.3 output already exists; pass --overwrite to replace it")
        OUTPUT_ROM.write_bytes(target)
        OUTPUT_PATCH.write_bytes(patch)
        OUTPUT_VERSION.write_text(json.dumps(version, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"ROM: {OUTPUT_ROM}")
    print(f"ROM SHA-256: {hashlib.sha256(target).hexdigest()}")
    print(f"BPS: {OUTPUT_PATCH}")
    print(f"BPS SHA-256: {hashlib.sha256(patch).hexdigest()}")
    print(f"Version manifest: {OUTPUT_VERSION}")


if __name__ == "__main__":
    main()
