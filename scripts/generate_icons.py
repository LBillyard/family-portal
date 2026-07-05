"""Generate simple PWA icons (navy background, teal circle)."""

import struct
import zlib
from pathlib import Path

NAVY = (15, 29, 50)
TEAL = (0, 168, 158)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: Path, size: int) -> None:
    raw = bytearray()
    cx, cy, r = size // 2, size // 2, int(size * 0.28)
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx, dy = x - cx, y - cy
            if dx * dx + dy * dy <= r * r:
                row.extend(TEAL)
            else:
                row.extend(NAVY)
        raw.extend(row)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b"")
    path.write_bytes(png)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "server" / "static"
    write_png(out / "icon-192.png", 192)
    write_png(out / "icon-512.png", 512)
    print(f"Wrote icons to {out}")
