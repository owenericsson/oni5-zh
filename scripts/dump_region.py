from pathlib import Path
import sys

if len(sys.argv) != 4:
    raise SystemExit(
        "Usage: python scripts/dump_region.py ROM OFFSET LENGTH"
    )

rom = Path(sys.argv[1]).read_bytes()
offset = int(sys.argv[2], 0)
length = int(sys.argv[3], 0)

if offset < 0 or length <= 0 or offset >= len(rom):
    raise SystemExit("Invalid range")

end = min(offset + length, len(rom))

for pos in range(offset, end, 16):
    chunk = rom[pos:min(pos + 16, end)]

    hx = " ".join(f"{b:02X}" for b in chunk)
    asc = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)

    print(f"{pos:06X}  {hx:<47}  {asc}")