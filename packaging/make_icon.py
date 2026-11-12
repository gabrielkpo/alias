"""The app icon, drawn from code (no image in the repository): a 1024x1024 PNG with an alias in
square brackets, `[ ]`, white on dark blue. `tauri icon` turns it into the icon sizes at build.

    python packaging/make_icon.py desktop/icon.png
"""

import struct
import sys
import zlib

SIZE = 1024
BACKGROUND = (31, 42, 68, 255)
INK = (255, 255, 255, 255)


def pixel(x: int, y: int) -> tuple[int, int, int, int]:
    margin, radius = 64, 180  # rounded square
    inside_x, inside_y = margin <= x < SIZE - margin, margin <= y < SIZE - margin
    if not (inside_x and inside_y):
        return (0, 0, 0, 0)
    cx = min(max(x, margin + radius), SIZE - margin - radius)
    cy = min(max(y, margin + radius), SIZE - margin - radius)
    if (x - cx) ** 2 + (y - cy) ** 2 > radius**2:
        return (0, 0, 0, 0)
    top, bottom, stroke, arm = 300, 724, 64, 120
    for left in (300, SIZE - 300 - stroke):  # the two brackets
        if left <= x < left + stroke and top <= y < bottom:
            return INK
        inner = left + stroke if left < SIZE // 2 else left - arm + stroke
        if inner <= x < inner + arm - stroke and (
            top <= y < top + stroke or bottom - stroke <= y < bottom
        ):
            return INK
    return BACKGROUND


def png(path: str) -> None:
    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(SIZE)) for y in range(SIZE)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    with open(path, "wb") as out:
        out.write(b"\x89PNG\r\n\x1a\n")
        out.write(chunk(b"IHDR", header))
        out.write(chunk(b"IDAT", zlib.compress(rows, 9)))
        out.write(chunk(b"IEND", b""))


if __name__ == "__main__":
    png(sys.argv[1])
