from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import uuid
from pathlib import Path

from .capture import (
    CaptureFailure,
    EphemeralArtifactStore,
    FileCapturePort,
    MacInteractiveCapturePort,
    PngIngestor,
)
from .fixture import generate_fixture
from .ports import CaptureSource, CapturedFrame

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS = REPO_ROOT / "runs" / "m003-artifacts"


def _public_summary(frame: CapturedFrame, *, include_path: bool) -> dict:
    summary = {
        "artifact_id": frame.fixture_id,
        "source_kind": frame.source.kind,
        "width": frame.width,
        "height": frame.height,
        "mime_type": frame.mime_type,
        "byte_size": frame.byte_size,
        "ephemeral": frame.ephemeral,
        "capture_ms": round(frame.duration_ms, 3),
    }
    if include_path and frame.image_path is not None:
        summary["retained_path"] = str(frame.image_path)
    return summary


def capture_file(path: Path, *, artifacts: Path, retain: bool, trace_id: str) -> tuple[CapturedFrame, EphemeralArtifactStore]:
    store = EphemeralArtifactStore(artifacts, retain=retain)
    ingestor = PngIngestor(store)
    port = FileCapturePort(path, ingestor)
    frame = port.capture(
        trace_id=trace_id,
        source=CaptureSource(kind="file", label="Selected image file"),
    )
    return frame, store


def capture_interactive(*, artifacts: Path, retain: bool, trace_id: str) -> tuple[CapturedFrame, EphemeralArtifactStore]:
    store = EphemeralArtifactStore(artifacts, retain=retain)
    ingestor = PngIngestor(store)
    port = MacInteractiveCapturePort(ingestor)
    print("A macOS selection crosshair will appear. Select one region/window, or press Escape to cancel.")
    frame = port.capture(
        trace_id=trace_id,
        source=CaptureSource(kind="region", label="User-selected region or window"),
    )
    return frame, store


def verify_generated_fixture() -> dict:
    """Run the non-private M003 gate with a generated PNG and deletion check."""
    with tempfile.TemporaryDirectory(prefix="vision-assistant-m003-verify-") as temp_dir:
        root = Path(temp_dir)
        fixture = generate_fixture(path=root / "fixture.png")
        frame, store = capture_file(
            fixture.path,
            artifacts=root / "artifacts",
            retain=False,
            trace_id="m003-generated-verify",
        )
        exists_before_release = bool(frame.image_path and frame.image_path.exists())
        digest_matches = bool(
            frame.image_path
            and frame.content_sha256
            and frame.content_sha256 == hashlib.sha256(frame.image_path.read_bytes()).hexdigest()
        )
        private_mode = bool(frame.image_path and (frame.image_path.stat().st_mode & 0o777) == 0o600)
        dimensions_match = (frame.width, frame.height) == (fixture.width, fixture.height)
        store.release(frame)
        deleted_after_release = bool(frame.image_path and not frame.image_path.exists())
        return {
            "dimensions_match": dimensions_match,
            "digest_matches": digest_matches,
            "private_mode": private_mode,
            "exists_before_release": exists_before_release,
            "deleted_after_release": deleted_after_release,
            "pass": all(
                [dimensions_match, digest_matches, private_mode, exists_before_release, deleted_after_release]
            ),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone 003 explicit screenshot ingest and capture")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--file", type=Path, help="explicit PNG file to ingest")
    choice.add_argument("--interactive", action="store_true", help="open the macOS region/window selector")
    parser.add_argument("--retain", action="store_true", help="opt in to retaining the normalized local artifact")
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS, help="private ignored artifact directory")
    parser.add_argument("--verify", action="store_true", help="run the generated-fixture lifecycle gate")
    args = parser.parse_args(argv)

    if args.verify:
        result = verify_generated_fixture()
        print(json.dumps(result, sort_keys=True))
        if not result["pass"]:
            return 1

    if args.file is None and not args.interactive:
        return 0 if args.verify else parser.error("choose --file, --interactive, or --verify")

    trace_id = f"m003-{uuid.uuid4().hex[:12]}"
    try:
        if args.file is not None:
            frame, store = capture_file(args.file, artifacts=args.artifacts, retain=args.retain, trace_id=trace_id)
        else:
            frame, store = capture_interactive(artifacts=args.artifacts, retain=args.retain, trace_id=trace_id)
    except CaptureFailure as exc:
        print(json.dumps({"status": "not_captured", "code": exc.code, "message": str(exc)}, sort_keys=True))
        return 2

    try:
        print(json.dumps({"status": "captured", **_public_summary(frame, include_path=args.retain)}, sort_keys=True))
    finally:
        store.release(frame)
    if not args.retain:
        print(json.dumps({"status": "released", "artifact_id": frame.fixture_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
