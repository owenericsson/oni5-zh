"""Build versioned V1 patches for the roam dialogue contexts."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

if __package__:
    from .apply_bps_patch import apply_bps_patch, create_bps_patch
    from .build_mbc1_expansion_probe import SOURCE_SIZE
    from .build_opening_dialogue_pilot import build_opening_dialogue_pilot
    from .build_rom import write_output
else:
    from apply_bps_patch import apply_bps_patch, create_bps_patch
    from build_mbc1_expansion_probe import SOURCE_SIZE
    from build_opening_dialogue_pilot import build_opening_dialogue_pilot
    from build_rom import write_output

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_V1_SHA256 = "5682522e20fade44c457725a66430bae13e3d6695dcc18e04d058e4ce2e910ab"
DIALOGUE_CONTEXT_IDS = ("noticeboard", "woman")


def build_v2_4_patch(
    parent_rom: bytes,
    source_rom: bytes,
    manifest: Any,
    opening_glyph_asset: Any,
    shared_glyph_asset: Any,
    practice_glyph_asset: Any,
    tile_candidate: Any,
    encoding_candidate: Any,
    context_plan: Any,
    context_encoding: Any,
    prefilter_pointer_highs: bool = False,
    clear_dialogue_upper_tile: bool = False,
    include_garou: bool = False,
    restore_dialogue_patterns_from_rom: bool = False,
    preserve_dialogue_return_code: bool = False,
) -> tuple[bytes, str]:
    if hashlib.sha256(parent_rom).hexdigest() != EXPECTED_V1_SHA256:
        raise ValueError("V2.4 parent ROM must match the immutable V1-opening-dialog SHA-256")
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    if include_garou and not (prefilter_pointer_highs and clear_dialogue_upper_tile):
        raise ValueError(
            "including Garou requires pointer-high filtering and the blank upper-tile return"
        )
    if restore_dialogue_patterns_from_rom and not (
        prefilter_pointer_highs and clear_dialogue_upper_tile and include_garou
    ):
        raise ValueError(
            "ROM-backed dialogue restoration requires the V2.4.3 context and safety gates"
        )
    if preserve_dialogue_return_code and not (
        prefilter_pointer_highs
        and clear_dialogue_upper_tile
        and include_garou
        and restore_dialogue_patterns_from_rom
    ):
        raise ValueError(
            "return-code restoration requires the V2.4.4 context and safety gates"
        )
    dialogue_context_ids = (
        (*DIALOGUE_CONTEXT_IDS, "garou") if include_garou else DIALOGUE_CONTEXT_IDS
    )

    target_rom = build_opening_dialogue_pilot(
        parent_rom,
        source_rom,
        manifest,
        opening_glyph_asset,
        shared_glyph_asset,
        practice_glyph_asset,
        tile_candidate,
        encoding_candidate,
        context_plan,
        context_encoding,
        dialogue_context_ids=dialogue_context_ids,
        gateway_layout="v2.2",
        prefilter_pointer_highs=prefilter_pointer_highs,
        dialogue_loader_return_b=0xCD if clear_dialogue_upper_tile else None,
        restore_dialogue_patterns_from_rom=restore_dialogue_patterns_from_rom,
        preserve_dialogue_return_code=preserve_dialogue_return_code,
    )
    patch = create_bps_patch(parent_rom, target_rom)
    if apply_bps_patch(parent_rom, patch) != target_rom:
        raise ValueError("V1-to-roam-dialogue BPS round-trip did not reproduce the target")
    return patch, hashlib.sha256(target_rom).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_file(
    parent_path: Path,
    source_path: Path,
    output_path: Path,
    overwrite: bool = False,
    prefilter_pointer_highs: bool = False,
    clear_dialogue_upper_tile: bool = False,
    include_garou: bool = False,
    restore_dialogue_patterns_from_rom: bool = False,
    preserve_dialogue_return_code: bool = False,
) -> tuple[Path, str, str]:
    parent_path = parent_path.resolve(strict=True)
    source_path = source_path.resolve(strict=True)
    input_paths = {
        ROOT / "data" / "text_manifest.json",
        ROOT / "data" / "chinese_glyphs_oni5_bank04_01330d.json",
        ROOT / "data" / "chinese_glyphs.json",
        ROOT / "data" / "chinese_glyphs_oni5_bank24_01348f.json",
        ROOT / "data" / "tile_cache_plan_candidate.json",
        ROOT / "data" / "translation_encoding_candidate.json",
        ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json",
        ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json",
    }
    output_path = output_path.resolve()
    if output_path in {parent_path, source_path} or output_path in input_paths:
        raise ValueError("BPS output path must differ from every input")
    if not output_path.parent.is_dir():
        raise ValueError("BPS output directory must already exist")
    if output_path.exists() and not overwrite:
        raise FileExistsError("BPS output already exists; pass --overwrite to replace it")

    inputs = [
        load_json(path)
        for path in (
            ROOT / "data" / "text_manifest.json",
            ROOT / "data" / "chinese_glyphs_oni5_bank04_01330d.json",
            ROOT / "data" / "chinese_glyphs.json",
            ROOT / "data" / "chinese_glyphs_oni5_bank24_01348f.json",
            ROOT / "data" / "tile_cache_plan_candidate.json",
            ROOT / "data" / "translation_encoding_candidate.json",
            ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json",
            ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json",
        )
    ]
    patch, target_digest = build_v2_4_patch(
        parent_path.read_bytes(),
        source_path.read_bytes(),
        *inputs,
        prefilter_pointer_highs=prefilter_pointer_highs,
        clear_dialogue_upper_tile=clear_dialogue_upper_tile,
        include_garou=include_garou,
        restore_dialogue_patterns_from_rom=restore_dialogue_patterns_from_rom,
        preserve_dialogue_return_code=preserve_dialogue_return_code,
    )
    write_output(output_path, patch, overwrite)
    if output_path.read_bytes() != patch:
        raise OSError(f"written BPS patch differs from generated patch: {output_path}")
    return output_path, hashlib.sha256(patch).hexdigest(), target_digest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build versioned V1 patches for selected roam dialogue contexts."
    )
    parser.add_argument("--parent", type=Path, default=ROOT / "roms" / "oni5_v1_opening_dialog.gb")
    parser.add_argument("--source", type=Path, default=ROOT / "roms" / "oni5_original.gb")
    parser.add_argument(
        "--output",
        type=Path,
    )
    parser.add_argument(
        "--prefilter-pointer-highs",
        action="store_true",
        help="Gate the shared entry by selected text pointer highs before switching ROM banks.",
    )
    parser.add_argument(
        "--clear-dialogue-upper-tile",
        action="store_true",
        help="Set B to the blank upper-row tile after loading the first dialogue glyph.",
    )
    parser.add_argument(
        "--include-garou",
        action="store_true",
        help="Add the translated Garou dialogue context (V2.4.3 candidate).",
    )
    parser.add_argument(
        "--restore-dialogue-patterns-from-rom",
        action="store_true",
        help="Keep the game WRAM tile-font staging buffer untouched (V2.4.4 candidate).",
    )
    parser.add_argument(
        "--preserve-dialogue-return-code",
        action="store_true",
        help="Restore the previous C4F0 return tile when a dialogue cache is closed (V2.4.5 candidate).",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.clear_dialogue_upper_tile and not args.prefilter_pointer_highs:
        parser.error("--clear-dialogue-upper-tile requires --prefilter-pointer-highs")
    if args.include_garou and not (
        args.prefilter_pointer_highs and args.clear_dialogue_upper_tile
    ):
        parser.error(
            "--include-garou requires --prefilter-pointer-highs and --clear-dialogue-upper-tile"
        )
    if args.restore_dialogue_patterns_from_rom and not (
        args.prefilter_pointer_highs
        and args.clear_dialogue_upper_tile
        and args.include_garou
    ):
        parser.error(
            "--restore-dialogue-patterns-from-rom requires --prefilter-pointer-highs, "
            "--clear-dialogue-upper-tile, and --include-garou"
        )
    if args.preserve_dialogue_return_code and not (
        args.prefilter_pointer_highs
        and args.clear_dialogue_upper_tile
        and args.include_garou
        and args.restore_dialogue_patterns_from_rom
    ):
        parser.error(
            "--preserve-dialogue-return-code requires --prefilter-pointer-highs, "
            "--clear-dialogue-upper-tile, --include-garou, and "
            "--restore-dialogue-patterns-from-rom"
        )
    if args.preserve_dialogue_return_code:
        default_output_name = "oni5_v2_4_5_roam_dialogues.bps"
        version_label = "V2.4.5"
    elif args.restore_dialogue_patterns_from_rom:
        default_output_name = "oni5_v2_4_4_roam_dialogues.bps"
        version_label = "V2.4.4"
    elif args.include_garou:
        default_output_name = "oni5_v2_4_3_roam_dialogues.bps"
        version_label = "V2.4.3"
    elif args.clear_dialogue_upper_tile:
        default_output_name = "oni5_v2_4_2_roam_dialogues.bps"
        version_label = "V2.4.2"
    elif args.prefilter_pointer_highs:
        default_output_name = "oni5_v2_4_1_roam_dialogues.bps"
        version_label = "V2.4.1"
    else:
        default_output_name = "oni5_v2_4_roam_dialogues.bps"
        version_label = "V2.4"
    output_path = args.output or ROOT / "roms" / (
        default_output_name
    )
    try:
        output, patch_digest, target_digest = build_file(
            args.parent,
            args.source,
            output_path,
            args.overwrite,
            args.prefilter_pointer_highs,
            args.clear_dialogue_upper_tile,
            args.include_garou,
            args.restore_dialogue_patterns_from_rom,
            args.preserve_dialogue_return_code,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote V1-to-{version_label} BPS patch: {output} ({output.stat().st_size} bytes)")
    print(f"BPS SHA-256: {patch_digest}")
    print(f"Target ROM SHA-256: {target_digest}")


if __name__ == "__main__":
    main()
