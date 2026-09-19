"""M006 one-shot local Vision Assistant.

One explicit flow: preview a user-selected PNG, submit one question to the
pinned local model, receive a labelled answer, then release the private
artifact. Every step is timed and written to a JSONL trace. The model adapter
is passed in, so tests run without a GPU or a server.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .capture import EphemeralArtifactStore, PngIngestor
from .events import (
    ANALYSING,
    ANSWERING,
    CANCELLED,
    DONE,
    Event,
    FAILED,
    IDLE,
    KIND_REAL,
)
from .ports import CaptureSource, CapturedFrame
from .trace import JsonlTraceSink

DEFAULT_QUESTION = "What does this screen show, and what does it not establish?"

LABELS_NOTE = (
    "Model output: [visible] quotes the screenshot, [inferred] is a supported "
    "cause, [unknown] is what the screenshot does not establish. Verify before trusting."
)


@dataclass(frozen=True)
class Preview:
    trace_id: str
    width: int
    height: int
    byte_size: int
    sha256: str
    ingest_ms: float


def preview_image(
    image_path: Path,
    *,
    artifacts_root: Path,
    trace_id: str,
    retain: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Preview, CapturedFrame, EphemeralArtifactStore, PngIngestor]:
    """Normalize the selected PNG, store it privately, and measure ingest time."""
    store = EphemeralArtifactStore(artifacts_root, retain=retain)
    ingestor = PngIngestor(store)
    data = Path(image_path).read_bytes()
    started = clock()
    frame = ingestor.ingest_bytes(
        data,
        trace_id=trace_id,
        source=CaptureSource(kind="file", label=str(image_path)),
        duration_ms=0.0,
    )
    ingest_ms = (clock() - started) * 1000.0
    preview = Preview(
        trace_id=trace_id,
        width=frame.width,
        height=frame.height,
        byte_size=frame.byte_size or 0,
        sha256=frame.content_sha256 or "",
        ingest_ms=round(ingest_ms, 3),
    )
    return preview, frame, store, ingestor


def answer_frame(
    frame: CapturedFrame,
    question: str,
    *,
    adapter,
    trace_dir: Path,
    store: EphemeralArtifactStore,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Submit one question, record the trace, release the artifact, return results."""
    trace_path = Path(trace_dir) / f"{frame.trace_id}.jsonl"
    trace = JsonlTraceSink(
        trace_path,
        trace_id=frame.trace_id,
        kind=KIND_REAL,
        created_at_ms=clock() * 1000.0,
    )
    events: list[Event] = []

    def emit(event_type: str, state: str, payload: dict) -> None:
        events.append(
            Event(
                trace_id=frame.trace_id,
                event_id=f"e{len(events) + 1}",
                ts_ms=clock() * 1000.0,
                type=event_type,
                state=state,
                payload=payload,
            )
        )

    def finish_trace() -> None:
        for event in events:
            trace.emit(event)
        trace.write()

    emit(
        "preview",
        IDLE,
        {
            "width": frame.width,
            "height": frame.height,
            "byte_size": frame.byte_size,
            "sha256": frame.content_sha256,
        },
    )
    emit("model_started", ANALYSING, {"question": question})

    png_bytes = Path(frame.image_path).read_bytes() if frame.image_path else b""
    try:
        started = clock()
        answer, timings = adapter.predict_image(png_bytes, question)
        total_ms = (clock() - started) * 1000.0
    except KeyboardInterrupt:
        emit("cancelled", CANCELLED, {"reason": "user_interrupt"})
        finish_trace()
        store.release(frame)
        raise
    except Exception as exc:  # noqa: BLE001 - recorded here, re-raised for the CLI
        emit("failed", FAILED, {"reason": type(exc).__name__, "message": str(exc)[:200]})
        finish_trace()
        store.release(frame)
        raise

    emit(
        "answer",
        ANSWERING,
        {
            "visible": list(answer.visible),
            "inferred": list(answer.inferred),
            "unknown": list(answer.unknown),
        },
    )
    emit(
        "done",
        DONE,
        {
            "first_token_ms": timings.get("first_token_ms") if timings else None,
            "complete_ms": timings.get("complete_ms") if timings else None,
            "total_ms": round(total_ms, 3),
        },
    )
    finish_trace()
    store.release(frame)
    released = frame.image_path is None or not frame.image_path.exists()

    return {
        "trace_id": frame.trace_id,
        "trace_path": str(trace_path),
        "image": {
            "width": frame.width,
            "height": frame.height,
            "byte_size": frame.byte_size,
            "sha256": frame.content_sha256,
        },
        "timing_ms": {
            "first_token": timings.get("first_token_ms") if timings else None,
            "complete": timings.get("complete_ms") if timings else None,
            "total": round(total_ms, 3),
        },
        "answer": {
            "visible": list(answer.visible),
            "inferred": list(answer.inferred),
            "unknown": list(answer.unknown),
        },
        "labels_note": LABELS_NOTE,
        "released": released,
    }
