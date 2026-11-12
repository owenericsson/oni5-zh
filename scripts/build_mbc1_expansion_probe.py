"""Build a guarded 512 KiB MBC1 bank-switch probe ROM."""
import argparse
import hashlib
from pathlib import Path

if __package__:
    from .build_rom import write_output
    from .rom_checksums import update_checksums, verify_rom
else:
    from build_rom import write_output
    from rom_checksums import update_checksums, verify_rom

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCE_SHA256 = "870f83f781c103925f206f35b71cdda6a0493e5b4c70d70b49cade145c35f127"
SOURCE_SIZE = 0x40000
EXPANDED_SIZE = 0x80000
MBC1_RAM_BATTERY_TYPE = 0x03
SOURCE_ROM_SIZE_CODE = 0x03
EXPANDED_ROM_SIZE_CODE = 0x04
GATEWAY_OFFSET = 0x1803
GATEWAY_EXPECTED = bytes.fromhex("FE 60 30 0E")
GATEWAY_PATCH = bytes.fromhex("C3 A0 00 00")
ENTRY_OFFSET = 0x00A0
ENTRY_EXPECTED = bytes([0xFF]) * 0x20
ENTRY_CODE = bytes.fromhex(
    "F5 FA AA FF FE 0C 20 46 FA AE FF FE 0E 20 3F FA AD FF "
    "FE 34 20 38 C3 E0 00"
)
POSTLUDE_OFFSET = 0x00E0
POSTLUDE_EXPECTED = bytes([0xFF]) * 0x20
POSTLUDE_CODE = bytes.fromhex(
    "FA AA FF EA F1 C4 3E 10 EA 00 20 CD 00 40 F1 FE 60 "
    "D2 15 18 C3 07 18"
)
BANK_SWITCH_HELPER_OFFSET = SOURCE_SIZE
BANK_SWITCH_HELPER = bytes.fromhex(
    "FA 00 41 EA F0 C4 C3 F7 00"
)
BANK_SWITCH_MARKER_OFFSET = SOURCE_SIZE + 0x0100
BANK_SWITCH_MARKER = 0xA5
BANK_RESTORE_STUB_OFFSET = 0x00F7
BANK_RESTORE_STUB_EXPECTED = bytes([0xFF]) * 9
BANK_RESTORE_STUB = bytes.fromhex("FA F1 C4 EA 00 20 C3 B9 00")
BANK_RESTORED_READBACK_OFFSET = 0x00B9
BANK_RESTORED_READBACK_EXPECTED = bytes([0xFF]) * 7
BANK_RESTORED_READBACK = bytes.fromhex("FA 33 4E EA F2 C4 C9")


def build_expansion_probe(source_rom: bytes) -> bytes:
    if len(source_rom) != SOURCE_SIZE:
        raise ValueError(f"source ROM must be exactly {SOURCE_SIZE} bytes")
    verification = verify_rom(source_rom)
    if not verification.passed:
        raise ValueError("source ROM failed size or checksum verification")
    if source_rom[0x147] != MBC1_RAM_BATTERY_TYPE:
        raise ValueError("source ROM must use the MBC1+RAM+Battery cartridge type")
    if source_rom[0x148] != SOURCE_ROM_SIZE_CODE:
        raise ValueError("source ROM must declare a 256 KiB ROM size")
    if source_rom[GATEWAY_OFFSET:GATEWAY_OFFSET + len(GATEWAY_EXPECTED)] != GATEWAY_EXPECTED:
        raise ValueError("bank-switch probe gateway bytes do not match the expected source")
    if source_rom[ENTRY_OFFSET:ENTRY_OFFSET + len(ENTRY_EXPECTED)] != ENTRY_EXPECTED:
        raise ValueError("bank-switch probe entry area is not entirely unused")
    if source_rom[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_EXPECTED)] != POSTLUDE_EXPECTED:
        raise ValueError("bank-switch probe postlude area is not entirely unused")
    if source_rom[BANK_RESTORE_STUB_OFFSET:BANK_RESTORE_STUB_OFFSET + len(BANK_RESTORE_STUB_EXPECTED)] != (
        BANK_RESTORE_STUB_EXPECTED
    ):
        raise ValueError("bank-switch restore stub area is not entirely unused")
    if source_rom[
        BANK_RESTORED_READBACK_OFFSET:
        BANK_RESTORED_READBACK_OFFSET + len(BANK_RESTORED_READBACK_EXPECTED)
    ] != BANK_RESTORED_READBACK_EXPECTED:
        raise ValueError("bank-switch readback area is not entirely unused")
    if len(ENTRY_CODE) > len(ENTRY_EXPECTED):
        raise ValueError("bank-switch probe entry code exceeds its reserved area")
    if len(POSTLUDE_CODE) > len(POSTLUDE_EXPECTED):
        raise ValueError("bank-switch probe postlude exceeds its reserved area")

    expanded = bytearray([0xFF]) * EXPANDED_SIZE
    expanded[:SOURCE_SIZE] = source_rom
    expanded[GATEWAY_OFFSET:GATEWAY_OFFSET + len(GATEWAY_PATCH)] = GATEWAY_PATCH
    expanded[ENTRY_OFFSET:ENTRY_OFFSET + len(ENTRY_CODE)] = ENTRY_CODE
    expanded[POSTLUDE_OFFSET:POSTLUDE_OFFSET + len(POSTLUDE_CODE)] = POSTLUDE_CODE
    expanded[BANK_RESTORE_STUB_OFFSET:BANK_RESTORE_STUB_OFFSET + len(BANK_RESTORE_STUB)] = (
        BANK_RESTORE_STUB
    )
    expanded[
        BANK_RESTORED_READBACK_OFFSET:
        BANK_RESTORED_READBACK_OFFSET + len(BANK_RESTORED_READBACK)
    ] = BANK_RESTORED_READBACK
    expanded[BANK_SWITCH_HELPER_OFFSET:BANK_SWITCH_HELPER_OFFSET + len(BANK_SWITCH_HELPER)] = (
        BANK_SWITCH_HELPER
    )
    expanded[BANK_SWITCH_MARKER_OFFSET] = BANK_SWITCH_MARKER
    expanded[0x148] = EXPANDED_ROM_SIZE_CODE

    result = update_checksums(expanded)
    result_verification = verify_rom(result)
    if not result_verification.passed:
        raise ValueError("expanded probe failed size or checksum verification")
    return result


def build_probe_file(
    source_path: Path,
    output_path: Path,
    overwrite: bool = False,
) -> tuple[Path, int, str]:
    source = source_path.resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"source ROM is not a file: {source}")
    output = output_path.resolve()
    if output == source:
        raise ValueError("output ROM path must differ from the source ROM path")
    if not output.parent.is_dir():
        raise ValueError(f"output directory does not exist: {output.parent}")
    if output.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {output}; pass --overwrite to replace it")

    source_rom = source.read_bytes()
    source_digest = hashlib.sha256(source_rom).hexdigest()
    if source_digest != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "source ROM SHA-256 mismatch: "
            f"expected {EXPECTED_SOURCE_SHA256}, found {source_digest}"
        )
    probe_rom = build_expansion_probe(source_rom)
    write_output(output, probe_rom, overwrite)

    written = output.read_bytes()
    if written != probe_rom:
        raise OSError(f"written probe does not match generated ROM: {output}")
    return output, len(probe_rom), hashlib.sha256(probe_rom).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a separate 512 KiB ROM that probes MBC1 bank-0x10 access."
    )
    parser.add_argument(
        "source_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_original.gb",
        help="verified 256 KiB MBC1 source ROM",
    )
    parser.add_argument(
        "output_rom",
        nargs="?",
        type=Path,
        default=ROOT / "roms" / "oni5_t14c5_mbc1_return_readback_probe.gb",
        help="new expanded probe ROM output path",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output")
    args = parser.parse_args()

    try:
        output, size, digest = build_probe_file(
            args.source_rom,
            args.output_rom,
            args.overwrite,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Wrote {output} ({size} bytes)")
    print(f"SHA-256: {digest}")
    print("Probe results are recorded at WRAM $C4F0-$C4F2.")


if __name__ == "__main__":
    main()
