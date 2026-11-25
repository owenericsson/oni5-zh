"""Hide the observed status redraw until the Chinese page is ready."""
import argparse
import hashlib
import json

from scripts import build_v2_6_9_status_probe as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.rom_checksums import update_checksums, verify_rom

ROOT = previous.ROOT
PARENT_SHA256 = "5da692b9debd72eccbaf269084392e3540a40b8e26a338e3e7223015f93ba0de"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_10_status_timing.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_10_status_timing.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.10-status-timing.json"
FRAME_CALL = 0x89CF
BACKUP = 0x9E40
FAILURE_MARKER = 0x95
SNAPSHOT_SIZE = 0x240


def _replace_at(component: bytearray, start: int, expected: bytes, replacement: bytes) -> None:
    if len(expected) != len(replacement) or component[start:start + len(expected)] != expected:
        raise ValueError(f"unexpected previous component bytes at +${start:04X}")
    component[start:start + len(expected)] = replacement


def _replace_all(component: bytearray, expected: bytes, replacement: bytes, count: int) -> None:
    if len(expected) != len(replacement) or component.count(expected) != count:
        raise ValueError(f"unexpected number of occurrences of {expected.hex(' ')}")
    component[:] = component.replace(expected, replacement)


def _wait_vblank(code: previous.Code, label: str) -> None:
    code.label(f"{label}_active")
    code.emit(bytes.fromhex("F0 44 FE 90"))
    code.address(0xD2, f"{label}_active")
    code.label(f"{label}_vblank")
    code.emit(bytes.fromhex("F0 44 FE 90"))
    code.address(0xDA, f"{label}_vblank")


def build_components(parent_v268: bytes) -> tuple[bytes, dict[str, int]]:
    labels, patterns = previous.compile_labels(parent_v268)
    original, locations = previous.build_components(labels, patterns)
    component = bytearray(original)
    base = previous._bank11_address(previous.COMPONENT_START)
    code = previous.Code(base + len(component))
    code.labels.update(locations)
    code.label("mask_dispatch")
    code.emit(bytes.fromhex("F5 C5 D5 E5 F8 0E 2A FE D2"))
    code.address(0xC2, "previous_dispatch")
    code.emit(bytes.fromhex("7E FE 49"))
    code.address(0xC2, "previous_dispatch")
    code.emit(bytes.fromhex("E1 D1 C1 F1"))
    code.label("mask_enter")
    code.emit(bytes.fromhex("F5 C5 D5 E5 F3 FA F2 C4 B7"))
    code.address(0xC2, "mask_skip")
    for register, expected in ((0x40, 0xC7), (0x42, 0x00), (0x43, 0x08),
                               (0x4A, 0x88), (0x4B, 0x07)):
        code.emit(bytes((0xF0, register, 0xFE, expected)))
        code.address(0xC2, "mask_fail")
    code.emit(bytes.fromhex("21 00 9C 01 00 04"))
    code.label("check_window_map")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE CD"))
    code.address(0xC2, "mask_fail")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "check_window_map")
    code.emit(bytes.fromhex("21 00 98 01 00 04"))
    code.label("check_visible_tiles")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE 20"))
    code.address(0xDA, "visible_tile_safe")
    code.emit(bytes.fromhex("FE 36"))
    code.address(0xDA, "mask_fail")
    code.label("visible_tile_safe")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "check_visible_tiles")
    for row in range(18):
        code.emit(previous._copy(0x9801 + row * 32, 0x9C00 + row * 32, 20))
    code.emit(bytes.fromhex("AF E0 4A"))
    _wait_vblank(code, "mask_open")
    code.emit(bytes.fromhex("3E E7 E0 40"))
    code.address(0xC3, "mask_skip")
    code.label("mask_fail")
    code.emit(bytes((0x3E, FAILURE_MARKER)) + bytes.fromhex("EA F2 C4"))
    code.label("mask_skip")
    code.emit(bytes.fromhex("E1 D1 C1 F1"))
    code.emit(previous._rst_call(1, 0x1A89))
    code.emit(bytes.fromhex("C9"))
    code.label("previous_dispatch")
    code.emit(bytes.fromhex("E1 D1 C1 F1 F5 C5 D5"))
    code.address(0xC3, "previous_dispatch_tail")
    code.labels["previous_dispatch_tail"] = locations["dispatch"] + 3

    code.label("unmask")
    code.emit(bytes.fromhex("F0 40 FE E7"))
    code.address(0xC2, "unmask_done")
    _wait_vblank(code, "mask_close")
    code.emit(bytes.fromhex("3E C7 E0 40 3E 88 E0 4A"))
    code.emit(bytes.fromhex("21 00 9C 01 40 02 3E CD CD 00 05"))
    code.label("unmask_done")
    code.emit(bytes.fromhex("E1 D1 C1 F1 C9"))

    code.label("restore_dispatch")
    code.emit(bytes.fromhex("F5 C5 D5 E5 F3 FA F2 C4 FE") + bytes((FAILURE_MARKER,)))
    code.address(0xC2, "previous_restore")
    code.emit(bytes.fromhex("AF EA F2 C4 E1 D1 C1 F1 C9"))
    code.label("previous_restore")
    code.emit(bytes.fromhex("E1 D1 C1 F1 F5 C5 D5"))
    code.address(0xC3, "previous_restore_tail")
    code.labels["previous_restore_tail"] = locations["restore"] + 3

    extension = code.finish()
    if previous.COMPONENT_START + len(component) + len(extension) > previous.COMPONENT_END:
        raise ValueError("status timing extension exceeds bank $11")
    _replace_all(component, bytes.fromhex("21 00 9C"), b"\x21" + BACKUP.to_bytes(2, "little"), 3)
    _replace_all(component, bytes.fromhex("11 00 9C"), b"\x11" + BACKUP.to_bytes(2, "little"), 1)
    _replace_all(component, bytes.fromhex("FE C7"), bytes.fromhex("FE E7"), 1)
    for name, old, target in (
        ("dispatch", bytes.fromhex("F5 C5 D5"), "mask_dispatch"),
        ("draw_done", bytes.fromhex("E1 D1 C1"), "unmask"),
        ("restore", bytes.fromhex("F5 C5 D5"), "restore_dispatch"),
    ):
        _replace_at(component, locations[name] - base, old,
                    b"\xC3" + code.labels[target].to_bytes(2, "little"))
    return bytes(component) + extension, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.9 parent ROM failed hash or checksum verification")
    v268 = previous.previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(v268).hexdigest() != previous.PARENT_SHA256:
        raise ValueError("V2.6.8 source for component reconstruction has an unexpected hash")
    labels, patterns = previous.compile_labels(v268)
    old_component, _ = previous.build_components(labels, patterns)
    component, locations = build_components(v268)
    expected_frame = bytes.fromhex("F5 E5 21 89 1A 3E 01 EF")
    replacement_frame = bytes.fromhex("CD 73 7E 00 00 00 00 00")
    old = old_component + bytes((0xFF,)) * (len(component) - len(old_component))
    changes = ((FRAME_CALL, expected_frame, replacement_frame),
               (previous.COMPONENT_START, old, component))
    result = bytearray(parent)
    for offset, expected, replacement in changes:
        for start in (offset, offset + MBC1_MIRROR_OFFSET):
            if parent[start:start + len(expected)] != expected:
                raise ValueError(f"unexpected parent or mirror bytes at ${start:06X}")
            result[start:start + len(replacement)] = replacement
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("status timing probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("status timing probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.10-status-timing",
        "parent_version": {"version_id": "V2.6.9-status-probe", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental: mask initial status redraw only in the observed village and current character.",
            "An exclamation mark indicates that scene-specific safety checks did not pass.",
            "Skill-window return, other characters and scenes are not covered by the new timing change.",
        ]},
        "implementation": {"bank11": {name: f"0x{value:04X}" for name, value in locations.items()}},
    }
    return result, patch, version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        target, patch, version = build()
        outputs = (OUTPUT_ROM, OUTPUT_PATCH, OUTPUT_VERSION)
        if not args.overwrite and any(path.exists() for path in outputs):
            raise FileExistsError("status timing output exists; pass --overwrite to replace it")
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
