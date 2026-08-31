from __future__ import annotations

import hashlib
import subprocess
import stat
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

from vision_assistant.capture import (
    CaptureCancelled,
    CapturePermissionDenied,
    CaptureSelectionTimedOut,
    EphemeralArtifactStore,
    FileCapturePort,
    ImagePolicy,
    ImageValidationError,
    MacInteractiveCapturePort,
    PngIngestor,
    normalize_png,
)
from vision_assistant.capture_cli import verify_generated_fixture
from vision_assistant.adapters import FakeAnswerPolicy, FakeVisionModelPort
from vision_assistant.clock import FakeClock
from vision_assistant.fixture import generate_fixture
from vision_assistant.ports import CaptureSource
from vision_assistant.spine import ReadOnlyTurn
from vision_assistant.trace import JsonlTraceSink


def chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


def insert_before_idat(png: bytes, tag: bytes, body: bytes) -> bytes:
    marker = png.index(b"IDAT") - 4
    return png[:marker] + chunk(tag, body) + png[marker:]


class CaptureMilestoneTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fixture = generate_fixture(path=self.root / "selected.png")
        self.store = EphemeralArtifactStore(self.root / "artifacts")
        self.ingestor = PngIngestor(self.store)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_file_ingest_records_exact_metadata_and_private_artifact(self) -> None:
        ticks = iter([1_000_000_000, 1_012_500_000])
        port = FileCapturePort(self.fixture.path, self.ingestor, monotonic_ns=lambda: next(ticks))
        frame = port.capture(
            trace_id="m003-file",
            source=CaptureSource(kind="file", label="Selected image file"),
        )
        self.assertEqual((frame.width, frame.height), (480, 300))
        self.assertEqual(frame.duration_ms, 12.5)
        self.assertEqual(frame.mime_type, "image/png")
        self.assertTrue(frame.ephemeral)
        self.assertIsNotNone(frame.image_path)
        self.assertEqual(stat.S_IMODE(frame.image_path.stat().st_mode), 0o600)
        self.assertEqual(frame.content_sha256, hashlib.sha256(frame.image_path.read_bytes()).hexdigest())
        self.assertEqual(frame.byte_size, len(frame.image_path.read_bytes()))

    def test_release_deletes_ephemeral_artifact_but_not_source(self) -> None:
        port = FileCapturePort(self.fixture.path, self.ingestor)
        frame = port.capture(trace_id="m003-release", source=CaptureSource(kind="file", label="Selected image file"))
        self.store.release(frame)
        self.assertFalse(frame.image_path.exists())
        self.assertTrue(self.fixture.path.exists())

    def test_retain_is_explicit(self) -> None:
        retained_store = EphemeralArtifactStore(self.root / "retained", retain=True)
        frame = FileCapturePort(self.fixture.path, PngIngestor(retained_store)).capture(
            trace_id="m003-retain",
            source=CaptureSource(kind="file", label="Selected image file"),
        )
        retained_store.release(frame)
        self.assertFalse(frame.ephemeral)
        self.assertTrue(frame.image_path.exists())

    def test_normalizer_strips_text_metadata(self) -> None:
        private_png = insert_before_idat(self.fixture.png_bytes, b"tEXt", b"User\x00private@example.test")
        normalized = normalize_png(private_png)
        self.assertIn("tEXt", normalized.stripped_chunks)
        self.assertNotIn(b"private@example.test", normalized.data)
        self.assertEqual((normalized.width, normalized.height), (480, 300))

    def test_invalid_crc_and_non_png_are_rejected(self) -> None:
        broken = bytearray(self.fixture.png_bytes)
        broken[-5] ^= 0x01
        for data in (b"not an image", bytes(broken)):
            with self.subTest(size=len(data)), self.assertRaises(ImageValidationError):
                normalize_png(data)

    def test_dimension_policy_is_enforced_before_artifact_write(self) -> None:
        with self.assertRaises(ImageValidationError):
            normalize_png(self.fixture.png_bytes, ImagePolicy(max_width=100))
        self.assertEqual(list(self.store.root.glob("**/frame.png")), [])

    def test_symlink_input_is_rejected(self) -> None:
        link = self.root / "linked.png"
        link.symlink_to(self.fixture.path)
        with self.assertRaises(ImageValidationError):
            FileCapturePort(link, self.ingestor).capture(
                trace_id="m003-link",
                source=CaptureSource(kind="file", label="Selected image file"),
            )

    def test_artifact_trace_directory_cannot_be_a_symlink(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.store.root / "m003-escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.store.write(trace_id="m003-escape", data=self.fixture.png_bytes)
        self.assertEqual(list(outside.iterdir()), [])

    def test_artifact_root_cannot_be_a_symlink(self) -> None:
        outside = self.root / "outside-root"
        outside.mkdir()
        linked_root = self.root / "linked-root"
        linked_root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            EphemeralArtifactStore(linked_root)

    def test_mac_capture_uses_fixed_interactive_command_and_shared_ingestor(self) -> None:
        observed: dict = {}

        def runner(argv, **kwargs):
            observed["argv"] = argv
            observed["kwargs"] = kwargs
            Path(argv[-1]).write_bytes(self.fixture.png_bytes)
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        ticks = iter([2_000_000_000, 2_250_000_000])
        frame = MacInteractiveCapturePort(
            self.ingestor,
            runner=runner,
            monotonic_ns=lambda: next(ticks),
        ).capture(
            trace_id="m003-mac",
            source=CaptureSource(kind="region", label="User-selected region or window"),
        )
        self.assertEqual(observed["argv"][:5], ["/usr/sbin/screencapture", "-i", "-x", "-t", "png"])
        self.assertFalse(observed["kwargs"]["check"])
        self.assertEqual(frame.duration_ms, 250.0)
        self.assertEqual(frame.content_sha256, hashlib.sha256(frame.image_path.read_bytes()).hexdigest())

    def test_permission_denial_and_cancel_are_recoverable(self) -> None:
        def denied(*args, **kwargs):
            return SimpleNamespace(returncode=1, stderr="Screen capture is not allowed", stdout="")

        def cancelled(*args, **kwargs):
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        source = CaptureSource(kind="region", label="User-selected region or window")
        with self.assertRaises(CapturePermissionDenied):
            MacInteractiveCapturePort(self.ingestor, runner=denied).capture(trace_id="m003-denied", source=source)
        with self.assertRaises(CaptureCancelled):
            MacInteractiveCapturePort(self.ingestor, runner=cancelled).capture(trace_id="m003-cancel", source=source)

    def test_selection_timeout_is_not_misreported_as_user_cancel(self) -> None:
        def timed_out(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        with self.assertRaises(CaptureSelectionTimedOut) as raised:
            MacInteractiveCapturePort(self.ingestor, runner=timed_out).capture(
                trace_id="m003-timeout",
                source=CaptureSource(kind="region", label="User-selected region or window"),
            )
        self.assertEqual(raised.exception.code, "selection_timed_out")

    def test_typed_capture_failure_reaches_turn_trace(self) -> None:
        class DeniedCapture:
            def capture(self, *, trace_id, source):
                raise CapturePermissionDenied()

        trace_path = self.root / "denied.jsonl"
        sink = JsonlTraceSink(trace_path, trace_id="m003-denied-turn")
        turn = ReadOnlyTurn(
            trace_id="m003-denied-turn",
            clock=FakeClock(),
            capture=DeniedCapture(),
            model=FakeVisionModelPort(),
            policy=FakeAnswerPolicy(),
            sink=sink,
        )
        final = turn.run(
            source=CaptureSource(kind="region", label="User-selected region or window"),
            question="What is visible?",
        )
        sink.write()
        failure = next(record for record in sink.read_back() if record.get("type") == "turn.failed")
        self.assertEqual(final, "failed")
        self.assertEqual(failure["payload"]["code"], "permission_denied")

    def test_real_artifact_paths_do_not_enter_trace(self) -> None:
        trace_path = self.root / "file-turn.jsonl"
        sink = JsonlTraceSink(trace_path, trace_id="m003-file-turn")
        turn = ReadOnlyTurn(
            trace_id="m003-file-turn",
            clock=FakeClock(),
            capture=FileCapturePort(self.fixture.path, self.ingestor),
            model=FakeVisionModelPort(),
            policy=FakeAnswerPolicy(),
            sink=sink,
        )
        final = turn.run(
            source=CaptureSource(kind="file", label="Selected image file"),
            question="What is visible?",
        )
        sink.write()
        trace_text = trace_path.read_text(encoding="utf-8")
        self.assertEqual(final, "done")
        self.assertNotIn(str(self.fixture.path), trace_text)
        self.assertNotIn(str(self.store.root), trace_text)

    def test_generated_fixture_gate(self) -> None:
        result = verify_generated_fixture()
        self.assertTrue(result["pass"], result)


if __name__ == "__main__":
    unittest.main()
