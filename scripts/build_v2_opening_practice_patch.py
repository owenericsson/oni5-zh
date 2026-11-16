"""Build a versioned V1-to-V2 BPS patch containing only the practice dialogue."""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

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
PRACTICE_CONTEXT_ID = "practice"


def build_v2_practice_patch(
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
    *,
    gateway_layout: Literal["v2.1", "v2.2", "v2.3"] = "v2.1",
) -> tuple[bytes, str]:
    if hashlib.sha256(parent_rom).hexdigest() != EXPECTED_V1_SHA256:
        raise ValueError("V2 parent ROM must match the immutable V1-opening-dialog SHA-256")
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")

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
        dialogue_context_ids=(PRACTICE_CONTEXT_ID,),
        gateway_layout=gateway_layout,
    )
    patch = create_bps_patch(parent_rom, target_rom)
    if apply_bps_patch(parent_rom, patch) != target_rom:
        raise ValueError("V1-to-V2 BPS round-trip did not reproduce the target")
    return patch, hashlib.sha256(target_rom).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_file(
    parent_path: Path,
    source_path: Path,
    manifest_path: Path,
    opening_glyphs_path: Path,
    shared_glyphs_path: Path,
    practice_glyphs_path: Path,
    tile_candidate_path: Path,
    encoding_candidate_path: Path,
    context_plan_path: Path,
    context_encoding_path: Path,
    output_path: Path,
    overwrite: bool = False,
    gateway_layout: Literal["v2.1", "v2.2", "v2.3"] = "v2.1",
) -> tuple[Path, str, str]:
    parent_path = parent_path.resolve(strict=True)
    source_path = source_path.resolve(strict=True)
    input_paths = {
        manifest_path.resolve(strict=True),
        opening_glyphs_path.resolve(strict=True),
        shared_glyphs_path.resolve(strict=True),
        practice_glyphs_path.resolve(strict=True),
        tile_candidate_path.resolve(strict=True),
        encoding_candidate_path.resolve(strict=True),
        context_plan_path.resolve(strict=True),
        context_encoding_path.resolve(strict=True),
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
            manifest_path,
            opening_glyphs_path,
            shared_glyphs_path,
            practice_glyphs_path,
            tile_candidate_path,
            encoding_candidate_path,
            context_plan_path,
            context_encoding_path,
        )
    ]
    patch, target_digest = build_v2_practice_patch(
        parent_path.read_bytes(),
        source_path.read_bytes(),
        *inputs,
        gateway_layout=gateway_layout,
    )
    write_output(output_path, patch, overwrite)
    if output_path.read_bytes() != patch:
        raise OSError(f"written BPS patch differs from generated patch: {output_path}")
    return output_path, hashlib.sha256(patch).hexdigest(), target_digest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a versioned V1-to-V2 patch for the practice dialogue only."
    )
    parser.add_argument(
        "--parent",
        type=Path,
        default=ROOT / "roms" / "oni5_v1_opening_dialog.gb",
    )
    parser.add_argument("--source", type=Path, default=ROOT / "roms" / "oni5_original.gb")
    parser.add_argument("--text-manifest", type=Path, default=ROOT / "data" / "text_manifest.json")
    parser.add_argument(
        "--opening-glyphs",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs_oni5_bank04_01330d.json",
    )
    parser.add_argument("--shared-glyphs", type=Path, default=ROOT / "data" / "chinese_glyphs.json")
    parser.add_argument(
        "--practice-glyphs",
        type=Path,
        default=ROOT / "data" / "chinese_glyphs_oni5_bank24_01348f.json",
    )
    parser.add_argument(
        "--tile-candidate",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_candidate.json",
    )
    parser.add_argument(
        "--encoding-candidate",
        type=Path,
        default=ROOT / "data" / "translation_encoding_candidate.json",
    )
    parser.add_argument(
        "--context-plan",
        type=Path,
        default=ROOT / "data" / "tile_cache_plan_oni5_bank0c_030ee8.json",
    )
    parser.add_argument(
        "--context-encoding",
        type=Path,
        default=ROOT / "data" / "translation_encoding_oni5_bank0c_030ee8.json",
    )
    parser.add_argument("--gateway-layout", choices=("v2.1", "v2.2", "v2.3"), default="v2.1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        output_path = args.output
        if output_path is None:
            version_suffix = args.gateway_layout[1:].replace(".", "_")
            output_path = ROOT / "roms" / f"oni5_v{version_suffix}_opening_practice.bps"
        output, patch_digest, target_digest = build_file(
            args.parent,
            args.source,
            args.text_manifest,
            args.opening_glyphs,
            args.shared_glyphs,
            args.practice_glyphs,
            args.tile_candidate,
            args.encoding_candidate,
            args.context_plan,
            args.context_encoding,
            output_path,
            args.overwrite,
            args.gateway_layout,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    version_label = args.gateway_layout.upper()
    print(f"Wrote V1-to-{version_label} BPS patch: {output} ({output.stat().st_size} bytes)")
    print(f"BPS SHA-256: {patch_digest}")
    print(f"{version_label} target SHA-256: {target_digest}")


if __name__ == "__main__":
    main()
