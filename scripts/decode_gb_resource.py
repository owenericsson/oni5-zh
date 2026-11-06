"""Decode the game's bitstream-compressed ROM resources into raw bytes."""
import argparse
from pathlib import Path

ROM_BANK_SIZE = 0x4000
ROMX_START = 0x4000
ROMX_END = 0x8000


def _romx_offset(rom: bytes, bank: int, address: int) -> int:
    if len(rom) % ROM_BANK_SIZE:
        raise ValueError("ROM size must be a multiple of 0x4000 bytes")
    bank_count = len(rom) // ROM_BANK_SIZE
    if not 0 <= bank < bank_count:
        raise ValueError(f"ROM bank is outside the file: {bank:#x}")
    if not ROMX_START <= address < ROMX_END:
        raise ValueError(f"ROMX address is outside 0x4000-0x7FFF: {address:#x}")
    return bank * ROM_BANK_SIZE + address - ROMX_START


def _read_romx(rom: bytes, bank: int, address: int) -> int:
    return rom[_romx_offset(rom, bank, address)]


class _BitReader:
    def __init__(self, rom: bytes, bank: int, address: int):
        self.rom = rom
        self.bank = bank
        self.address = address
        self.buffer = _read_romx(rom, bank, address)
        self.bits_read = 0

    def read_bit(self) -> int:
        if self.bits_read == 8:
            self.address += 1
            self.buffer = _read_romx(self.rom, self.bank, self.address)
            self.bits_read = 0
        bit = self.buffer >> 7
        self.buffer = (self.buffer << 1) & 0xFF
        self.bits_read += 1
        return bit

    def read_bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.read_bit()
        return value


def _read_copy_length(reader: _BitReader) -> int:
    if reader.read_bit():
        if reader.read_bit():
            return reader.read_bits(6) + 0x15
        return reader.read_bits(4) + 5
    if reader.read_bit():
        return reader.read_bits(2) + 1
    return 0


def _backref_bit_count(output_length: int) -> int:
    distance_minus_one = (output_length - 1) & 0xFFFF
    return max(1, distance_minus_one.bit_length())


def _read_backref_source(reader: _BitReader, output: bytearray) -> int:
    offset = reader.read_bits(_backref_bit_count(len(output)))
    source = len(output) - offset - 1
    if source < 0 or source >= len(output):
        raise ValueError("compressed stream refers before the decoded output")
    return source


def _copy_backref(output: bytearray, source: int, count: int, limit: int) -> None:
    if count > limit - len(output):
        raise ValueError("backreference exceeds the requested output length")
    for _ in range(count):
        if source < 0 or source >= len(output):
            raise ValueError("compressed stream refers before the decoded output")
        output.append(output[source])
        source += 1


def decode_resource(
    rom: bytes,
    bank: int,
    descriptor_address: int,
    output_length: int,
) -> bytes:
    """Decode one ROMX resource descriptor to its requested uncompressed size."""
    if output_length <= 0 or output_length > 0xFFFF:
        raise ValueError("output length must be between 1 and 0xFFFF bytes")

    descriptor = _read_romx(rom, bank, descriptor_address)
    control_address = descriptor_address + 1
    if descriptor & 0x80:
        relative_offset = ((descriptor & 0x7F) << 8) | _read_romx(
            rom, bank, control_address
        )
        control_address += 1
    else:
        relative_offset = descriptor

    payload_address = control_address + relative_offset + 1
    _romx_offset(rom, bank, payload_address)
    reader = _BitReader(rom, bank, control_address)
    output = bytearray()

    while len(output) < output_length:
        if reader.read_bit() == 0:
            source = _read_backref_source(reader, output)
            count = _read_copy_length(reader) + 3
            _copy_backref(output, source, count, output_length)
        elif reader.read_bit() == 0:
            source = _read_backref_source(reader, output)
            _copy_backref(output, source, 2, output_length)
        else:
            count = _read_copy_length(reader) + 1
            if count > output_length - len(output):
                raise ValueError("literal run exceeds the requested output length")
            for _ in range(count):
                output.append(_read_romx(rom, bank, payload_address))
                payload_address += 1

    return bytes(output)


def _parse_integer(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decode a bitstream-compressed ROM resource to a binary file."
    )
    parser.add_argument("rom", type=Path, help="input ROM file")
    parser.add_argument("--bank", type=_parse_integer, required=True, help="ROMX bank")
    parser.add_argument(
        "--descriptor",
        type=_parse_integer,
        required=True,
        help="descriptor CPU address in the selected ROMX bank",
    )
    parser.add_argument(
        "--length",
        type=_parse_integer,
        required=True,
        help="uncompressed output length",
    )
    parser.add_argument("--output", type=Path, required=True, help="output binary path")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace the output file if it already exists",
    )
    args = parser.parse_args()

    try:
        rom_path = args.rom.resolve()
        output_path = args.output.resolve()
        if rom_path == output_path:
            raise ValueError("output path must not overwrite the input ROM")
        if output_path.exists() and not args.overwrite:
            raise ValueError(f"output file already exists: {output_path}")
        decoded = decode_resource(
            args.rom.read_bytes(),
            args.bank,
            args.descriptor,
            args.length,
        )
        output_path.write_bytes(decoded)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"decoded {len(decoded)} bytes to {output_path}")


if __name__ == "__main__":
    main()
