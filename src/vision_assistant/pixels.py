"""Deterministic pixel operations for evidence augmentation (M007).

Pure-stdlib PNG decode/encode over the M003 normalized format: decode to
unfiltered rows, then crop or integer-zoom and re-encode with filter 0.
Every output re-validates through `normalize_png`, so augmented images obey
the same bounds as captured ones. No new dependencies.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .capture import (
    PNG_SIGNATURE,
    ImagePolicy,
    ImageValidationError,
    _decompressed_row_size,
    _png_chunk,
    normalize_png,
)

_MAX_ZOOM = 8


def _channels(colour_type: int) -> int:
    try:
        return {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]
    except KeyError as exc:
        raise ImageValidationError(f"unsupported PNG colour type {colour_type}") from exc


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(filter_type: int, scan: bytes, prev: bytes, bpp: int) -> bytes:
    if filter_type == 0:
        return bytes(scan)
    out = bytearray(len(scan))
    if filter_type == 1:
        for i, value in enumerate(scan):
            left = out[i - bpp] if i >= bpp else 0
            out[i] = (value + left) & 0xFF
    elif filter_type == 2:
        for i, value in enumerate(scan):
            out[i] = (value + prev[i]) & 0xFF
    elif filter_type == 3:
        for i, value in enumerate(scan):
            left = out[i - bpp] if i >= bpp else 0
            out[i] = (value + ((left + prev[i]) >> 1)) & 0xFF
    elif filter_type == 4:
        for i, value in enumerate(scan):
            left = out[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            out[i] = (value + _paeth(left, up, up_left)) & 0xFF
    else:
        raise ImageValidationError("invalid PNG row filter")
    return bytes(out)


@dataclass(frozen=True)
class PngPixels:
    """Unfiltered scanlines (filter bytes removed) plus colour metadata."""

    width: int
    height: int
    colour_type: int
    bit_depth: int
    rows: tuple[bytes, ...]

    @property
    def bytes_per_pixel(self) -> int:
        return _channels(self.colour_type) * (self.bit_depth // 8)


def decode_png(data: bytes) -> PngPixels:
    """Validate through the M003 normalizer, then inflate to unfiltered rows."""
    normalized = normalize_png(data)
    width, height = normalized.width, normalized.height
    offset = len(PNG_SIGNATURE)
    ihdr: bytes | None = None
    idat: list[bytes] = []
    while offset < len(normalized.data):
        length = struct.unpack(">I", normalized.data[offset : offset + 4])[0]
        tag = normalized.data[offset + 4 : offset + 8]
        body = normalized.data[offset + 8 : offset + 8 + length]
        if tag == b"IHDR":
            ihdr = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
        offset += length + 12
    if ihdr is None:
        raise ImageValidationError("normalized PNG lost its IHDR")
    _, _, bit_depth, colour_type, _, _, _ = struct.unpack(">IIBBBBB", ihdr)
    if colour_type == 3:
        raise ImageValidationError("palette PNGs are not supported for pixel operations")
    if bit_depth < 8:
        raise ImageValidationError("pixel operations need bit depth 8 or 16")
    row_size = _decompressed_row_size(width, bit_depth, colour_type)
    raw = zlib.decompress(b"".join(idat))
    bpp = _channels(colour_type) * (bit_depth // 8)
    rows: list[bytes] = []
    previous = bytes(row_size)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        scan = raw[position + 1 : position + 1 + row_size]
        position += row_size + 1
        previous = _unfilter(filter_type, scan, previous, bpp)
        rows.append(previous)
    return PngPixels(
        width=width,
        height=height,
        colour_type=colour_type,
        bit_depth=bit_depth,
        rows=tuple(rows),
    )


def encode_png(pixels: PngPixels) -> bytes:
    """Encode unfiltered rows as a canonical filter-0 PNG."""
    raw = b"".join(b"\x00" + row for row in pixels.rows)
    ihdr = struct.pack(
        ">IIBBBBB", pixels.width, pixels.height, pixels.bit_depth, pixels.colour_type, 0, 0, 0
    )
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def _check_within_policy(width: int, height: int) -> None:
    policy = ImagePolicy()
    if width > policy.max_width or height > policy.max_height or width * height > policy.max_pixels:
        raise ImageValidationError("augmented image exceeds the configured pixel limits")


def crop_png(data: bytes, *, x: int, y: int, width: int, height: int) -> bytes:
    """Crop a rectangle (source pixels). Output is a fresh valid PNG."""
    draw = decode_png(data)
    if x < 0 or y < 0 or width < 1 or height < 1:
        raise ImageValidationError("crop region must be positive")
    if x + width > draw.width or y + height > draw.height:
        raise ImageValidationError("crop region is outside the image bounds")
    bpp = draw.bytes_per_pixel
    start, end = x * bpp, (x + width) * bpp
    rows = tuple(row[start:end] for row in draw.rows[y : y + height])
    result = encode_png(
        PngPixels(
            width=width,
            height=height,
            colour_type=draw.colour_type,
            bit_depth=draw.bit_depth,
            rows=rows,
        )
    )
    normalize_png(result)  # hard guarantee: outputs stay M003-valid
    return result


def zoom_png(data: bytes, *, factor: int) -> bytes:
    """Integer nearest-neighbour zoom. Deterministic, no smoothing."""
    draw = decode_png(data)
    if not 2 <= factor <= _MAX_ZOOM:
        raise ImageValidationError(f"zoom factor must be between 2 and {_MAX_ZOOM}")
    new_width, new_height = draw.width * factor, draw.height * factor
    _check_within_policy(new_width, new_height)
    bpp = draw.bytes_per_pixel
    rows: list[bytes] = []
    for row in draw.rows:
        stretched = b"".join(row[i : i + bpp] * factor for i in range(0, len(row), bpp))
        rows.extend([stretched] * factor)
    result = encode_png(
        PngPixels(
            width=new_width,
            height=new_height,
            colour_type=draw.colour_type,
            bit_depth=draw.bit_depth,
            rows=tuple(rows),
        )
    )
    normalize_png(result)
    return result
