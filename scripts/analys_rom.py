from pathlib import Path
import hashlib
import sys

if __package__:
    from .rom_checksums import ROM_SIZE_BYTES, verify_rom
else:
    from rom_checksums import ROM_SIZE_BYTES, verify_rom


def analyze_rom(path):
    data = Path(path).read_bytes()

    print("File:", path)
    print("Size:", len(data))
    print("SHA-256:", hashlib.sha256(data).hexdigest())
    print("MD5:", hashlib.md5(data).hexdigest())

    if len(data) < 0x150:
        print("Error: ROM too small")
        return False

    title = data[0x134:0x144]
    verification = verify_rom(data)

    print("\n--- Header ---")
    print("Title raw:", title.hex(" "))
    print("Title ASCII:",
          title.decode("ascii", errors="replace"))

    print("Cartridge type:",
          hex(data[0x147]))

    size_code = data[0x148]
    expected_size = ROM_SIZE_BYTES.get(size_code)
    print("ROM size code:", hex(size_code))
    print(
        "Expected ROM size:",
        f"{expected_size} bytes" if expected_size is not None else "unknown size code",
    )
    print("ROM size matches header:", verification.size_matches)

    print("RAM size code:",
          hex(data[0x149]))

    print("Header checksum:",
          hex(verification.header_checksum_stored))
    print("Calculated header checksum:", hex(verification.header_checksum_calculated))
    print("Header checksum matches:", verification.header_checksum_matches)
    print("Global checksum:", f"{verification.global_checksum_stored:04X}")
    print("Calculated global checksum:", f"{verification.global_checksum_calculated:04X}")
    print("Global checksum matches:", verification.global_checksum_matches)
    print("Verification passed:", verification.passed)
    return verification.passed

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python analyze_rom.py ROM_FILE")
        sys.exit(1)

    sys.exit(0 if analyze_rom(sys.argv[1]) else 1)