"""Generate the kitsune-vault icon (SVG + PNG) with no dependencies.

A geometric fox head with a golden keyhole. The same shape list feeds both
the SVG writer and a tiny supersampling rasteriser that writes the PNG.

    python3 tools/make_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 256
OUT = Path(__file__).resolve().parent.parent / "kitsune_vault" / "assets"

ORANGE, DARK, CREAM, GOLD, BG = "#f28c28", "#2b1a10", "#fff4e6", "#ffd24a", "#1f2a44"

SHAPES = [
    ("rrect", (8, 8, 240, 240, 48), BG),
    ("poly", [(44, 52), (100, 98), (156, 98), (212, 52), (200, 140), (128, 214), (56, 140)], ORANGE),
    ("poly", [(60, 74), (94, 102), (72, 120)], DARK),
    ("poly", [(196, 74), (162, 102), (184, 120)], DARK),
    ("poly", [(80, 150), (128, 138), (176, 150), (128, 214)], CREAM),
    ("poly", [(88, 126), (112, 132), (94, 140)], DARK),
    ("poly", [(168, 126), (144, 132), (162, 140)], DARK),
    ("poly", [(115, 190), (141, 190), (128, 205)], DARK),
    ("circle", (128, 106, 10), GOLD),
    ("poly", [(122, 110), (134, 110), (139, 132), (117, 132)], GOLD),
]


# ---------------------------------------------------------------- SVG

def svg() -> str:
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">']
    for kind, g, col in SHAPES:
        if kind == "rrect":
            x, y, w, h, r = g
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{col}"/>')
        elif kind == "circle":
            cx, cy, r = g
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{col}"/>')
        else:
            pts = " ".join(f"{x},{y}" for x, y in g)
            parts.append(f'<polygon points="{pts}" fill="{col}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- raster

def _inside(kind, g, x, y) -> bool:
    if kind == "circle":
        cx, cy, r = g
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    if kind == "rrect":
        rx, ry, w, h, r = g
        if not (rx <= x <= rx + w and ry <= y <= ry + h):
            return False
        cx = min(max(x, rx + r), rx + w - r)
        cy = min(max(y, ry + r), ry + h - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    inside = False  # even-odd polygon test
    n = len(g)
    for i in range(n):
        (x1, y1), (x2, y2) = g[i], g[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _rgb(h: str):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def png(ss: int = 3) -> bytes:
    shapes = [(k, g, _rgb(c)) for k, g, c in SHAPES]
    rows = bytearray()
    offs = [(i + 0.5) / ss for i in range(ss)]
    for py in range(SIZE):
        rows.append(0)
        for px in range(SIZE):
            r = gr = b = a = 0
            for oy in offs:
                for ox in offs:
                    x, y = px + ox, py + oy
                    for kind, g, col in reversed(shapes):
                        if _inside(kind, g, x, y):
                            r += col[0]; gr += col[1]; b += col[2]; a += 255
                            break
            n = ss * ss
            cov = a / 255 or 1
            rows += bytes((round(r / cov), round(gr / cov), round(b / cov), round(a / n)))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "kitsune-vault.svg").write_text(svg())
    (OUT / "kitsune-vault.png").write_bytes(png())
    print("written to", OUT)
