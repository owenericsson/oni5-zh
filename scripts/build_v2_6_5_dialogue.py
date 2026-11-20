"""Build the confirmed dialogues on the accepted V2.6.4 ROM."""
import argparse
import hashlib
import json

from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_opening_text_preview_patch import (
    FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH, load_glyph_patterns, required_custom_characters,
)
from scripts.build_noticeboard_glyph_probe import build_copy_code, tile_vram_address
from scripts.build_text_comparison_pilot import bank_cpu_address
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM, SOURCE_SIZE
from scripts import build_v2_6_4_dialogue as previous
from scripts.build_v2_6_4_dialogue import CURRENT_NAME_TILES, ROOT, encode_compact_glyph_table
from scripts.build_v2_6_3_dialogue import _read_macro
from scripts.build_v2_6_prologue_patch import (
    EXPECTED_SOURCE_SHA256,
    NATIVE_QUOTE_TILES,
    RESERVED_TILE_IDS,
    encode_translation_span,
)
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import update_checksums, verify_rom

PAGES = (
    (0x135D8, 0x135E7, "伽罗\n「你来晚了嘛，{主角}。」"),
    (0x135EC, 0x135F4, "{主角}\n「{原来是}{伽罗}啊。」"),
    (0x135F6, 0x13625, "伽罗\n「明天是你{16}岁生日吧？\n阿姨正在做好吃的呢。」"),
    (0x1362A, 0x1363C, "{主角}\n「好吃的！？\n有红豆汤吗？」"),
    (0x13672, 0x13696, "弥生\n「欢迎回来。\n我做了你最喜欢的红豆汤哦。」"),
    (0x1369B, 0x136B7, "{主角}\n「太好了！谢谢妈妈！\n我可以先尝一口吗？」"),
    (0x136BC, 0x136CF, "伽罗\n「不行哦，这是明天的美食嘛。」"),
    (0x136D1, 0x136EA, "{主角}\n「切，要是明天快点到就好了。」"),
    (0x136F1, 0x136FF, "女人\n「啊啊啊{破折}{破折}{结尾}"),
)
MACROS = {
    "{主角}": (0x80, 5), "{16}": (0x41, 2), "{原来是}": (0xB0, 3),
    "{伽罗}": (0xC6, 2), "{破折}": (0xD4, 2), "{结尾}": (0xD0, 3),
}
SPECIAL_TEXT = bytes.fromhex("7C B9 21 C0 7D 3B 0F 05 09 09 09 D4 D4 08 D0 7F")
LATER_MARKER = 0x8E
EARLIER_MARKER = 0x8D
EXPECTED_PARENT_SHA256 = "027cc41c7ee9c672014e64840c68d1ae7094d36a9b8aeb120b169b421314c793"
OUTPUT_ROM = ROOT / "roms" / "oni5_v2_6_5_opening_dialogue.gb"
OUTPUT_PATCH = ROOT / "roms" / "oni5_v2_6_5_opening_dialogue.bps"
OUTPUT_VERSION = ROOT / "versions" / "V2.6.5-opening-dialogue.json"
FREE_RANGES = (
    (0x4204F, 0x42100), (0x40F70, 0x41000), (0x43090, 0x43100),
    (0x43DC7, 0x43E28), (0x400AC, 0x40100), (0x405B0, 0x40600),
    (0x413B0, 0x41400), (0x40AB6, 0x40B00), (0x423B6, 0x42400),
    (0x416B9, 0x41700), (0x42AB7, 0x42B00), (0x42DB8, 0x42E00),
    (0x424BD, 0x42500), (0x401BF, 0x40200), (0x40EC0, 0x40F00),
    (0x428C3, 0x42900), (0x43048, 0x43080), (0x411CD, 0x41200),
)


def build_special_dash_restore(original_pattern_address: int) -> bytes:
    """Restore the shared dash tile just before the translated special sentence."""
    if not 0x4000 <= original_pattern_address <= 0x7FF0:
        raise ValueError("dash pattern must be wholly within the active bank")
    code = bytearray()
    for address, expected in ((0xFFAA, 4), (0xFFAE, 0x36), (0xFFAD, 0xF2), (0xC4F2, LATER_MARKER)):
        code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0xC0)))
    code.extend(bytes.fromhex("C5 D5 E5 F5"))
    code.extend(build_copy_code(original_pattern_address, tile_vram_address(0xB7)))
    code.extend(bytes.fromhex("F1 E1 D1 C1 C9"))
    return bytes(code)


def automatic_scene_tiles(rom: bytes) -> set[int]:
    """Return original glyph tiles referenced by the following automatic dialogue."""
    if rom[0x136F0:0x13700] != SPECIAL_TEXT:
        raise ValueError("the following automatic dialogue differs from the accepted baseline")
    tokens = []
    for code in SPECIAL_TEXT:
        if 0x80 <= code <= 0xD5:
            tokens.extend(_read_macro(rom, code))
        elif code < 0x7B:
            tokens.append(code)
    if any(code >= 0x60 for code in tokens):
        raise ValueError("automatic dialogue has an unhandled non-direct glyph code")
    return {code + 0x80 for code in tokens if code < 0x40}


def prepare_pages() -> tuple[list[dict[str, int]], dict[int, bytes]]:
    """Encode the pages without installing or claiming runtime safety."""
    assets = tuple(
        json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        for name in ("chinese_glyphs_oni5_v265_dialogues.json", "chinese_glyphs_oni5_v264_dialogues.json")
    )
    excluded = RESERVED_TILE_IDS | NATIVE_QUOTE_TILES | CURRENT_NAME_TILES | {0xBE}
    tiles = [tile for tile in range(0x80, 0xC0) if tile not in excluded]
    mappings = []
    pages = {}
    for group in (PAGES[:4], PAGES[4:]):
        text = "".join(page[2] for page in group)
        for token in MACROS:
            text = text.replace(token, "")
        if group == PAGES[:4]:
            text += "原来是"
        characters = [c for c in required_custom_characters(text) if c not in "。！？"]
        if len(characters) > len(tiles):
            raise ValueError("not enough glyph tiles for dialogue group")
        load_glyph_patterns(assets, characters)
        fixed = ({"原": 0xB4, "来": 0x98, "是": 0x99, "伽": 0xA9, "罗": 0xAF}
                 if group == PAGES[:4] else {"妈": 0xB7})
        available = [tile for tile in tiles if tile not in fixed.values()]
        mapping = dict(fixed)
        mapping.update(zip((c for c in characters if c not in fixed), available))
        codes = {character: tile - 0x80 for character, tile in mapping.items()}
        for start, end, text in group:
            # The two original digit tiles are ordinary input codes, not a one-byte macro.
            encoded = encode_translation_span(text.replace("{16}", "{1}{6}"), codes, end - start, 0,
                                              {"{主角}": (0x80, 5), "{1}": (0x41, 1), "{6}": (0x46, 1),
                                               "{原来是}": (0xB0, 3), "{伽罗}": (0xC6, 2),
                                               "{破折}": (0xD4, 2), "{结尾}": (0xD0, 3)})
            pages[start] = encoded
        mappings.append(mapping)
    return mappings, pages


def build_load_dispatcher(first: int, later: int, restore: int, dash: int) -> bytes:
    """Load at the first direct glyph in each group and otherwise use the old gateway."""
    code = bytearray()
    for high, cursor, old_marker, marker, tile, loader in (
        (0x35, 0xD9, 0, EARLIER_MARKER, 0xA9, first),
        (0x36, 0x73, EARLIER_MARKER, LATER_MARKER, 0x81, later),
    ):
        branches = []
        for address, expected in ((0xFFAA, 4), (0xFFAE, high), (0xFFAD, cursor), (0xC4F2, old_marker)):
            code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
            branches.append(len(code) - 1)
        if marker == LATER_MARKER:
            code.extend(b"\xCD" + restore.to_bytes(2, "little"))
        code.extend(b"\xCD" + loader.to_bytes(2, "little"))
        code.extend(bytes((0x3E, marker)) + bytes.fromhex("EA F2 C4"))
        code.extend(bytes((0x3E, tile)) + bytes.fromhex("EA F0 C4 06 CD 3E 01 C9"))
        for branch in branches:
            code[branch] = len(code) - branch - 1
    code.extend(b"\xCD" + dash.to_bytes(2, "little"))
    code.extend(bytes.fromhex("C3 08 41"))
    return bytes(code)


def build_close_dispatcher(restore: int) -> bytes:
    """Extend the previous close dispatcher only at the observed automatic-scene close."""
    code = bytearray(bytes.fromhex("CD 90 42"))
    branches = []
    for address, expected in ((0xFFAA, 4), (0xFFAE, 0x37), (0xFFAD, 0), (0xC4F2, LATER_MARKER)):
        code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
        branches.append(len(code) - 1)
    code.extend(b"\xCD" + restore.to_bytes(2, "little"))
    code.extend(bytes.fromhex("AF EA F2 C4"))
    for branch in branches:
        code[branch] = len(code) - branch - 1
    code.append(0xC9)
    return bytes(code)


def install_components(target: bytearray, font: bytes, mappings: list[dict[str, int]]) -> dict[str, int]:
    """Install isolated helpers and tables into checked free ranges in bank $10."""
    for start, end in FREE_RANGES:
        if target[start:end] != bytes([0xFF]) * (end - start):
            raise ValueError(f"V2.6.5 allocation range ${start:06X} is not free")
    positions = [start for start, _ in FREE_RANGES]

    def allocate(data: bytes) -> int:
        for i, (_, end) in enumerate(FREE_RANGES):
            start = positions[i]
            if start + len(data) <= end:
                target[start:start + len(data)] = data
                positions[i] += len(data)
                return start
        raise ValueError(f"no space for {len(data)}-byte component")

    load_offset = allocate(bytes([0xFF]) * 120)
    wrapper_offsets = [allocate(bytes([0xFF]) * 96) for _ in range(2)]
    close_offset = allocate(bytes([0xFF]) * 48)
    dash_offset = allocate(bytes([0xFF]) * len(build_special_dash_restore(0x4000)))
    dash_pattern_offset = allocate(font[0x370:0x380])
    assets = tuple(
        json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        for name in ("chinese_glyphs_oni5_v265_dialogues.json", "chinese_glyphs_oni5_v264_dialogues.json")
    )
    patterns = load_glyph_patterns(assets, list(dict.fromkeys(c for group in mappings for c in group)))
    copy_address = bank_cpu_address(0x43D3E)
    restore_address = bank_cpu_address(0x43D9A)
    if target[0x43D3E:0x43D42] != bytes.fromhex("C5 D5 E5 F5"):
        raise ValueError("unexpected V2.6.4 compact glyph helper")
    if target[0x43D9A:0x43D9E] != bytes.fromhex("C5 D5 E5 F5"):
        raise ValueError("unexpected V2.6.4 glyph restore helper")
    original_first, _ = previous.prepare_first_pages()
    original_later, _ = previous.prepare_later_pages()
    original_tiles = set(original_first.values()) | set(original_later.values())
    if any(set(group.values()) - original_tiles for group in mappings):
        raise ValueError("V2.6.4 restore helper does not cover all new glyph tiles")

    for mapping, wrapper_offset in zip(mappings, wrapper_offsets):
        raw = encode_compact_glyph_table({tile: patterns[character] for character, tile in mapping.items()})
        cursor = 0
        chunks = []
        for i, (_, end) in enumerate(FREE_RANGES):
            count = min((end - positions[i]) // 10, (len(raw) - cursor) // 10)
            if count:
                start = positions[i]
                size = count * 10
                target[start:start + size] = raw[cursor:cursor + size]
                positions[i] += size
                cursor += size
                chunks.append((start, count))
        if cursor != len(raw):
            raise ValueError("not enough space for V2.6.5 compact glyph tables")
        wrapper = bytearray.fromhex("C5 D5 E5 F5")
        for offset, count in chunks:
            wrapper.extend(b"\x21" + bank_cpu_address(offset).to_bytes(2, "little"))
            wrapper.extend(bytes((0x06, count, 0xCD)) + copy_address.to_bytes(2, "little"))
        wrapper.extend(bytes.fromhex("F1 E1 D1 C1 C9"))
        if len(wrapper) > 96:
            raise ValueError("V2.6.5 glyph wrapper exceeds its reservation")
        target[wrapper_offset:wrapper_offset + len(wrapper)] = wrapper

    load = build_load_dispatcher(*(bank_cpu_address(x) for x in wrapper_offsets),
                                 restore_address, bank_cpu_address(dash_offset))
    close = build_close_dispatcher(restore_address)
    dash = build_special_dash_restore(bank_cpu_address(dash_pattern_offset))
    if len(load) > 120 or len(close) > 48:
        raise ValueError("V2.6.5 dispatchers exceed their reservations")
    target[load_offset:load_offset + len(load)] = load
    target[close_offset:close_offset + len(close)] = close
    target[dash_offset:dash_offset + len(dash)] = dash
    if target[0x40100:0x40108] != bytes.fromhex("CD 08 41 B7 C0 C3 30 40"):
        raise ValueError("unexpected V2.6.4 glyph load gate")
    if target[0x43040:0x43048] != bytes.fromhex("F5 CD 90 42 F1 C3 80 70"):
        raise ValueError("unexpected V2.6.4 close gate")
    target[0x40101:0x40103] = bank_cpu_address(load_offset).to_bytes(2, "little")
    target[0x43042:0x43044] = bank_cpu_address(close_offset).to_bytes(2, "little")
    return {
        "load_dispatcher": load_offset, "first_loader": wrapper_offsets[0],
        "later_loader": wrapper_offsets[1], "close_dispatcher": close_offset,
        "dash_restore": dash_offset, "dash_pattern": dash_pattern_offset,
    }


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != EXPECTED_PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.4 parent ROM failed SHA-256 or checksum verification")
    source = SOURCE_ROM.read_bytes()
    if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("original ROM SHA-256 mismatch")
    font = decode_resource(source, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    mappings, pages = prepare_pages()
    automatic_scene_tiles(parent)
    if pages[0x135D8][0] != 0x29 or pages[0x13672][0] != 1 or pages[0x136F1][0] >= 0x40:
        raise ValueError("load trigger no longer matches the direct first glyph")
    target = bytearray(parent)
    for index, (start, end, _) in enumerate(PAGES):
        before = 0x57 if index in (0, 4) else 0x7C
        terminator = 0x7E if index in (1, 6) else 0x7F
        if parent[start - 1] != before or parent[end] != terminator:
            raise ValueError(f"unexpected control bytes around page ${start:06X}")
        if parent[MBC1_MIRROR_OFFSET + start - 1:MBC1_MIRROR_OFFSET + end + 1] != parent[start - 1:end + 1]:
            raise ValueError(f"parent ROM mirror differs around page ${start:06X}")
        target[start:end] = pages[start]
        target[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end] = pages[start]
    components = install_components(target, font, mappings)
    target[MBC1_MIRROR_OFFSET + SOURCE_SIZE:MBC1_MIRROR_OFFSET + SOURCE_SIZE + 0x4000] = target[
        SOURCE_SIZE:SOURCE_SIZE + 0x4000
    ]
    target = update_checksums(target)
    if len(target) != len(parent) or not verify_rom(target).passed:
        raise ValueError("V2.6.5 ROM failed size or checksum verification")
    patch = create_bps_patch(parent, target)
    if apply_bps_patch(parent, patch) != target:
        raise ValueError("V2.6.4-to-V2.6.5 BPS round-trip failed")
    version: dict[str, object] = {
        "schema_version": 1,
        "version_id": "V2.6.5-opening-dialogue",
        "parent_version": {"version_id": "V2.6.4-opening-dialogue", "sha256": EXPECTED_PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(target).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {
            "status": "pending-sameboy",
            "limitations": [
                "Only the observed protagonist name tiles and voiced mark are protected.",
                "Glyph loading, group transition, dash restoration and automatic scene require SameBoy verification.",
            ],
        },
        "implementation": {"glyph_components": {k: f"0x{v:06X}" for k, v in components.items()}},
    }
    return bytes(target), patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace existing V2.6.5 outputs")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("V2.6.5 output already exists; pass --overwrite to replace it")
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
