"""Game Boy ROM size and checksum helpers."""
from dataclasses import dataclass


ROM_SIZE_BYTES = {
    0x00: 0x8000,
    0x01: 0x10000,
    0x02: 0x20000,
    0x03: 0x40000,
    0x04: 0x80000,
    0x05: 0x100000,
    0x06: 0x200000,
    0x07: 0x400000,
    0x08: 0x800000,
    0x52: 72 * 0x4000,
    0x53: 80 * 0x4000,
    0x54: 96 * 0x4000,
}


@dataclass(frozen=True)
class RomVerification:
    actual_size: int
    expected_size: int | None
    size_matches: bool
    header_checksum_stored: int
    header_checksum_calculated: int
    header_checksum_matches: bool
    global_checksum_stored: int
    global_checksum_calculated: int
    global_checksum_matches: bool

    @property
    def passed(self) -> bool:
        return (
            self.size_matches
            and self.header_checksum_matches
            and self.global_checksum_matches
        )


def calculate_header_checksum(rom: bytes | bytearray) -> int:
    if len(rom) < 0x150:
        raise ValueError("ROM is too small to contain the complete Game Boy header")
    checksum = 0
    for byte in rom[0x134:0x14D]:
        checksum = (checksum - byte - 1) & 0xFF
    return checksum


def calculate_global_checksum(rom: bytes | bytearray) -> int:
    if len(rom) < 0x150:
        raise ValueError("ROM is too small to contain the complete Game Boy header")
    return (sum(rom[:0x14E]) + sum(rom[0x150:])) & 0xFFFF


def update_checksums(rom: bytes | bytearray) -> bytes:
    if len(rom) < 0x150:
        raise ValueError("ROM is too small to contain the complete Game Boy header")
    updated = bytearray(rom)
    updated[0x14D] = calculate_header_checksum(updated)
    updated[0x14E:0x150] = calculate_global_checksum(updated).to_bytes(2, "big")
    return bytes(updated)


def verify_rom(rom: bytes | bytearray) -> RomVerification:
    if len(rom) < 0x150:
        raise ValueError("ROM is too small to contain the complete Game Boy header")

    size_code = rom[0x148]
    expected_size = ROM_SIZE_BYTES.get(size_code)
    header_stored = rom[0x14D]
    header_calculated = calculate_header_checksum(rom)
    global_stored = int.from_bytes(rom[0x14E:0x150], "big")
    global_calculated = calculate_global_checksum(rom)
    return RomVerification(
        actual_size=len(rom),
        expected_size=expected_size,
        size_matches=expected_size == len(rom),
        header_checksum_stored=header_stored,
        header_checksum_calculated=header_calculated,
        header_checksum_matches=header_stored == header_calculated,
        global_checksum_stored=global_stored,
        global_checksum_calculated=global_calculated,
        global_checksum_matches=global_stored == global_calculated,
    )
