from pathlib import Path
import sys

rom = Path(sys.argv[1]).read_bytes()

MIN_LENGTH = 4

start = None
buf = bytearray()

def flush():
    global start, buf

    if start is not None and len(buf) >= MIN_LENGTH:
        text = buf.decode("ascii", errors="replace")
        print(f"{start:06X}: {text}")

    start = None
    buf = bytearray()

for offset, b in enumerate(rom):
    if 0x20 <= b <= 0x7E:
        if start is None:
            start = offset
        buf.append(b)
    else:
        flush()

flush()
