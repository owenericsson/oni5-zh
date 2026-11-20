"""Build the confirmed pre-battle dialogue on the V2.6.5 baseline."""
import argparse
import hashlib
import json

from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_opening_text_preview_patch import load_glyph_patterns, required_custom_characters
from scripts.build_text_comparison_pilot import bank_cpu_address
from scripts import build_v2_6_5_dialogue as previous
from scripts.build_v2_6_1_single_dialogue import SOURCE_SIZE
from scripts.build_v2_6_4_dialogue import (
    CURRENT_NAME_TILES, ROOT, build_compact_copy_helper, encode_compact_glyph_table,
    prepare_first_pages, prepare_later_pages,
)
from scripts.build_v2_6_3_dialogue import _read_macro
from scripts.build_v2_6_prologue_patch import (
    NATIVE_QUOTE_TILES, RESERVED_TILE_IDS, encode_translation_span,
)
from scripts.rom_checksums import update_checksums, verify_rom

PAGES = (
    (0x13738, 0x13741, "{主角}\n「{是从外}面传来的{感叹结尾}"),
    (0x13774, 0x13782, "{主角}\n「啊，在干什么{惊问结尾}"),
    (0x1378B, 0x137A3, "妖怪\n「啧，糟了！\n事到如今，你也去死吧{双感叹结尾}"),
)
MACROS = {
    "{主角}": (0x80, 5),
    "{是从外}": (0xB0, 3),
    "{感叹结尾}": (0xD2, 2),
    "{惊问结尾}": (0xCC, 3),
    "{双感叹结尾}": (0xD0, 3),
}
EXPECTED_PARENT_SHA256 = "9df6947b9e8ef7d651fe205af739552255707c4396c82b47ba90fd487343c859"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_6_opening_dialogue.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_6_opening_dialogue.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.6-opening-dialogue.json"
MARKER = 0x8F
BANK11 = 0x44000
BANK11_END = 0x48000
FIRST_ROUTER = 0x40EC0
SECOND_ROUTER = 0x40F99
THIRD_ROUTER = 0x411CD
CLOSE_ROUTER = 0x428C3
BANK_THUNK = 0x43048


def bank11_cpu_address(offset: int) -> int:
    if not BANK11 <= offset < BANK11_END:
        raise ValueError(f"file offset 0x{offset:X} is outside bank $11")
    return 0x4000 + offset - BANK11


def prepare_pages() -> tuple[dict[str, int], dict[int, bytes]]:
    text = "".join(page[2] for page in PAGES)
    for token in MACROS:
        text = text.replace(token, "")
    text += "是从外"
    characters = [c for c in required_custom_characters(text) if c not in "。！？"]
    asset = json.loads((ROOT / "data/chinese_glyphs_oni5_v266_dialogues.json").read_text(encoding="utf-8"))
    load_glyph_patterns((asset,), characters)
    excluded = RESERVED_TILE_IDS | NATIVE_QUOTE_TILES | CURRENT_NAME_TILES | {0xBE}
    fixed = {"是": 0xB4, "从": 0x98, "外": 0x99}
    tiles = [tile for tile in range(0x80, 0xC0) if tile not in excluded | set(fixed.values())]
    remaining = [character for character in characters if character not in fixed]
    if len(remaining) > len(tiles) or set(fixed.values()) & excluded:
        raise ValueError("not enough suitable glyph tiles for pre-battle dialogue")
    mapping = fixed | dict(zip(remaining, tiles))
    codes = {character: tile - 0x80 for character, tile in mapping.items()}
    pages = {
        start: encode_translation_span(text, codes, end - start, 0, MACROS)
        for start, end, text in PAGES
    }
    return mapping, pages


def build_load_router(cursor: int, expected_marker: int, tile: int, next_router: int) -> bytes:
    code = bytearray()
    branches = []
    for address, expected in ((0xFFAA, 4), (0xFFAE, 0x37), (0xFFAD, cursor), (0xC4F2, expected_marker)):
        code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
        branches.append(len(code) - 1)
    code.extend(b"\xCD" + bank_cpu_address(BANK_THUNK).to_bytes(2, "little"))
    code.extend(bytes((0x3E, MARKER)) + bytes.fromhex("EA F2 C4"))
    code.extend(bytes((0x3E, tile)) + bytes.fromhex("EA F0 C4 06 CD 3E 01 C9"))
    for branch in branches:
        code[branch] = len(code) - branch - 1
    code.extend(b"\xC3" + next_router.to_bytes(2, "little"))
    return bytes(code)


def build_close_router() -> bytes:
    code = bytearray(bytes.fromhex("CD C7 60"))
    branches = []
    for address, expected in ((0xFFAA, 4), (0xFFAE, 0x37), (0xFFAD, 0xA4), (0xC4F2, MARKER)):
        code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
        branches.append(len(code) - 1)
    code.extend(bytes.fromhex("CD 9A 7D AF EA F2 C4"))
    for branch in branches:
        code[branch] = len(code) - branch - 1
    code.append(0xC9)
    return bytes(code)


def install_components(target: bytearray, mapping: dict[str, int], pages: dict[int, bytes]) -> dict[str, int]:
    if target[BANK11:BANK11_END] != b"\xFF" * (BANK11_END - BANK11):
        raise ValueError("bank $11 is not free")
    if target[MBC1_MIRROR_OFFSET + BANK11:MBC1_MIRROR_OFFSET + BANK11_END] != b"\xFF" * (BANK11_END - BANK11):
        raise ValueError("bank $31 mirror is not free")
    if target[0x40100:0x40108] != bytes.fromhex("CD 4F 60 B7 C0 C3 30 40"):
        raise ValueError("unexpected V2.6.5 load gateway")
    if target[0x43040:0x43048] != bytes.fromhex("F5 CD C7 60 F1 C3 80 70"):
        raise ValueError("unexpected V2.6.5 close gateway")
    asset = json.loads((ROOT / "data/chinese_glyphs_oni5_v266_dialogues.json").read_text(encoding="utf-8"))
    patterns = load_glyph_patterns((asset,), list(mapping))
    first, _ = prepare_first_pages()
    later, _ = prepare_later_pages()
    if set(mapping.values()) - (set(first.values()) | set(later.values())):
        raise ValueError("the existing restore helper does not cover every new glyph")
    copy = build_compact_copy_helper()
    wrapper_offset = BANK11 + len(copy)
    table_offset = wrapper_offset + 17
    table = encode_compact_glyph_table({tile: patterns[character] for character, tile in mapping.items()})
    wrapper = (bytes.fromhex("C5 D5 E5 F5 21") + bank11_cpu_address(table_offset).to_bytes(2, "little")
               + bytes((0x06, len(mapping), 0xCD)) + bank11_cpu_address(BANK11).to_bytes(2, "little")
               + bytes.fromhex("F1 E1 D1 C1 C9"))
    if len(wrapper) != 17:
        raise ValueError("unexpected compact loader size")
    target[BANK11:BANK11 + len(copy)] = copy
    target[wrapper_offset:wrapper_offset + len(wrapper)] = wrapper
    target[table_offset:table_offset + len(table)] = table
    thunk = (bytes.fromhex("F5 3E 11 EA 00 20 CD") + bank11_cpu_address(wrapper_offset).to_bytes(2, "little")
             + bytes.fromhex("3E 10 EA 00 20 F1 C9"))
    target[BANK11 + (BANK_THUNK - SOURCE_SIZE):BANK11 + (BANK_THUNK - SOURCE_SIZE) + len(thunk)] = thunk
    first = build_load_router(0x3B, 0, 0xBB, bank_cpu_address(SECOND_ROUTER))
    second = build_load_router(0x77, MARKER, 0xBB, bank_cpu_address(THIRD_ROUTER))
    third = build_load_router(0x8C, MARKER, pages[0x1378B][0] + 0x80, 0x604F)
    close = build_close_router()
    for start, end, code in (
        (FIRST_ROUTER, 0x40F00, first),
        (SECOND_ROUTER, 0x40FD0, second),
        (THIRD_ROUTER, 0x41200, third),
        (CLOSE_ROUTER, 0x42900, close),
        (BANK_THUNK, 0x43080, thunk),
    ):
        if start + len(code) > end or target[start:start + len(code)] != b"\xFF" * len(code):
            raise ValueError(f"V2.6.6 component overlaps existing data at ${start:06X}")
        target[start:start + len(code)] = code
    target[0x40101:0x40103] = bank_cpu_address(FIRST_ROUTER).to_bytes(2, "little")
    target[0x43042:0x43044] = bank_cpu_address(CLOSE_ROUTER).to_bytes(2, "little")
    return {"first_router": FIRST_ROUTER, "second_router": SECOND_ROUTER, "third_router": THIRD_ROUTER,
            "close_router": CLOSE_ROUTER, "bank_thunk": BANK_THUNK, "bank11_copy": BANK11,
            "bank11_loader": wrapper_offset, "bank11_table": table_offset}


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != EXPECTED_PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.5 parent ROM failed SHA-256 or checksum verification")
    for code, expected in ((0xB0, "34 18 19"), (0xD2, "4B 3C"), (0xCC, "4B 4A 3C"), (0xD0, "4B 4B 3C")):
        if _read_macro(parent, code) != bytes.fromhex(expected):
            raise ValueError(f"unexpected original macro ${code:02X}")
    mapping, pages = prepare_pages()
    if pages[0x13738][:4] != bytes.fromhex("80 7D 3B B0") or pages[0x13774][:3] != bytes.fromhex("80 7D 3B"):
        raise ValueError("first character triggers no longer match their page positions")
    if not 0 <= pages[0x1378B][0] < 0x40:
        raise ValueError("third page does not begin with a direct glyph")
    target = bytearray(parent)
    for index, (start, end, _) in enumerate(PAGES):
        if parent[start - 1] != (0x57 if index == 1 else 0x7C) or parent[end] != 0x7F:
            raise ValueError(f"unexpected control bytes around page ${start:06X}")
        if parent[MBC1_MIRROR_OFFSET + start - 1:MBC1_MIRROR_OFFSET + end + 1] != parent[start - 1:end + 1]:
            raise ValueError(f"parent mirror differs around page ${start:06X}")
        target[start:end] = pages[start]
        target[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end] = pages[start]
    components = install_components(target, mapping, pages)
    for start in (SOURCE_SIZE, BANK11):
        target[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + start + 0x4000] = target[start:start + 0x4000]
    target = update_checksums(target)
    if len(target) != len(parent) or not verify_rom(target).passed:
        raise ValueError("V2.6.6 ROM failed size or checksum verification")
    patch = create_bps_patch(parent, target)
    if apply_bps_patch(parent, patch) != target:
        raise ValueError("V2.6.5-to-V2.6.6 BPS round-trip failed")
    version: dict[str, object] = {
        "schema_version": 1,
        "version_id": "V2.6.6-opening-dialogue",
        "parent_version": {"version_id": "V2.6.5-opening-dialogue", "sha256": EXPECTED_PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(target).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {
            "status": "pending-sameboy",
            "limitations": [
                "Only the observed protagonist name tiles and voiced mark are protected.",
                "Loading, bank switching, glyph restoration and the first battle require SameBoy verification.",
            ],
        },
        "implementation": {"glyph_components": {k: f"0x{v:06X}" for k, v in components.items()}},
    }
    return bytes(target), patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace existing V2.6.6 outputs")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("V2.6.6 output already exists; pass --overwrite to replace it")
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
