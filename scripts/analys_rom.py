from pathlib import Path
import hashlib
import sys

def analyze_rom(path):
    data = Path(path).read_bytes()

    print("File:", path)
    print("Size:", len(data))
    print("SHA-256:", hashlib.sha256(data).hexdigest())
    print("MD5:", hashlib.md5(data).hexdigest())

    if len(data) < 0x150:
        print("Error: ROM too small")
        return

    title = data[0x134:0x144]

    print("\n--- Header ---")
    print("Title raw:", title.hex(" "))
    print("Title ASCII:",
          title.decode("ascii", errors="replace"))

    print("Cartridge type:",
          hex(data[0x147]))

    print("ROM size code:",
          hex(data[0x148]))

    print("RAM size code:",
          hex(data[0x149]))

    print("Header checksum:",
          hex(data[0x14d]))

    # Standard header checksum calculation
    checksum = 0
    for b in data[0x134:0x14d]:
        checksum = (checksum - b - 1) & 0xff

    print("Calculated header checksum:",
          hex(checksum))

    print("Header checksum matches:",
          checksum == data[0x14d])

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python analyze_rom.py ROM_FILE")
        sys.exit(1)

    analyze_rom(sys.argv[1])