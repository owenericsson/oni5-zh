"""Build the confirmed post-battle dialogue on the V2.6.6 baseline."""
import argparse
import hashlib
import json

from scripts import build_v2_6_6_dialogue as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_opening_text_preview_patch import (
    FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH, load_glyph_patterns, required_custom_characters,
)
from scripts.build_text_comparison_pilot import bank_cpu_address
from scripts.build_v2_6_1_single_dialogue import SOURCE_ROM, SOURCE_SIZE
from scripts.build_v2_6_3_dialogue import _read_macro
from scripts.build_v2_6_4_dialogue import (
    CURRENT_NAME_TILES, ROOT, encode_compact_glyph_table, prepare_first_pages,
    prepare_later_pages, split_original_patterns,
)
from scripts.build_v2_6_prologue_patch import (
    NATIVE_QUOTE_TILES, RESERVED_TILE_IDS, encode_translation_span,
)
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import update_checksums, verify_rom

PAGES = (
    (0x13A40, 0x13A52, "{主角}\n「那家伙到底是什么人{省略}{问结}"),
    (0x13A59, 0x13A61, "伽罗\n「{主角}{长音}{长音}{感叹结}"),
    (0x13A7C, 0x13A88, "伽罗\n「你没事吧，{主角}{问结}"),
    (0x13A8F, 0x13A95, "{主角}\n「嗯。」"),
    (0x13AA4, 0x13AB4, "妖怪\n「{竟敢对}同伴下手！吃我这招{感叹结}"),
    (0x13ABD, 0x13AC7, "弥生\n「啊{感叹结}"),
    (0x13AE0, 0x13AEB, "伽罗\n「啊！阿姨{感叹结}"),
    (0x13AF0, 0x13B0C, "妖怪\n「那个女人我们要带走，\n献给魔王当祭品{感叹结}"),
    (0x13B13, 0x13B1B, "{主角}\n「妈{长音}妈妈{双感叹结}"),
    (0x13B22, 0x13B53, "弥生\n「呜{省略}{主角}，去三日月山{省略}\n那里有能改变你命运的东西{省略}」"),
    (0x13B55, 0x13B63, "{主角}\n「你在说什么啊{问结}"),
    (0x13B65, 0x13B73, "弥生\n「是三日月山{省略}{省略}」"),
    (0x13B88, 0x13B93, "伽罗\n「啊，阿姨{长音}{双感叹结}"),
    (0x13B98, 0x13BA3, "{主角}\n「妈妈{长音}{长音}{感叹结}"),
    (0x13BA9, 0x13BB5, "男人\n「什么？这是{什么声}音{惊问结}"),
    (0x13BB7, 0x13BC5, "男人\n「喂，发生什么事了{问结}"),
)
GROUPS = (PAGES[:4], PAGES[4:9], PAGES[9:12], PAGES[12:])
MACROS = {
    "{主角}": (0x80, 5), "{省略}": (0xD5, 2), "{长音}": (0xD4, 2),
    "{问结}": (0xCE, 2), "{感叹结}": (0xD2, 2), "{双感叹结}": (0xD0, 3),
    "{惊问结}": (0xCC, 3), "{竟敢对}": (0xB0, 3), "{什么声}": (0xB0, 3),
}
EXPECTED_PARENT_SHA256 = "a5f22750a56839635130d19b1df787b82f930fa65676b9a995256b4507f23ae0"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_7_opening_dialogue.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_7_opening_dialogue.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.7-opening-dialogue.json"
MARKERS = (0x90, 0x91, 0x92, 0x93)
LOAD_THUNK = 0x421E0
LOAD_GATE = 0x408EC
CLOSE_THUNK = 0x422E0
CLOSE_GATE = 0x422F0
COMPONENT_START = 0x45000
COMPONENT_END = 0x47000


def prepare_pages() -> tuple[list[dict[str, int]], dict[int, bytes]]:
    asset = json.loads((ROOT / "data/chinese_glyphs_oni5_v267_dialogues.json").read_text(encoding="utf-8"))
    excluded = RESERVED_TILE_IDS | NATIVE_QUOTE_TILES | CURRENT_NAME_TILES | {0xB7, 0xBE, 0xBF}
    fixed_by_group = ({}, {"竟": 0xB4, "敢": 0x98, "对": 0x99}, {},
                      {"什": 0xB4, "么": 0x98, "声": 0x99})
    mappings = []
    pages = {}
    for group, fixed in zip(GROUPS, fixed_by_group):
        text = "".join(page[2] for page in group)
        for token in MACROS:
            text = text.replace(token, "")
        text += "".join(fixed)
        characters = [c for c in required_custom_characters(text) if c not in "。！？"]
        load_glyph_patterns((asset,), characters)
        tiles = [tile for tile in range(0x80, 0xC0) if tile not in excluded | set(fixed.values())]
        remaining = [character for character in characters if character not in fixed]
        if len(remaining) > len(tiles) or set(fixed.values()) & excluded:
            raise ValueError("not enough suitable glyph tiles for dialogue group")
        mapping = fixed | dict(zip(remaining, tiles))
        codes = {character: tile - 0x80 for character, tile in mapping.items()}
        for start, end, page in group:
            pages[start] = encode_translation_span(page, codes, end - start, 0, MACROS)
        mappings.append(mapping)
    return mappings, pages


def build_thunk(dispatcher: int) -> bytes:
    return (bytes.fromhex("3E 11 EA 00 20 CD") + previous.bank11_cpu_address(dispatcher).to_bytes(2, "little")
            + bytes.fromhex("F5 3E 10 EA 00 20 F1 C9"))


def build_load_dispatcher(loaders: list[int], restore: int, pages: dict[int, bytes]) -> bytes:
    code = bytearray()
    triggers = ((0x3A, 0x43, 0, 0xBB), (0x3A, 0xA5, MARKERS[0], pages[0x13AA4][0] + 0x80),
                (0x3B, 0x23, MARKERS[1], pages[0x13B22][0] + 0x80),
                (0x3B, 0x89, MARKERS[2], pages[0x13B88][0] + 0x80))
    for index, (high, low, old_marker, tile) in enumerate(triggers):
        branches = []
        for address, expected in ((0xFFAA, 4), (0xFFAE, high), (0xFFAD, low), (0xC4F2, old_marker)):
            code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
            branches.append(len(code) - 1)
        if index:
            code.extend(b"\xCD" + previous.bank11_cpu_address(restore).to_bytes(2, "little"))
        code.extend(b"\xCD" + previous.bank11_cpu_address(loaders[index]).to_bytes(2, "little"))
        code.extend(bytes((0x3E, MARKERS[index])) + bytes.fromhex("EA F2 C4"))
        code.extend(bytes((0x3E, tile)) + bytes.fromhex("EA F0 C4 06 CD 3E 01 C9"))
        for branch in branches:
            code[branch] = len(code) - branch - 1
    code.extend(bytes.fromhex("AF C9"))
    return bytes(code)


def build_close_dispatcher(restore: int) -> bytes:
    code = bytearray()
    branches = []
    for address, expected in ((0xFFAA, 4), (0xFFAE, 0x3B), (0xFFAD, 0xC6), (0xC4F2, MARKERS[-1])):
        code.extend(bytes((0xFA, address & 0xFF, address >> 8, 0xFE, expected, 0x20, 0)))
        branches.append(len(code) - 1)
    code.extend(b"\xCD" + previous.bank11_cpu_address(restore).to_bytes(2, "little"))
    code.extend(bytes.fromhex("AF EA F2 C4"))
    for branch in branches:
        code[branch] = len(code) - branch - 1
    code.append(0xC9)
    return bytes(code)


def install_components(target: bytearray, mappings: list[dict[str, int]], pages: dict[int, bytes]) -> dict[str, int]:
    if target[COMPONENT_START:COMPONENT_END] != b"\xFF" * (COMPONENT_END - COMPONENT_START):
        raise ValueError("V2.6.7 bank $11 component range is not free")
    if target[0x40100:0x40108] != bytes.fromhex("CD C0 4E B7 C0 C3 30 40"):
        raise ValueError("unexpected V2.6.6 load gateway")
    if target[0x43040:0x43048] != bytes.fromhex("F5 CD C3 68 F1 C3 80 70"):
        raise ValueError("unexpected V2.6.6 close gateway")
    if target[previous.BANK11:previous.BANK11 + 4] != bytes.fromhex("C5 D5 E5 F5"):
        raise ValueError("unexpected V2.6.6 bank $11 copy helper")
    font = decode_resource(SOURCE_ROM.read_bytes(), FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    first, _ = prepare_first_pages()
    later, _ = prepare_later_pages()
    tiles = set().union(*(set(mapping.values()) for mapping in mappings))
    if tiles - (set(first.values()) | set(later.values())):
        raise ValueError("existing restore helper does not cover every V2.6.7 tile")
    compact, full = split_original_patterns(tiles, font)
    if full:
        raise ValueError("V2.6.7 native restoration requires noncompact patterns")
    asset = json.loads((ROOT / "data/chinese_glyphs_oni5_v267_dialogues.json").read_text(encoding="utf-8"))
    patterns = load_glyph_patterns((asset,), list(dict.fromkeys(c for mapping in mappings for c in mapping)))
    position = COMPONENT_START

    def allocate(data: bytes) -> int:
        nonlocal position
        offset = position
        position += len(data)
        if position > COMPONENT_END:
            raise ValueError("V2.6.7 bank $11 component range is too small")
        target[offset:position] = data
        return offset

    def loader(table: dict[int, bytes]) -> int:
        raw = encode_compact_glyph_table(table)
        table_offset = allocate(raw)
        wrapper = (bytes.fromhex("C5 D5 E5 F5 21") + previous.bank11_cpu_address(table_offset).to_bytes(2, "little")
                   + bytes((0x06, len(table), 0xCD)) + previous.bank11_cpu_address(previous.BANK11).to_bytes(2, "little")
                   + bytes.fromhex("F1 E1 D1 C1 C9"))
        return allocate(wrapper)

    restore = loader(compact)
    loaders = [loader({tile: patterns[character] for character, tile in mapping.items()}) for mapping in mappings]
    dispatch = allocate(build_load_dispatcher(loaders, restore, pages))
    close_dispatch = allocate(build_close_dispatcher(restore))
    for thunk_offset, gate_offset, dispatcher, legacy in (
        (LOAD_THUNK, LOAD_GATE, dispatch, previous.FIRST_ROUTER),
        (CLOSE_THUNK, CLOSE_GATE, close_dispatch, previous.CLOSE_ROUTER),
    ):
        thunk = build_thunk(dispatcher)
        gate = (bytes.fromhex("FA AE FF E6 FE FE 3A 20 05") + b"\xCD"
                + bank_cpu_address(thunk_offset).to_bytes(2, "little") + bytes.fromhex("B7 C0 C3")
                + bank_cpu_address(legacy).to_bytes(2, "little") if thunk_offset == LOAD_THUNK else
                b"\xCD" + bank_cpu_address(legacy).to_bytes(2, "little")
                + bytes.fromhex("FA AE FF FE 3B 20 03") + b"\xCD"
                + bank_cpu_address(thunk_offset).to_bytes(2, "little") + b"\xC9")
        for offset, code in ((thunk_offset, thunk), (gate_offset, gate)):
            if target[offset:offset + len(code)] != b"\xFF" * len(code):
                raise ValueError(f"bank $10 component overlaps existing data at ${offset:06X}")
            target[offset:offset + len(code)] = code
        paired = thunk_offset + (previous.BANK11 - SOURCE_SIZE)
        if target[paired:paired + len(thunk)] != b"\xFF" * len(thunk):
            raise ValueError(f"bank $11 thunk overlaps existing data at ${paired:06X}")
        target[paired:paired + len(thunk)] = thunk
    target[0x40101:0x40103] = bank_cpu_address(LOAD_GATE).to_bytes(2, "little")
    target[0x43042:0x43044] = bank_cpu_address(CLOSE_GATE).to_bytes(2, "little")
    return {"restore": restore, "load_dispatcher": dispatch, "close_dispatcher": close_dispatch,
            "component_end": position, "load_gate": LOAD_GATE, "close_gate": CLOSE_GATE}


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != EXPECTED_PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.6 parent ROM failed SHA-256 or checksum verification")
    for code, expected in ((0xB0, "34 18 19"), (0xD4, "37 37"), (0xD5, "3A 3A"),
                           (0xCE, "4A 3C"), (0xD2, "4B 3C"), (0xD0, "4B 4B 3C"), (0xCC, "4B 4A 3C")):
        if _read_macro(parent, code) != bytes.fromhex(expected):
            raise ValueError(f"unexpected original macro ${code:02X}")
    mappings, pages = prepare_pages()
    target = bytearray(parent)
    for index, (start, end, _) in enumerate(PAGES):
        expected_end = 0x7E if index in (9, 10, 14) else 0x7F
        if parent[end] != expected_end:
            raise ValueError(f"unexpected control byte at page end ${end:06X}")
        if parent[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end + 1] != parent[start:end + 1]:
            raise ValueError(f"parent mirror differs around page ${start:06X}")
        target[start:end] = pages[start]
        target[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end] = pages[start]
    if pages[0x13A40][:3] != bytes.fromhex("80 7D 3B") or any(
        pages[start][0] >= 0x40 for start in (0x13AA4, 0x13B22, 0x13B88)
    ):
        raise ValueError("glyph loading triggers no longer match their page positions")
    components = install_components(target, mappings, pages)
    for start in (SOURCE_SIZE, previous.BANK11):
        target[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + start + 0x4000] = target[start:start + 0x4000]
    target = update_checksums(target)
    if len(target) != len(parent) or not verify_rom(target).passed:
        raise ValueError("V2.6.7 ROM failed size or checksum verification")
    patch = create_bps_patch(parent, target)
    if apply_bps_patch(parent, patch) != target:
        raise ValueError("V2.6.6-to-V2.6.7 BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.7-opening-dialogue",
        "parent_version": {"version_id": "V2.6.6-opening-dialogue", "sha256": EXPECTED_PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(target).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Only the observed protagonist name tiles and voiced mark are protected.",
            "Glyph switching, dialogue transitions, and restoration before village movement require SameBoy verification.",
        ]},
        "implementation": {"glyph_components": {k: f"0x{v:06X}" for k, v in components.items()}},
    }
    return bytes(target), patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace existing V2.6.7 outputs")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("V2.6.7 output already exists; pass --overwrite to replace it")
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
