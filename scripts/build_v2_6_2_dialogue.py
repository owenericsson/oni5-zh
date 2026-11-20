"""Build the Shizuna follow-up from the accepted V2.6.1 ROM."""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET, MENU_EXPANDED_SIZE
from scripts.build_opening_text_preview_patch import (
    FONT_BANK,
    FONT_DESCRIPTOR,
    FONT_LENGTH,
    create_glyph_mapping,
)
from scripts.build_text_comparison_pilot import (
    PilotContext,
    align_up,
    bank_cpu_address,
    build_loader_helper,
    build_restore_helper,
)
from scripts.build_v2_6_1_single_dialogue import (
    LOAD_DISPATCHER_OFFSET,
    MARKER,
    NATIVE_QUOTE_TILES,
    OUTPUT_ROM as V2_6_1_ROM,
    PROTAGONIST_NATIVE_TILES,
    REPLY_MARKER,
    RESTORE_WRAPPER_OFFSET,
    SHIZUNA_FOLLOWUP_TEXT_SPAN,
    SOURCE_ROM,
    SOURCE_SIZE,
    TOKIWA_FIRST_CURSOR,
    TOKIWA_MARKER,
    TOKIWA_RECORD_ID,
    TOKIWA_TEXT_SPAN,
    _candidate_excluding_tiles,
    _load_json,
    _require_object,
    _translation_text,
)
from scripts.build_v2_6_prologue_patch import EXPECTED_SOURCE_SHA256, encode_translation_span
from scripts.decode_gb_resource import decode_resource
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_V2_6_1_SHA256 = (
    "afe11e0f8aa3d035d76432652aada1c2b3dc2da0a95805783e2a869dae9300cf"
)
OUTPUT_ROM = ROOT / "roms" / "oni5_v2_6_2_opening_dialogue.gb"
OUTPUT_PATCH = ROOT / "roms" / "oni5_v2_6_2_opening_dialogue.bps"
OUTPUT_VERSION = ROOT / "versions" / "V2.6.2-opening-dialogue.json"
HELPER_START = SOURCE_SIZE + 0x2580
HELPER_END = SOURCE_SIZE + 0x2900
RESTORE_CURSOR = 0x7C
PUNCTUATION_MACRO = 0xD2


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = V2_6_1_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != EXPECTED_V2_6_1_SHA256:
        raise ValueError("V2.6.1 parent ROM SHA-256 mismatch")
    if len(parent) != MENU_EXPANDED_SIZE or not verify_rom(parent).passed:
        raise ValueError("V2.6.1 parent ROM failed size or checksum verification")

    start, end = SHIZUNA_FOLLOWUP_TEXT_SPAN
    if parent[start - 1:end + 1] != bytes.fromhex(
        "7C AD 7D 3B 95 08 18 2F D5 D5 22 08 3C 7F"
    ):
        raise ValueError("V2.6.1 follow-up text does not match the expected source")
    macro_bank = 0x0C * 0x4000
    if parent[macro_bank + 0x2A4:macro_bank + 0x2A6] != bytes.fromhex("C5 04"):
        raise ValueError("native $D2 macro has an unexpected table pointer")
    if parent[macro_bank + 0x4C5:macro_bank + 0x4C8] != bytes.fromhex("02 4B 3C"):
        raise ValueError("native $D2 macro no longer expands to ！ and 」")

    manifest = _load_json(ROOT / "data" / "text_manifest.json")
    record = _require_object(
        next(item for item in manifest["records"] if item.get("id") == TOKIWA_RECORD_ID),
        "Tokiwa dialogue record",
    )
    previous_text = _translation_text(record, *TOKIWA_TEXT_SPAN)
    followup_text = _translation_text(record, start, end)
    expanded_followup = followup_text.replace("{静那}", "静那").replace(
        "{常叶丸}", "常叶丸"
    )
    if not expanded_followup.endswith("！」"):
        raise ValueError("follow-up translation does not end with ！ and 」")
    glyph_text = previous_text + expanded_followup
    for character in ("\n", "「", "」", "！", "？", "。"):
        glyph_text = glyph_text.replace(character, "")
    candidate = _candidate_excluding_tiles(
        _load_json(ROOT / "data" / "tile_cache_plan_candidate.json"),
        frozenset({MARKER, REPLY_MARKER, TOKIWA_MARKER})
        | PROTAGONIST_NATIVE_TILES
        | NATIVE_QUOTE_TILES,
    )
    assets = tuple(
        _load_json(ROOT / "data" / name)
        for name in (
            "chinese_glyphs_oni5_bank04_prologue_v26.json",
            "chinese_glyphs_oni5_bank04_prologue_v261.json",
            "chinese_glyphs_oni5_v261_remaining_dialogues.json",
            "chinese_glyphs_oni5_bank04_01342e.json",
            "chinese_glyphs_oni5_bank04_01330d.json",
            "chinese_glyphs_oni5_bank04_01346f.json",
        )
    )
    glyphs, codes = create_glyph_mapping(glyph_text, assets, candidate)
    previous_payload = encode_translation_span(
        previous_text, codes, TOKIWA_TEXT_SPAN[1] - TOKIWA_TEXT_SPAN[0], 0
    )
    if previous_payload != parent[slice(*TOKIWA_TEXT_SPAN)]:
        raise ValueError("new glyph allocation would change the V2.6.1 Tokiwa dialogue")
    payload = encode_translation_span(
        expanded_followup,
        codes,
        end - start,
        0,
        macro_tokens={"！」": (PUNCTUATION_MACRO, 2)},
    )
    if payload[-1] != PUNCTUATION_MACRO:
        raise ValueError("follow-up punctuation macro is not at the end of the page")

    source = SOURCE_ROM.read_bytes()
    if hashlib.sha256(source).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise ValueError("original ROM SHA-256 mismatch")
    font = decode_resource(source, FONT_BANK, FONT_DESCRIPTOR, FONT_LENGTH)
    originals = tuple(font[(glyph.tile - 0x80) * 16:(glyph.tile - 0x7F) * 16] for glyph in glyphs)
    if any(len(pattern) != 16 for pattern in originals):
        raise ValueError("original font is missing a dialogue glyph backup pattern")
    context = PilotContext(
        record_id="opening",
        bank=0x04,
        pointer_high=0x34,
        first_cursor=TOKIWA_FIRST_CURSOR,
        restore_cursor=RESTORE_CURSOR,
        source_offset=TOKIWA_TEXT_SPAN[0],
        payload=previous_payload,
        glyphs=tuple(glyphs),
        marker=TOKIWA_MARKER,
        restore_from_rom=True,
        original_patterns=originals,
        return_code=glyphs[0].tile,
        loader_return_b=0xCD,
    )
    loader_offset = HELPER_START
    loader_size = len(build_loader_helper(context, 0x4100))
    pattern_offset = align_up(loader_offset + loader_size, 16)
    pattern_data = b"".join(glyph.pattern for glyph in glyphs)
    original_offset = align_up(pattern_offset + len(pattern_data), 16)
    original_data = b"".join(originals)
    restore_offset = align_up(original_offset + len(original_data), 16)
    loader = build_loader_helper(context, bank_cpu_address(pattern_offset))
    restore = build_restore_helper(
        context, bank_cpu_address(restore_offset), bank_cpu_address(original_offset)
    )
    helper_end = restore_offset + len(restore)
    if helper_end > HELPER_END or parent[HELPER_START:helper_end] != b"\xFF" * (helper_end - HELPER_START):
        raise ValueError("V2.6.2 helpers exceed the verified free bank-10 area")

    dispatcher = LOAD_DISPATCHER_OFFSET
    if parent[dispatcher + 116:dispatcher + 121] != bytes.fromhex("FA AD FF FE 6E"):
        raise ValueError("V2.6.1 Tokiwa load boundary has an unexpected layout")
    if parent[dispatcher + 132:dispatcher + 135] != bytes.fromhex("CD D3 7A"):
        raise ValueError("V2.6.1 Tokiwa loader call has an unexpected layout")
    old_loader = SOURCE_SIZE + 0x7AD3 - 0x4000
    old_pattern_address = int.from_bytes(parent[old_loader + 4:old_loader + 6], "little")
    old_pattern_offset = SOURCE_SIZE + old_pattern_address - 0x4000
    previous_glyphs, _ = create_glyph_mapping(
        "".join(character for character in previous_text if character not in "\n「」！？。"),
        assets,
        candidate,
    )
    if glyphs[:len(previous_glyphs)] != previous_glyphs:
        raise ValueError("new glyph allocation would change existing glyph patterns")
    previous_pattern_data = b"".join(glyph.pattern for glyph in previous_glyphs)
    if parent[old_pattern_offset:old_pattern_offset + len(previous_pattern_data)] != previous_pattern_data:
        raise ValueError("V2.6.1 Tokiwa glyph patterns do not match the source assets")
    router = parent[RESTORE_WRAPPER_OFFSET:RESTORE_WRAPPER_OFFSET + 8]
    if router[:2] != bytes.fromhex("F5 CD"):
        raise ValueError("V2.6.1 restore router has an unexpected layout")
    restore_dispatcher = SOURCE_SIZE + int.from_bytes(router[2:4], "little") - 0x4000
    if parent[restore_dispatcher + 31:restore_dispatcher + 46] != bytes.fromhex(
        "FE 89 20 0A FA AD FF FE 6E 20 03 CA 80 7C C9"
    ):
        raise ValueError("V2.6.1 Tokiwa restore dispatch has an unexpected layout")

    target = bytearray(parent)
    target[start:end] = payload
    target[MBC1_MIRROR_OFFSET + start:MBC1_MIRROR_OFFSET + end] = payload
    target[loader_offset:loader_offset + len(loader)] = loader
    target[pattern_offset:pattern_offset + len(pattern_data)] = pattern_data
    target[original_offset:original_offset + len(original_data)] = original_data
    target[restore_offset:helper_end] = restore
    target[dispatcher + 120] = RESTORE_CURSOR
    target[dispatcher + 133:dispatcher + 135] = bank_cpu_address(loader_offset).to_bytes(2, "little")
    target[restore_dispatcher + 39] = RESTORE_CURSOR
    target[restore_dispatcher + 43:restore_dispatcher + 45] = bank_cpu_address(restore_offset).to_bytes(2, "little")
    target[MBC1_MIRROR_OFFSET + SOURCE_SIZE:MBC1_MIRROR_OFFSET + SOURCE_SIZE + 0x4000] = target[
        SOURCE_SIZE:SOURCE_SIZE + 0x4000
    ]
    target = update_checksums(target)
    if not verify_rom(target).passed:
        raise ValueError("V2.6.2 ROM failed checksum verification")
    patch = create_bps_patch(parent, target)
    if apply_bps_patch(parent, patch) != target:
        raise ValueError("V2.6.1-to-V2.6.2 BPS round-trip failed")
    version = {
        "schema_version": 1,
        "version_id": "V2.6.2-opening-dialogue",
        "parent_version": {
            "version_id": "V2.6.1-opening-dialogue",
            "path": f"../roms/{V2_6_1_ROM.name}",
            "sha256": EXPECTED_V2_6_1_SHA256,
        },
        "patch": {
            "path": f"../roms/{OUTPUT_PATCH.name}",
            "size_bytes": len(patch),
            "sha256": hashlib.sha256(patch).hexdigest(),
        },
        "target_rom": {
            "path": f"../roms/{OUTPUT_ROM.name}",
            "size_bytes": len(target),
            "sha256": hashlib.sha256(target).hexdigest(),
            "persisted_by_builder": True,
        },
        "runtime_validation": {
            "status": "sameboy-confirmed-by-user",
            "tested_rom_sha256": None,
            "confirmation": "User reported that V2.6.2 passed testing and selected it as the new baseline; the tested ROM hash was not independently confirmed.",
            "required_sameboy_checks": [
                "Check the previous V2.6.1 dialogue and the translated Shizuna page.",
                "Advance beyond the dialogue and verify subsequent scenes and text remain normal.",
                "Check that the original glyphs are restored after the two-page dialogue.",
            ],
        },
        "implementation": {
            "followup_text_span": [f"0x{start:06X}", f"0x{end:06X}"],
            "native_punctuation_macro": "0xD2",
            "glyph_tiles": {glyph.character: f"0x{glyph.tile:02X}" for glyph in glyphs},
            "loader_offset": f"0x{loader_offset:06X}",
            "pattern_offset": f"0x{pattern_offset:06X}",
            "original_pattern_offset": f"0x{original_offset:06X}",
            "restore_offset": f"0x{restore_offset:06X}",
            "helper_end": f"0x{helper_end:06X}",
        },
        "automated_validation": {
            "checksum": "Target ROM passes size and checksum verification.",
            "bps_round_trip": "Applying the V2.6.1-to-V2.6.2 BPS reproduces the target ROM.",
            "parent_dialogue": "The original V2.6.1 Tokiwa dialogue encoding is unchanged.",
        },
    }
    return target, patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace existing V2.6.2 outputs")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("V2.6.2 output already exists; pass --overwrite to replace it")
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
