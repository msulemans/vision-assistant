from __future__ import annotations

import struct
import unittest
import zlib

from vision_assistant.capture import PNG_SIGNATURE, ImageValidationError, _png_chunk, normalize_png
from vision_assistant.pixels import crop_png, decode_png, mostly_black, scale_png, zoom_png


def _pixels(width: int, height: int) -> list[bytes]:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256))
        rows.append(bytes(row))
    return rows


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _filtered_scan(filter_type: int, row: bytes, prev: bytes, bpp: int) -> bytes:
    out = bytearray(len(row))
    for i, value in enumerate(row):
        left = row[i - bpp] if i >= bpp else 0
        up = prev[i]
        up_left = prev[i - bpp] if i >= bpp else 0
        predictor = {
            0: 0,
            1: left,
            2: up,
            3: (left + up) >> 1,
            4: _paeth(left, up, up_left),
        }[filter_type]
        out[i] = (value - predictor) & 0xFF
    return bytes(out)


def _make_png(width: int, height: int, *, filter_cycle: bool = False) -> bytes:
    """A tiny deterministic RGB PNG; optionally one filter type per row."""
    rows = _pixels(width, height)
    raw = bytearray()
    previous = bytes(len(rows[0]))
    for y, row in enumerate(rows):
        filter_type = (y % 5) if filter_cycle else 0
        raw.append(filter_type)
        raw += _filtered_scan(filter_type, row, previous, 3)
        previous = row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _solid_png(width: int, height: int, value: int) -> bytes:
    row = bytes([value] * (width * 3))
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        raw += row
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


class MostlyBlackTest(unittest.TestCase):
    def test_uniform_black_captures_are_detected(self) -> None:
        self.assertTrue(mostly_black(_solid_png(16, 16, 0)))
        self.assertTrue(mostly_black(_solid_png(16, 16, 8)))

    def test_real_content_is_not_flagged(self) -> None:
        self.assertFalse(mostly_black(_make_png(16, 16)))
        self.assertFalse(mostly_black(_solid_png(16, 16, 200)))


class DecodePngTest(unittest.TestCase):
    def test_all_row_filters_round_trip(self) -> None:
        source = _make_png(24, 16, filter_cycle=True)
        decoded = decode_png(source)
        self.assertEqual(decoded.rows, tuple(_pixels(24, 16)))


class CropPngTest(unittest.TestCase):
    def test_crop_returns_exact_source_region(self) -> None:
        png = _make_png(24, 16)
        source = decode_png(png)
        cropped = crop_png(png, x=5, y=3, width=10, height=6)
        result = decode_png(cropped)
        self.assertEqual((result.width, result.height), (10, 6))
        bpp = source.bytes_per_pixel
        start, end = 5 * bpp, (5 + 10) * bpp
        for row in range(6):
            self.assertEqual(result.rows[row], source.rows[3 + row][start:end])
        normalize_png(cropped)  # output stays M003-valid

    def test_crop_rejects_out_of_bounds_and_nonpositive(self) -> None:
        png = _make_png(24, 16)
        with self.assertRaises(ImageValidationError):
            crop_png(png, x=20, y=0, width=10, height=10)
        with self.assertRaises(ImageValidationError):
            crop_png(png, x=-1, y=0, width=10, height=10)
        with self.assertRaises(ImageValidationError):
            crop_png(png, x=0, y=0, width=0, height=10)


class ZoomPngTest(unittest.TestCase):
    def test_zoom_repeats_pixels_nearest_neighbour(self) -> None:
        png = _make_png(24, 16)
        source = decode_png(png)
        zoomed = zoom_png(png, factor=2)
        result = decode_png(zoomed)
        self.assertEqual((result.width, result.height), (48, 32))
        bpp = source.bytes_per_pixel
        expected_row = b"".join(
            source.rows[0][i : i + bpp] * 2 for i in range(0, len(source.rows[0]), bpp)
        )
        self.assertEqual(result.rows[0], expected_row)
        self.assertEqual(result.rows[1], expected_row)  # vertical repeat
        normalize_png(zoomed)

    def test_zoom_factor_bounds(self) -> None:
        png = _make_png(24, 16)
        with self.assertRaises(ImageValidationError):
            zoom_png(png, factor=1)
        with self.assertRaises(ImageValidationError):
            zoom_png(png, factor=9)


class ScalePngTest(unittest.TestCase):
    def test_scale_downscales_to_budget_by_integer_sampling(self) -> None:
        png = _make_png(24, 16)
        source = decode_png(png)
        scaled = scale_png(png, max_pixels=100)
        result = decode_png(scaled)
        self.assertEqual((result.width, result.height), (12, 8))
        bpp = source.bytes_per_pixel
        expected = b"".join(
            source.rows[0][x * 2 * bpp : x * 2 * bpp + bpp] for x in range(12)
        )
        self.assertEqual(result.rows[0], expected)
        normalize_png(scaled)

    def test_scale_passthrough_when_within_budget(self) -> None:
        png = _make_png(24, 16)
        self.assertIs(scale_png(png, max_pixels=10_000), png)


if __name__ == "__main__":
    unittest.main()
