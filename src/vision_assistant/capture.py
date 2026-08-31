from __future__ import annotations

import hashlib
import os
import re
import stat
import struct
import subprocess
import tempfile
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ports import CaptureFailure, CapturedFrame, CaptureSource

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SAFE_ANCILLARY = frozenset({b"cHRM", b"gAMA", b"sBIT", b"sRGB", b"bKGD", b"pHYs", b"tRNS"})
_TRACE_ID = re.compile(r"^[A-Za-z0-9._-]{1,96}$")


class ImageValidationError(CaptureFailure):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_image")


class CapturePermissionDenied(CaptureFailure):
    def __init__(self) -> None:
        super().__init__(
            "Screen Recording permission is not available; grant it in System Settings and retry",
            code="permission_denied",
        )


class CaptureCancelled(CaptureFailure):
    def __init__(self) -> None:
        super().__init__("screen selection was cancelled", code="cancelled_by_user")


class CaptureSelectionTimedOut(CaptureFailure):
    def __init__(self) -> None:
        super().__init__("screen selection exceeded its time budget", code="selection_timed_out")


class CaptureUnavailable(CaptureFailure):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="capture_unavailable")


@dataclass(frozen=True)
class ImagePolicy:
    max_file_bytes: int = 20 * 1024 * 1024
    max_width: int = 8192
    max_height: int = 8192
    max_pixels: int = 40_000_000


@dataclass(frozen=True)
class NormalizedPng:
    data: bytes
    width: int
    height: int
    stripped_chunks: tuple[str, ...]


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _decompressed_row_size(width: int, bit_depth: int, colour_type: int) -> int:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour_type)
    if channels is None:
        raise ImageValidationError(f"unsupported PNG colour type {colour_type}")
    valid_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if bit_depth not in valid_depths[colour_type]:
        raise ImageValidationError("invalid PNG bit depth for colour type")
    return (width * channels * bit_depth + 7) // 8


def normalize_png(data: bytes, policy: ImagePolicy | None = None) -> NormalizedPng:
    """Validate a non-interlaced PNG and remove metadata-bearing chunks.

    Pixel data is decompressed only to validate its exact bounded size and row
    filters, then the original compressed stream is retained. This avoids a
    new image dependency while still rejecting truncated/decompression-bomb
    inputs before a future model decoder sees them.
    """
    policy = policy or ImagePolicy()
    if len(data) > policy.max_file_bytes:
        raise ImageValidationError("PNG exceeds the configured byte limit")
    if not data.startswith(PNG_SIGNATURE):
        raise ImageValidationError("only PNG input is accepted in Milestone 003")

    offset = len(PNG_SIGNATURE)
    ihdr: bytes | None = None
    kept: list[tuple[bytes, bytes]] = []
    idat_parts: list[bytes] = []
    stripped: list[str] = []
    saw_iend = False

    while offset < len(data):
        if offset + 12 > len(data):
            raise ImageValidationError("truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        tag = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ImageValidationError("truncated PNG chunk data")
        body = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        actual_crc = zlib.crc32(tag + body) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ImageValidationError(f"PNG CRC mismatch in {tag.decode('ascii', 'replace')}")
        if not all(65 <= c <= 90 or 97 <= c <= 122 for c in tag):
            raise ImageValidationError("invalid PNG chunk type")

        if tag == b"IHDR":
            if ihdr is not None or offset != len(PNG_SIGNATURE) or length != 13:
                raise ImageValidationError("invalid PNG IHDR")
            ihdr = body
        elif tag == b"IDAT":
            if ihdr is None:
                raise ImageValidationError("PNG IDAT appears before IHDR")
            idat_parts.append(body)
        elif tag == b"IEND":
            if length != 0 or not idat_parts:
                raise ImageValidationError("invalid PNG IEND")
            saw_iend = True
            offset = end
            break
        elif tag in {b"acTL", b"fcTL", b"fdAT"}:
            raise ImageValidationError("animated PNG input is not accepted")
        elif tag[0] & 0x20:
            if tag in _SAFE_ANCILLARY:
                kept.append((tag, body))
            else:
                stripped.append(tag.decode("ascii"))
        else:
            if tag != b"PLTE":
                raise ImageValidationError(f"unknown critical PNG chunk {tag.decode('ascii')}")
            kept.append((tag, body))
        offset = end

    if ihdr is None or not saw_iend or offset != len(data):
        raise ImageValidationError("PNG is missing a valid final IEND chunk")

    width, height, bit_depth, colour_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", ihdr)
    if width < 1 or height < 1:
        raise ImageValidationError("PNG dimensions must be positive")
    if width > policy.max_width or height > policy.max_height or width * height > policy.max_pixels:
        raise ImageValidationError("PNG dimensions exceed the configured limit")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise ImageValidationError("only non-interlaced standard PNG input is accepted")

    row_size = _decompressed_row_size(width, bit_depth, colour_type)
    expected_size = height * (row_size + 1)
    inflater = zlib.decompressobj()
    raw = inflater.decompress(b"".join(idat_parts), expected_size + 1)
    if len(raw) > expected_size or inflater.unconsumed_tail:
        raise ImageValidationError("PNG pixel stream exceeds its declared dimensions")
    raw += inflater.flush()
    if len(raw) != expected_size or not inflater.eof or inflater.unused_data:
        raise ImageValidationError("PNG pixel stream has an invalid decompressed size")
    for row in range(height):
        if raw[row * (row_size + 1)] > 4:
            raise ImageValidationError("PNG contains an invalid row filter")

    canonical = bytearray(PNG_SIGNATURE)
    canonical.extend(_png_chunk(b"IHDR", ihdr))
    for tag, body in kept:
        canonical.extend(_png_chunk(tag, body))
    canonical.extend(_png_chunk(b"IDAT", b"".join(idat_parts)))
    canonical.extend(_png_chunk(b"IEND", b""))
    return NormalizedPng(bytes(canonical), width, height, tuple(stripped))


class EphemeralArtifactStore:
    """Private local artifacts with explicit release and purge operations."""

    def __init__(self, root: Path, *, retain: bool = False) -> None:
        self.root = Path(root)
        self.retain = retain
        if self.root.is_symlink():
            raise ValueError("artifact root cannot be a symbolic link")
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def write(self, *, trace_id: str, data: bytes) -> Path:
        if not _TRACE_ID.fullmatch(trace_id):
            raise ValueError("trace_id contains unsafe characters")
        trace_dir = self.root / trace_id
        if trace_dir.is_symlink():
            raise ValueError("artifact trace directory cannot be a symbolic link")
        trace_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        if trace_dir.resolve().parent != self.root.resolve():
            raise ValueError("artifact trace directory escaped the store")
        trace_dir.chmod(0o700)
        temp_path = trace_dir / ".frame.tmp"
        final_path = trace_dir / "frame.png"
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, final_path)
            final_path.chmod(0o600)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return final_path

    def release(self, frame: CapturedFrame) -> None:
        if self.retain or not frame.ephemeral or frame.image_path is None:
            return
        path = frame.image_path
        if path.parent.parent != self.root:
            raise ValueError("artifact is outside this store")
        if path.exists():
            path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass


class PngIngestor:
    """The single normalization path used by file and macOS capture ports."""

    def __init__(self, store: EphemeralArtifactStore, *, policy: ImagePolicy | None = None) -> None:
        self.store = store
        self.policy = policy or ImagePolicy()

    def ingest_bytes(
        self,
        data: bytes,
        *,
        trace_id: str,
        source: CaptureSource,
        duration_ms: float,
    ) -> CapturedFrame:
        normalized = normalize_png(data, self.policy)
        path = self.store.write(trace_id=trace_id, data=normalized.data)
        return CapturedFrame(
            trace_id=trace_id,
            source=source,
            width=normalized.width,
            height=normalized.height,
            duration_ms=duration_ms,
            fixture_id=trace_id,
            image_path=path,
            mime_type="image/png",
            byte_size=len(normalized.data),
            content_sha256=hashlib.sha256(normalized.data).hexdigest(),
            ephemeral=not self.store.retain,
        )


class FileCapturePort:
    def __init__(
        self,
        input_path: Path,
        ingestor: PngIngestor,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.input_path = Path(input_path)
        self.ingestor = ingestor
        self._monotonic_ns = monotonic_ns

    def capture(self, *, trace_id: str, source: CaptureSource) -> CapturedFrame:
        if source.kind != "file":
            raise CaptureUnavailable("file adapter requires source kind 'file'")
        started = self._monotonic_ns()
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.input_path, flags)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise ImageValidationError("selected image must be a regular file")
                if info.st_size > self.ingestor.policy.max_file_bytes:
                    raise ImageValidationError("PNG exceeds the configured byte limit")
                with os.fdopen(fd, "rb") as handle:
                    fd = -1
                    data = handle.read(self.ingestor.policy.max_file_bytes + 1)
                if len(data) > self.ingestor.policy.max_file_bytes:
                    raise ImageValidationError("PNG exceeds the configured byte limit")
            finally:
                if fd >= 0:
                    os.close(fd)
        except FileNotFoundError as exc:
            raise CaptureUnavailable("selected image file does not exist") from exc
        except OSError as exc:
            if self.input_path.is_symlink():
                raise ImageValidationError("symbolic-link image input is not accepted") from exc
            raise CaptureUnavailable("selected image file could not be opened") from exc
        duration_ms = (self._monotonic_ns() - started) / 1_000_000
        return self.ingestor.ingest_bytes(
            data,
            trace_id=trace_id,
            source=source,
            duration_ms=duration_ms,
        )


class MacInteractiveCapturePort:
    """User-triggered region/window capture using macOS `screencapture -i`."""

    def __init__(
        self,
        ingestor: PngIngestor,
        *,
        executable: str = "/usr/sbin/screencapture",
        runner: Callable = subprocess.run,
        timeout_s: float = 180.0,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.ingestor = ingestor
        self.executable = executable
        self._runner = runner
        self.timeout_s = timeout_s
        self._monotonic_ns = monotonic_ns

    def capture(self, *, trace_id: str, source: CaptureSource) -> CapturedFrame:
        if source.kind not in {"region", "window"}:
            raise CaptureUnavailable("interactive adapter requires region or window scope")
        started = self._monotonic_ns()
        try:
            with tempfile.TemporaryDirectory(prefix="vision-assistant-capture-") as temp_dir:
                raw_path = Path(temp_dir) / "selected.png"
                result = self._runner(
                    [self.executable, "-i", "-x", "-t", "png", str(raw_path)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    check=False,
                    env={"PATH": "/usr/bin:/bin:/usr/sbin", "LC_ALL": "C"},
                )
                stderr = (result.stderr or "").lower()
                if result.returncode != 0:
                    if "not allowed" in stderr or "permission" in stderr or "could not create image" in stderr:
                        raise CapturePermissionDenied()
                    raise CaptureCancelled()
                if not raw_path.exists() or raw_path.stat().st_size == 0:
                    raise CaptureCancelled()
                data = raw_path.read_bytes()
        except subprocess.TimeoutExpired as exc:
            raise CaptureSelectionTimedOut() from exc
        except FileNotFoundError as exc:
            raise CaptureUnavailable("macOS screencapture executable is unavailable") from exc

        duration_ms = (self._monotonic_ns() - started) / 1_000_000
        return self.ingestor.ingest_bytes(
            data,
            trace_id=trace_id,
            source=source,
            duration_ms=duration_ms,
        )
