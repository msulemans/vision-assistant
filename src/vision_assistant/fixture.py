from __future__ import annotations

import base64
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """Encode an 8-bit RGB image (no alpha) into a PNG using only stdlib."""
    row_bytes = width * 3
    raw = b"".join(b"\x00" + rgb[y * row_bytes : (y + 1) * row_bytes] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _fill_rect(rgb: bytearray, width: int, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = (y * width + x) * 3
            rgb[i : i + 3] = bytes(color)


def _draw_glyph(rgb: bytearray, width: int, x: int, y: int, h: int, color: tuple[int, int, int], on: bool) -> None:
    """Draw one small vertical bar used as a stand-in for text pixels."""
    if not on:
        return
    for yy in range(y, y + h):
        for xx in range(x, x + 2):
            i = (yy * width + xx) * 3
            rgb[i : i + 3] = bytes(color)


def _draw_text_blocks(rgb: bytearray, width: int, x: int, y: int, n: int, h: int, color: tuple[int, int, int]) -> None:
    """Draw a run of short bars to suggest a line of generic text."""
    for k in range(n):
        _draw_glyph(rgb, width, x + k * 6, y, h, color, True)


@dataclass(frozen=True)
class SyntheticFixture:
    """A synthetic, trusted-code-generated fixture image."""

    id: str
    width: int
    height: int
    png_bytes: bytes
    path: Path

    @property
    def data_uri(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png_bytes).decode("ascii")


def generate_fixture(
    *,
    fixture_id: str = "synthetic-dialog-001",
    width: int = 480,
    height: int = 300,
    path: Path | None = None,
) -> SyntheticFixture:
    """Draw a synthetic 'Connect to Database' dialog screen.

    This is trusted code producing a fake image only. It contains no real
    pixels, text, or sensitive data. Rectangles and blocks stand in for UI
    elements; real text/OCR is handled in a later milestone.
    """
    rgb = bytearray(width * height * 3)

    # App background.
    _fill_rect(rgb, width, 0, 0, width, height, (46, 48, 56))

    # Dialog window.
    _fill_rect(rgb, width, 40, 48, 440, 264, (245, 246, 250))
    # Title bar.
    _fill_rect(rgb, width, 40, 40, 440, 58, (70, 84, 112))

    # Title suggestion (blocks).
    _draw_text_blocks(rgb, width, 56, 45, 20, 9, (245, 246, 250))

    # Field labels (blocks).
    _draw_text_blocks(rgb, width, 60, 82, 10, 7, (90, 96, 110))
    _draw_text_blocks(rgb, width, 60, 132, 10, 7, (90, 96, 110))

    # Input fields (outlined rectangles).
    _fill_rect(rgb, width, 60, 94, 420, 118, (255, 255, 255))
    _fill_rect(rgb, width, 60, 144, 420, 168, (255, 255, 255))

    # A small red validation hint near the second field.
    _fill_rect(rgb, width, 60, 176, 210, 184, (200, 82, 82))
    _draw_text_blocks(rgb, width, 66, 176, 12, 6, (255, 240, 240))

    # Buttons.
    _fill_rect(rgb, width, 300, 220, 372, 248, (57, 122, 202))
    _fill_rect(rgb, width, 384, 220, 428, 248, (200, 202, 208))

    # A green status toast.
    _fill_rect(rgb, width, 60, 240, 200, 254, (56, 142, 96))

    png = _encode_png(width, height, bytes(rgb))
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)

    return SyntheticFixture(id=fixture_id, width=width, height=height, png_bytes=png, path=path)
