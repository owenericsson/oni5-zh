"""Build a scene-limited status-details translation probe from V2.6.8."""
import argparse
import hashlib
import json

from scripts import build_v2_6_8_menu as previous
from scripts.apply_bps_patch import apply_bps_patch, create_bps_patch
from scripts.build_menu_pilot import MBC1_MIRROR_OFFSET
from scripts.build_v2_6_4_dialogue import ROOT
from scripts.rom_checksums import update_checksums, verify_rom

PARENT_SHA256 = "4134619459f2b779d864ef7796b5c0eff995ac4bd4fcf204e9ff528371dad38c"
OUTPUT_ROM = ROOT / "roms/oni5_v2_6_9_status_probe.gb"
OUTPUT_PATCH = ROOT / "roms/oni5_v2_6_9_status_probe.bps"
OUTPUT_VERSION = ROOT / "versions/V2.6.9-status-probe.json"
STATUS_CALL = 0x8B26
EXIT_CALLS = ((0x8B7B, 0x7A30), (0x8B96, 0x7ACB))
EXIT_WRAPPER = 0xBE73
COMPONENT_START = 0x47060
COMPONENT_END = 0x48000
MARKER = 0x94
FIRST_TILE = 0x20
BACKUP = 0x9C00
GLYPH_VRAM = 0x9200
MAP_START = 0x9800
MAP_SIZE = 0x400
BG_BLANK = 0xCD


class Code:
    def __init__(self, base: int):
        self.base = base
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str]] = []

    def emit(self, data: bytes) -> None:
        self.data.extend(data)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate code label {name}")
        self.labels[name] = self.base + len(self.data)

    def address(self, opcode: int, name: str) -> None:
        self.emit(bytes((opcode, 0, 0)))
        self.fixups.append((len(self.data) - 2, name))

    def finish(self) -> bytes:
        for offset, name in self.fixups:
            if name not in self.labels:
                raise ValueError(f"missing code label {name}")
            self.data[offset:offset + 2] = self.labels[name].to_bytes(2, "little")
        return bytes(self.data)


def _bank11_address(offset: int) -> int:
    if not 0x44000 <= offset < 0x48000:
        raise ValueError("component is outside bank $11")
    return 0x4000 + offset - 0x44000


def _rst_call(bank: int, target: int) -> bytes:
    return bytes.fromhex("F5 E5 21") + target.to_bytes(2, "little") + bytes((0x3E, bank, 0xEF))


def _copy(source: int, destination: int, size: int) -> bytes:
    return (b"\x21" + source.to_bytes(2, "little")
            + b"\x11" + destination.to_bytes(2, "little")
            + b"\x01" + size.to_bytes(2, "little") + bytes.fromhex("CD 21 05"))


def compile_labels(parent: bytes) -> tuple[list[tuple[int, int, bytes, tuple[int, ...]]], bytes]:
    manifest = json.loads((ROOT / "data/status_text_manifest.json").read_text(encoding="utf-8"))
    asset = json.loads((ROOT / "data/chinese_glyphs_oni5_status.json").read_text(encoding="utf-8"))
    if manifest["parent_rom_sha256"] != PARENT_SHA256:
        raise ValueError("status manifest has an unexpected parent")
    glyphs = asset["glyphs"]
    characters = [entry["character"] for entry in glyphs]
    required = {character for record in manifest["records"]
                for segment in record["translation"]["segments"] for character in segment["text"]}
    if len(characters) != 22 or len(set(characters)) != len(characters) or set(characters) != required:
        raise ValueError("status glyph asset does not exactly cover the translations")
    mapping = {character: FIRST_TILE + index for index, character in enumerate(characters)}
    patterns = b"".join(bytes.fromhex(entry["tile_2bpp_hex"]) for entry in glyphs)
    if len(patterns) != 22 * 16:
        raise ValueError("status glyph patterns must each be 16 bytes")
    labels = []
    occupied: set[int] = set()
    for record in manifest["records"]:
        source = record["source"]
        start, end = int(source["start"], 16), int(source["end_exclusive"], 16)
        expected = bytes.fromhex(source["raw_hex"])
        text = record["translation"]["segments"][0]["text"]
        if record["translation"]["status"] != "confirmed" or len(record["translation"]["segments"]) != 1:
            raise ValueError(f"{record['id']}: translation is not confirmed")
        if (end - start != len(expected) or len(text) > len(expected)
                or parent[start:end] != expected
                or parent[start + MBC1_MIRROR_OFFSET:end + MBC1_MIRROR_OFFSET] != expected):
            raise ValueError(f"{record['id']}: unexpected source or label width")
        if occupied.intersection(range(start, end)):
            raise ValueError(f"{record['id']}: overlapping source labels")
        occupied.update(range(start, end))
        column, row = record["position"]["column"], record["position"]["row"]
        if not (0 <= column < 32 and 1 <= row < 32 and column + len(expected) <= 32):
            raise ValueError(f"{record['id']}: invalid status position")
        tiles = bytes(mapping[character] for character in text)
        voiced = tuple(index for index, value in enumerate(expected) if 0x60 <= value <= 0x7B)
        labels.append((column, row, tiles + bytes((BG_BLANK,)) * (len(expected) - len(tiles)), voiced))
    if len(labels) != 12:
        raise ValueError("expected twelve status labels")
    return labels, patterns


def build_components(
    labels: list[tuple[int, int, bytes, tuple[int, ...]]], patterns: bytes
) -> tuple[bytes, dict[str, int]]:
    code = Code(_bank11_address(COMPONENT_START))
    code.label("dispatch")
    code.emit(bytes.fromhex("F5 C5 D5 E5 F8 0E 2A FE 29"))
    code.address(0xCA, "entry_status")
    code.emit(bytes.fromhex("FE 7E"))
    code.address(0xCA, "exit_status")
    code.emit(bytes.fromhex("FE 99"))
    code.address(0xC2, "bad_exit")
    code.emit(bytes.fromhex("7E FE 4B"))
    code.address(0xC2, "bad_exit")
    code.emit(bytes.fromhex("E1 D1 C1 F1"))
    code.emit(_rst_call(2, 0x7ACB))
    code.address(0xC3, "restore")
    code.label("entry_status")
    code.emit(bytes.fromhex("7E FE 4B"))
    code.address(0xC2, "bad_exit")
    code.emit(bytes.fromhex("E1 D1 C1 F1"))
    code.label("draw")
    code.emit(_rst_call(1, 0x1934))
    code.emit(bytes.fromhex("F5 C5 D5 E5 F3 FA F2 C4 FE") + bytes((MARKER,)))
    code.address(0xCA, "draw_ready")
    code.emit(bytes.fromhex("B7"))
    code.address(0xC2, "draw_error")
    code.emit(bytes.fromhex("F0 40 FE C7"))
    code.address(0xC2, "draw_error")
    code.emit(bytes.fromhex("21 00 9C 01 60 01"))
    code.label("check_backup")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE CD"))
    code.address(0xC2, "draw_error")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "check_backup")
    code.emit(bytes.fromhex("21 00 98 01 00 04"))
    code.label("check_map")
    code.emit(bytes.fromhex("F0 41 E6 02 20 FA 2A FE 20"))
    code.address(0xDA, "map_safe")
    code.emit(bytes.fromhex("FE 36"))
    code.address(0xDA, "draw_error")
    code.label("map_safe")
    code.emit(bytes.fromhex("0B 78 B1"))
    code.address(0xC2, "check_map")
    code.emit(_copy(GLYPH_VRAM, BACKUP, len(patterns)))
    code.address(0x21, "patterns")
    code.emit(b"\x11" + GLYPH_VRAM.to_bytes(2, "little")
              + b"\x01" + len(patterns).to_bytes(2, "little") + bytes.fromhex("CD 21 05"))
    code.emit(bytes((0x3E, MARKER)) + bytes.fromhex("EA F2 C4"))
    code.label("draw_ready")
    code.emit(bytes.fromhex("21 00 00"))
    for column, row, tiles, voiced in labels:
        code.emit(bytes((0x11, column, row)))
        for index, tile in enumerate(tiles):
            if index in voiced:
                code.emit(bytes.fromhex("3E CD 15 CD E5 19 14"))
            code.emit(bytes((0x3E, tile)) + bytes.fromhex("CD E5 19 1C"))
    code.address(0xC3, "draw_done")
    code.label("draw_error")
    code.emit(bytes.fromhex("21 00 00 11 0C 01 3E CB CD E5 19"))
    code.label("draw_done")
    code.emit(bytes.fromhex("E1 D1 C1 F1 C9"))

    code.label("exit_status")
    code.emit(bytes.fromhex("7E FE 4B"))
    code.address(0xC2, "bad_exit")
    code.emit(bytes.fromhex("E1 D1 C1 F1"))
    code.emit(_rst_call(2, 0x7A30))
    code.address(0xC3, "restore")
    code.label("bad_exit")
    code.emit(bytes.fromhex("E1 D1 C1 F1 FF"))
    code.label("restore")
    code.emit(bytes.fromhex("F5 C5 D5 E5 F3 FA F2 C4 FE") + bytes((MARKER,)))
    code.address(0xC2, "restore_done")
    code.emit(_copy(BACKUP, GLYPH_VRAM, len(patterns)))
    code.emit(bytes.fromhex("21 00 9C 01 60 01 3E CD CD 00 05 AF EA F2 C4"))
    code.label("restore_done")
    code.emit(bytes.fromhex("E1 D1 C1 F1 C9"))
    code.label("patterns")
    code.emit(patterns)
    result = code.finish()
    if COMPONENT_START + len(result) > COMPONENT_END:
        raise ValueError("status components exceed bank $11 free space")
    return result, code.labels


def build() -> tuple[bytes, bytes, dict[str, object]]:
    parent = previous.OUTPUT_ROM.read_bytes()
    if hashlib.sha256(parent).hexdigest() != PARENT_SHA256 or not verify_rom(parent).passed:
        raise ValueError("V2.6.8 parent ROM failed hash or checksum verification")
    labels, patterns = compile_labels(parent)
    component, locations = build_components(labels, patterns)
    expected_call = bytes.fromhex("F5 E5 21 34 19 3E 01 EF")
    wrapper = bytes.fromhex("F5 E5 21") + locations["dispatch"].to_bytes(2, "little") + bytes.fromhex("3E 11 EF FB C9")
    changes = [
        (STATUS_CALL, expected_call, bytes.fromhex("CD 73 7E 00 00 00 00 00")),
        (EXIT_WRAPPER, bytes((0xFF,)) * len(wrapper), wrapper),
        (COMPONENT_START, bytes((0xFF,)) * len(component), component),
    ]
    for offset, target in EXIT_CALLS:
        changes.append((offset, b"\xCD" + target.to_bytes(2, "little"), bytes.fromhex("CD 73 7E")))
    result = bytearray(parent)
    for offset, expected, replacement in changes:
        mirror = offset + MBC1_MIRROR_OFFSET
        if parent[offset:offset + len(expected)] != expected or parent[mirror:mirror + len(expected)] != expected:
            raise ValueError(f"unexpected parent or mirror bytes at ${offset:06X}")
        result[offset:offset + len(replacement)] = replacement
        result[mirror:mirror + len(replacement)] = replacement
    result = update_checksums(result)
    if len(result) != len(parent) or not verify_rom(result).passed:
        raise ValueError("status probe failed size or checksum verification")
    patch = create_bps_patch(parent, result)
    if apply_bps_patch(parent, patch) != result:
        raise ValueError("status probe BPS round-trip failed")
    version = {
        "schema_version": 1, "version_id": "V2.6.9-status-probe",
        "parent_version": {"version_id": "V2.6.8-status-fix", "sha256": PARENT_SHA256},
        "target_rom": {"path": f"../roms/{OUTPUT_ROM.name}", "sha256": hashlib.sha256(result).hexdigest()},
        "patch": {"path": f"../roms/{OUTPUT_PATCH.name}", "sha256": hashlib.sha256(patch).hexdigest()},
        "runtime_validation": {"status": "pending-sameboy", "limitations": [
            "Experimental: use only the observed village, current character, and empty skill window.",
            "A visible exclamation mark next to the level indicates the VRAM safety checks failed.",
            "Other characters, learned skills, scenes, transitions, and dynamic tile updates are unverified.",
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
            raise FileExistsError("status probe output exists; pass --overwrite to replace it")
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
