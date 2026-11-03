"""Render ROM bytes as Game Boy 2bpp tiles into PNG sheets (one per 16KB bank)."""
from pathlib import Path
import sys
from PIL import Image

PALETTE = [255, 170, 85, 0]
COLS = 32  # tiles per row


def render(data, base):
    n = len(data) // 16
    rows = (n + COLS - 1) // COLS
    img = Image.new("L", (COLS * 8, rows * 8), 255)
    px = img.load()
    for t in range(n):
        tx, ty = (t % COLS) * 8, (t // COLS) * 8
        for y in range(8):
            lo, hi = data[t * 16 + y * 2], data[t * 16 + y * 2 + 1]
            for x in range(8):
                bit = 7 - x
                px[tx + x, ty + y] = PALETTE[((hi >> bit) & 1) << 1 | ((lo >> bit) & 1)]
    return img.resize((img.width * 3, img.height * 3), Image.NEAREST)


if __name__ == "__main__":
    rom = Path(sys.argv[1]).read_bytes()
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "reports/tiles")
    out.mkdir(parents=True, exist_ok=True)
    for bank in range(len(rom) // 0x4000):
        render(rom[bank * 0x4000:(bank + 1) * 0x4000], bank).save(out / f"bank{bank:02X}.png")
    print("done", len(rom) // 0x4000, "banks ->", out)
