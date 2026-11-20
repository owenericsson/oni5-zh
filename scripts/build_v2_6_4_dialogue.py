"""Components for the V2.6.4 dialogue build."""
import json
import hashlib
import argparse
from pathlib import Path

from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_noticeboard_glyph_probe import build_copy_code, tile_vram_address
from scripts.build_opening_text_preview_patch import FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH, load_glyph_patterns, required_custom_characters
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM, SOURCE_SIZE
from scripts.build_v2_6_3_dialogue import OUTPUT_ROM as PARENT_ROM
from scripts.build_text_comparison_pilot import bank_cpu_address
from scripts.build_v2_6_prologue_patch import (
    EXPECTED_SOURCE_SHA256,
    NATIVE_QUOTE_TILES,
    RESERVED_TILE_IDS,
    encode_translation_span,
)
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import update_checksums, verify_rom


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PARENT_SHA256 = "1cb47f5e8ca4b62a03d4df9e2e22d6eb0625b813caeec826da33e37577663457"
OUTPUT_ROM = ROOT / "roms" / "oni5_v2_6_4_opening_dialogue.gb"
OUTPUT_PATCH = ROOT / "roms" / "oni5_v2_6_4_opening_dialogue.bps"
OUTPUT_VERSION = ROOT / "versions" / "V2.6.4-opening-dialogue.json"
REPLY_TO_TOKIWA_CALL_OFFSET = SOURCE_SIZE + 0x0284
TRANSITION_HELPER_OFFSET = SOURCE_SIZE + 0x0AA0
REPLY_RESTORE_BODY = 0x79F3
TOKIWA_LOADER = 0x6580
CURRENT_NAME_TILES = frozenset({0x92, 0x8E, 0xA0, 0xA7, 0xB1, 0xB8})
FIRST_PAGES = (
    ("oni5-bank04-inline-01348f-v264", 0x1348D, 0x134AA, "静那"),
    ("oni5-bank04-inline-0134ab", 0x134AC, 0x134CD, "{主角}"),
    ("oni5-bank04-inline-0134ce", 0x134CF, 0x134FA, "静那"),
    ("oni5-bank04-inline-0134fb", 0x134FC, 0x13516, "{主角}"),
)
LATER_PAGES = (
    ("oni5-bank24-01353f", 0x13545, 0x13552, "常叶丸"),
    ("oni5-bank04-inline-013557", 0x13558, 0x13577, "{主角}"),
    ("oni5-bank04-inline-01358a", 0x1358B, 0x135AB, "常叶丸"),
)
COMPONENT_RANGES = (
    (SOURCE_SIZE + 0x3D3E, SOURCE_SIZE + 0x4000),
    (SOURCE_SIZE + 0x0D12, SOURCE_SIZE + 0x0E00),
    (SOURCE_SIZE + 0x1A40, SOURCE_SIZE + 0x1B2E),
    (SOURCE_SIZE + 0x1840, SOURCE_SIZE + 0x1900),
    (SOURCE_SIZE + 0x2D30, SOURCE_SIZE + 0x2E00),
    (SOURCE_SIZE + 0x204F, SOURCE_SIZE + 0x2100),
    (SOURCE_SIZE + 0x0F70, SOURCE_SIZE + 0x1000),
)
LOAD_GATE_OFFSET = SOURCE_SIZE + 0x0100
NEW_LOAD_DISPATCH_OFFSET = SOURCE_SIZE + 0x0108
NEW_RESTORE_DISPATCH_OFFSET = SOURCE_SIZE + 0x0290
RESTORE_WRAPPER_OFFSET = SOURCE_SIZE + 0x3040


def prepare_first_pages() -> tuple[dict[str, int], dict[int, bytes]]:
    """Prepare fixed-width text and shared glyph assignments, without patching ROM."""
    manifest = json.loads((ROOT / "data" / "text_manifest.json").read_text(encoding="utf-8"))
    records = {record["id"]: record for record in manifest["records"]}
    texts = []
    for record_id, _, _, speaker in FIRST_PAGES:
        translation = records[record_id]["translation"]
        if translation["status"] != "confirmed" or len(translation["segments"]) != 1:
            raise ValueError(f"{record_id} is not a single confirmed translation")
        body = translation["segments"][0]["text"]
        if record_id == "oni5-bank04-inline-0134ab":
            before, separator, after = body.partition("结束修炼")
            if not separator:
                raise ValueError("second page no longer matches its verified line break")
            body = before + "结束\n修炼" + after
        texts.append(speaker + "\n" + body)
    all_text = "".join(texts).replace("{主角}", "")
    characters = [c for c in required_custom_characters(all_text) if c not in "。！？"]
    excluded = RESERVED_TILE_IDS | NATIVE_QUOTE_TILES | CURRENT_NAME_TILES | {0xBE}
    tiles = [tile for tile in range(0x80, 0xC0) if tile not in excluded]
    if len(characters) > len(tiles):
        raise ValueError("not enough glyph tiles for the four consecutive pages")
    asset = json.loads((ROOT / "data" / "chinese_glyphs_oni5_v264_dialogues.json").read_text(encoding="utf-8"))
    load_glyph_patterns((asset,), characters)
    tile_by_character = dict(zip(characters, tiles))
    codes = {character: tile - 0x80 for character, tile in tile_by_character.items()}
    pages = {
        start: encode_translation_span(text, codes, end - start, 0, {"{主角}": (0x80, 5)})
        for (_, start, end, _), text in zip(FIRST_PAGES, texts)
    }
    return tile_by_character, pages


def prepare_later_pages() -> tuple[dict[str, int], dict[int, bytes]]:
    """Prepare the three later pages with the dynamic name and native punctuation."""
    manifest = json.loads((ROOT / "data" / "text_manifest.json").read_text(encoding="utf-8"))
    records = {record["id"]: record for record in manifest["records"]}
    texts = []
    for record_id, _, _, speaker in LATER_PAGES:
        translation = records[record_id]["translation"]
        if translation["status"] != "confirmed" or len(translation["segments"]) != 1:
            raise ValueError(f"{record_id} is not a single confirmed translation")
        body = translation["segments"][0]["text"]
        if record_id == "oni5-bank24-01353f":
            prefix = speaker + "\n"
            if not body.startswith(prefix):
                raise ValueError("fifth page no longer has the confirmed speaker")
            body = body[len(prefix):]
        elif record_id == "oni5-bank04-inline-013557":
            before, separator, after = body.partition("……")
            if not separator:
                raise ValueError("sixth page no longer matches its verified line break")
            body = before + separator + "\n" + after
        elif record_id == "oni5-bank04-inline-01358a":
            before, separator, after = body.partition("…………")
            if not separator:
                raise ValueError("seventh page no longer matches its verified line break")
            body = before + separator + "\n" + after
        body = body.replace("…………", "{省略}{省略}").replace("……", "{省略}")
        texts.append(speaker + "\n" + body)
    macros = {"{主角}": (0x80, 5), "{省略}": (0xD5, 2), "！？」": (0xCC, 3)}
    all_text = "".join(texts)
    for token in macros:
        all_text = all_text.replace(token, "")
    characters = [c for c in required_custom_characters(all_text) if c not in "。！？"]
    excluded = RESERVED_TILE_IDS | NATIVE_QUOTE_TILES | CURRENT_NAME_TILES | {0xBE}
    tiles = [tile for tile in range(0x80, 0xC0) if tile not in excluded]
    if len(characters) > len(tiles):
        raise ValueError("not enough glyph tiles for the later pages")
    asset = json.loads((ROOT / "data" / "chinese_glyphs_oni5_v264_dialogues.json").read_text(encoding="utf-8"))
    load_glyph_patterns((asset,), characters)
    tile_by_character = dict(zip(characters, tiles))
    codes = {character: tile - 0x80 for character, tile in tile_by_character.items()}
    pages = {
        start: encode_translation_span(text, codes, end - start, 0, macros)
        for (_, start, end, _), text in zip(LATER_PAGES, texts)
    }
    return tile_by_character, pages


def install_translations(target: bytearray) -> None:
    """Write all seven fixed-length pages into an untouched V2.6.3 parent."""
    if hashlib.sha256(target).hexdigest() != EXPECTED_PARENT_SHA256:
        raise ValueError("V2.6.3 parent ROM SHA-256 mismatch")
    _, first = prepare_first_pages()
    _, later = prepare_later_pages()
    for index, (_, start, end, _) in enumerate((*FIRST_PAGES, *LATER_PAGES)):
        expected_end = 0x7E if index < 3 else 0x7F
        if target[start - 1] != 0x7C or target[end] != expected_end:
            raise ValueError(f"unexpected control bytes around page ${start:06X}")
        if target[MBC1_MIRROR_OFFSET + start - 1:MBC1_MIRROR_OFFSET + end + 1] != target[start - 1:end + 1]:
            raise ValueError(f"parent ROM mirror differs around page ${start:06X}")
    for start, page in (first | later).items():
        target[start:start + len(page)] = page
        mirror = MBC1_MIRROR_OFFSET + start
        target[mirror:mirror + len(page)] = page


def encode_compact_glyph_table(patterns: dict[int, bytes]) -> bytes:
    """Encode equal-plane patterns as destination address followed by eight rows."""
    data = bytearray()
    for tile, pattern in patterns.items():
        if not 0x80 <= tile <= 0xBF or len(pattern) != 16:
            raise ValueError(f"invalid pattern or text tile ${tile:02X}")
        if any(pattern[i] != pattern[i + 1] for i in range(0, 16, 2)):
            raise ValueError(f"tile ${tile:02X} cannot be stored as equal bitplanes")
        destination = 0x8800 + (tile - 0x80) * 16
        data.extend(destination.to_bytes(2, "little"))
        data.extend(pattern[::2])
    return bytes(data)


def split_original_patterns(tiles: set[int], font: bytes) -> tuple[dict[int, bytes], dict[int, bytes]]:
    """Separate equal-plane font patterns from patterns requiring full 2bpp copies."""
    compact: dict[int, bytes] = {}
    full: dict[int, bytes] = {}
    for tile in sorted(tiles):
        if not 0x80 <= tile <= 0xBF:
            raise ValueError(f"invalid text tile ${tile:02X}")
        offset = (tile - 0x80) * 16
        pattern = font[offset:offset + 16]
        if len(pattern) != 16:
            raise ValueError(f"original font does not cover tile ${tile:02X}")
        target = compact if all(pattern[i] == pattern[i + 1] for i in range(0, 16, 2)) else full
        target[tile] = pattern
    return compact, full


def build_compact_copy_helper() -> bytes:
    """Copy 1–255 compact records from HL to VRAM, retaining registers and flags."""
    code = bytearray.fromhex("C5 D5 E5 F5")
    tile_start = len(code)
    code.extend(bytes.fromhex("2A 5F 2A 57 0E 08"))
    row_start = len(code)
    code.extend(bytes.fromhex("2A F5 F0 41 E6 02 20 FA F1 12 13"))
    code.extend(bytes.fromhex("F5 F0 41 E6 02 20 FA F1 12 13 0D 20 00"))
    code[-1] = (row_start - len(code)) & 0xFF
    code.extend(bytes.fromhex("05 20 00"))
    code[-1] = (tile_start - len(code)) & 0xFF
    code.extend(bytes.fromhex("F1 E1 D1 C1 C9"))
    return bytes(code)


def install_glyph_components(target: bytearray, font: bytes) -> dict[str, int]:
    """Install isolated copy routines and tables; do not alter any game hooks."""
    for start, end in COMPONENT_RANGES:
        if target[start:end] != bytes([0xFF]) * (end - start):
            raise ValueError(f"component allocation range ${start:06X} is not free")
    positions = [start for start, _ in COMPONENT_RANGES]

    def allocate(data: bytes) -> int:
        for i, (_, end) in enumerate(COMPONENT_RANGES):
            start = positions[i]
            if start + len(data) <= end:
                target[start:start + len(data)] = data
                positions[i] += len(data)
                return start
        raise ValueError(f"no space for {len(data)}-byte glyph component")

    def allocate_table(patterns: dict[int, bytes]) -> list[tuple[int, int]]:
        raw = encode_compact_glyph_table(patterns)
        chunks = []
        cursor = 0
        for i, (_, end) in enumerate(COMPONENT_RANGES):
            count = min((end - positions[i]) // 10, (len(raw) - cursor) // 10, 255)
            if count:
                start = positions[i]
                size = count * 10
                target[start:start + size] = raw[cursor:cursor + size]
                positions[i] += size
                cursor += size
                chunks.append((start, count))
        if cursor != len(raw):
            raise ValueError("not enough space for compact glyph table")
        return chunks

    asset = json.loads((ROOT / "data" / "chinese_glyphs_oni5_v264_dialogues.json").read_text(encoding="utf-8"))
    first, _ = prepare_first_pages()
    later, _ = prepare_later_pages()
    patterns = load_glyph_patterns((asset,), list(dict.fromkeys((*first, *later))))
    first_patterns = {tile: patterns[character] for character, tile in first.items()}
    later_patterns = {tile: patterns[character] for character, tile in later.items()}
    original_compact, original_full = split_original_patterns(set(first.values()) | set(later.values()), font)

    copy_offset = allocate(build_compact_copy_helper())
    # Reserve room for the three wrappers before allocating tables into fragmented space.
    wrappers_offset = allocate(bytes([0xFF]) * 192)
    tables = [allocate_table(group) for group in (first_patterns, later_patterns, original_compact)]
    full_offsets = {tile: allocate(pattern) for tile, pattern in original_full.items()}
    copy_address = bank_cpu_address(copy_offset)
    wrappers = bytearray()
    result = {"copy": copy_offset}
    for label, chunks in zip(("first", "later", "restore"), tables):
        result[label] = wrappers_offset + len(wrappers)
        wrappers.extend(bytes.fromhex("C5 D5 E5 F5"))
        for offset, count in chunks:
            wrappers.extend(b"\x21" + bank_cpu_address(offset).to_bytes(2, "little"))
            wrappers.extend(bytes((0x06, count, 0xCD)) + copy_address.to_bytes(2, "little"))
        if label == "restore":
            for tile, offset in full_offsets.items():
                wrappers.extend(build_copy_code(bank_cpu_address(offset), tile_vram_address(tile)))
        wrappers.extend(bytes.fromhex("F1 E1 D1 C1 C9"))
    if len(wrappers) > 192:
        raise ValueError("glyph wrappers exceed their reserved space")
    target[wrappers_offset:wrappers_offset + len(wrappers)] = wrappers
    result["wrapper_end"] = wrappers_offset + len(wrappers)
    return result


def build_initial_load_dispatcher(first_loader: int, later_loader: int) -> bytes:
    """Build an isolated exact-cursor loader; the caller must handle restoration."""
    for address in (first_loader, later_loader):
        if not 0x4000 <= address < 0x8000:
            raise ValueError("loader must be in the active bank window")
    code = bytearray()
    for high, cursor, marker, return_tile, loader in (
        (0x34, 0x8E, 0x8B, 0x81, first_loader),
        (0x35, 0x46, 0x8C, 0x81, later_loader),
        (0x35, 0x5B, 0x8C, 0xBB, later_loader),
        (0x35, 0x8C, 0x8C, 0x81, later_loader),
    ):
        branches = []
        for address, expected in ((0xFFAA, 0x04), (0xFFAE, high), (0xFFAD, cursor)):
            code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
            branches.append(len(code) - 1)
        code.extend(bytes.fromhex("FA F2 C4 B7 20 00"))
        branches.append(len(code) - 1)
        code.extend(b"\xCD" + loader.to_bytes(2, "little"))
        code.extend(bytes((0x3E, marker)) + bytes.fromhex("EA F2 C4"))
        code.extend(bytes((0x3E, return_tile)) + bytes.fromhex("EA F0 C4 06 CD 3E 01 C9"))
        for branch in branches:
            delta = len(code) - branch - 1
            if delta > 127:
                raise ValueError("loader dispatch branch out of range")
            code[branch] = delta
    code.extend(bytes.fromhex("AF C9"))
    return bytes(code)


def build_restore_dispatcher(previous: int, restore: int) -> bytes:
    """Run the previous dispatcher, then restore at observed close cursors."""
    for address in (previous, restore):
        if not 0x4000 <= address < 0x8000:
            raise ValueError("restore dispatcher target is outside the active bank")
    code = bytearray(b"\xCD" + previous.to_bytes(2, "little"))
    for cursor, marker in ((0x17, 0x8B), (0x78, 0x8C), (0xAC, 0x8C)):
        branches = []
        for address, expected in ((0xFFAA, 4), (0xFFAE, 0x35), (0xFFAD, cursor), (0xC4F2, marker)):
            code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
            branches.append(len(code) - 1)
        code.extend(b"\xCD" + restore.to_bytes(2, "little"))
        code.extend(bytes.fromhex("AF EA F2 C4 C9"))
        for branch in branches:
            code[branch] = len(code) - branch - 1
    code.append(0xC9)
    return bytes(code)


def install_dispatchers(target: bytearray, components: dict[str, int]) -> None:
    """Install guarded dispatchers in the accepted parent gateway."""
    if target[LOAD_GATE_OFFSET:LOAD_GATE_OFFSET + 8] != bytes.fromhex("CD 00 42 B7 C0 C3 30 40"):
        raise ValueError("unexpected V2.6.3 load gate")
    router = target[RESTORE_WRAPPER_OFFSET:RESTORE_WRAPPER_OFFSET + 8]
    if router != bytes.fromhex("F5 CD 5E 4A F1 C3 80 70"):
        raise ValueError("unexpected V2.6.3 restore wrapper")
    old_load = 0x4200
    old_restore = 0x4A5E
    load = build_initial_load_dispatcher(
        bank_cpu_address(components["first"]), bank_cpu_address(components["later"])
    )
    load = load[:-2] + b"\xC3" + old_load.to_bytes(2, "little")
    restore = build_restore_dispatcher(old_restore, bank_cpu_address(components["restore"]))
    for start, end, data in (
        (NEW_LOAD_DISPATCH_OFFSET, SOURCE_SIZE + 0x0200, load),
        (NEW_RESTORE_DISPATCH_OFFSET, SOURCE_SIZE + 0x0300, restore),
    ):
        if start + len(data) > end or target[start:start + len(data)] != b"\xFF" * len(data):
            raise ValueError(f"dispatcher overlaps occupied bytes at ${start:06X}")
        target[start:start + len(data)] = data
    target[LOAD_GATE_OFFSET + 1:LOAD_GATE_OFFSET + 3] = bank_cpu_address(NEW_LOAD_DISPATCH_OFFSET).to_bytes(2, "little")
    target[RESTORE_WRAPPER_OFFSET + 2:RESTORE_WRAPPER_OFFSET + 4] = bank_cpu_address(NEW_RESTORE_DISPATCH_OFFSET).to_bytes(2, "little")


def install_reply_transition_restore(target: bytearray) -> tuple[int, int]:
    """Restore the old reply glyphs before a new context overwrites its marker."""
    expected_call = bytes.fromhex("CD 80 65")
    expected_restore_prefix = bytes.fromhex(
        "C5 D5 F5 FA F2 C4 FE 88 C2 CF 7A FA AD FF FE 53 C2 CF 7A"
    )
    restore_offset = SOURCE_SIZE + 0x39E0
    if target[REPLY_TO_TOKIWA_CALL_OFFSET:REPLY_TO_TOKIWA_CALL_OFFSET + 3] != expected_call:
        raise ValueError("unexpected Tokiwa loader call in V2.6.3")
    if target[restore_offset:restore_offset + len(expected_restore_prefix)] != expected_restore_prefix:
        raise ValueError("unexpected reply restore helper in V2.6.3")
    helper_address = bank_cpu_address(TRANSITION_HELPER_OFFSET)
    trampoline_address = helper_address + 16
    helper = (
        bytes.fromhex("FA F2 C4 FE 88 20 05 E5 CD")
        + trampoline_address.to_bytes(2, "little")
        + bytes.fromhex("E1 CD")
        + TOKIWA_LOADER.to_bytes(2, "little")
        + bytes.fromhex("C9 C5 D5 F5 C3")
        + REPLY_RESTORE_BODY.to_bytes(2, "little")
    )
    end = TRANSITION_HELPER_OFFSET + len(helper)
    if target[TRANSITION_HELPER_OFFSET:end] != bytes([0xFF]) * len(helper):
        raise ValueError("reply transition helper overlaps occupied bytes")
    target[TRANSITION_HELPER_OFFSET:end] = helper
    target[REPLY_TO_TOKIWA_CALL_OFFSET + 1:REPLY_TO_TOKIWA_CALL_OFFSET + 3] = helper_address.to_bytes(2, "little")
    return TRANSITION_HELPER_OFFSET, end


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = PARENT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != EXPECTED_PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.3 parent ROM failed SHA-256 or checksum verification")
    source = SOURCE_ROM.read_bytes()
    if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("original ROM SHA-256 mismatch")
    font = decode_resource(source, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    target = bytearray(parent)
    install_translations(target)
    components = install_glyph_components(target, font)
    install_reply_transition_restore(target)
    install_dispatchers(target, components)
    target[MBC1_MIRROR_OFFSET + SOURCE_SIZE:MBC1_MIRROR_OFFSET + SOURCE_SIZE + 0x4000] = target[
        SOURCE_SIZE:SOURCE_SIZE + 0x4000
    ]
    target = update_checksums(target)
    if len(target) != len(parent) or not verify_rom(target).passed:
        raise ValueError("V2.6.4 ROM failed size or checksum verification")
    patch = create_bps_patch(parent, target)
    if apply_bps_patch(parent, patch) != target:
        raise ValueError("V2.6.3-to-V2.6.4 BPS round-trip failed")
    version: dict[str, object] = {
        "schema_version": 1,
        "version_id": "V2.6.4-opening-dialogue",
        "parent_version": {"version_id": "V2.6.3-opening-dialogue", "sha256": EXPECTED_PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(target).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {
            "status": "pending-sameboy",
            "limitations": [
                "Only the observed protagonist name tiles and voiced mark are protected.",
                "Loading, page transitions and glyph restoration require SameBoy verification.",
            ],
        },
        "implementation": {"glyph_components": {k: f"0x{v:06X}" for k, v in components.items()}},
    }
    return bytes(target), patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace existing V2.6.4 outputs")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("V2.6.4 output already exists; pass --overwrite to replace it")
        OUTPUT_ROM.write_bytes(target)
        OUTPUT_PATCH.write_bytes(patch)
        OUTPUT_VERSION.write_text(json.dumps(version, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"ROM: {OUTPUT_ROM}")
    print(f"SHA-256: {hashlib.sha256(target).hexdigest()}")
    print(f"BPS: {OUTPUT_PATCH}")
    print(f"Manifest: {OUTPUT_VERSION}")


if __name__ == "__main__":
    main()
