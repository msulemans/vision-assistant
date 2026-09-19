"""M008 multi-turn visual conversation over one current capture.

A session binds exactly one captured frame (identity: trace id + image
sha256); a second capture never inherits another session's history. Follow-ups
are answered against the same private artifact. History is bounded by turn
count and a transcript character budget (oldest turns dropped first), and an
idle capture raises a stale warning. Reset releases the artifact and closes
the session; asking afterwards is a typed error.

Traces: one JSONL per session (`session_started`, per-turn
`model_started`/`answer`/`done`, `session_reset`; failures record `failed`).
As in M006/M007, evidence fact text never enters traces.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .assistant import gather_evidence
from .capture import EphemeralArtifactStore
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
from .evidence import EvidencePort, EvidenceReport, facts_to_prompt
from .ports import CapturedFrame, LabelledAnswer
from .trace import JsonlTraceSink

MAX_TURNS = 12
MAX_CONTEXT_CHARS = 4000
STALE_AFTER_S = 900.0


class SessionError(RuntimeError):
    """Base class for typed conversation-session errors."""


class SessionClosed(SessionError):
    def __init__(self) -> None:
        super().__init__("session is closed; select a capture to start again")


class TurnLimitReached(SessionError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"turn limit of {limit} reached; reset to continue")


@dataclass(frozen=True)
class Turn:
    question: str
    answer: LabelledAnswer
    first_token_ms: float | None
    complete_ms: float | None


class ConversationSession:
    def __init__(
        self,
        frame: CapturedFrame,
        store: EphemeralArtifactStore,
        adapter: object,
        *,
        evidence_port: EvidencePort | None = None,
        evidence_zoom: int = 2,
        trace_dir: Path | None = None,
        max_turns: int = MAX_TURNS,
        max_context_chars: int = MAX_CONTEXT_CHARS,
        stale_after_s: float = STALE_AFTER_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.frame = frame
        self.store = store
        self.adapter = adapter
        self._evidence_port = evidence_port
        self._evidence_zoom = evidence_zoom
        self._max_turns = max_turns
        self._max_context_chars = max_context_chars
        self._stale_after_s = stale_after_s
        self._clock = clock
        self._turns: list[Turn] = []
        self._closed = False
        self._evidence_report: EvidenceReport | None = None
        self._evidence_loaded = False
        self._started_at = clock()
        self._last_activity = self._started_at
        self._sink: JsonlTraceSink | None = None
        self._events = 0
        if trace_dir is not None:
            self._sink = JsonlTraceSink(
                Path(trace_dir) / f"{frame.trace_id}.jsonl",
                trace_id=frame.trace_id,
                kind=KIND_REAL,
                created_at_ms=clock() * 1000.0,
            )
        self._emit(
            "session_started",
            IDLE,
            {
                "capture": self.capture_identity(),
                "policy": {
                    "max_turns": self._max_turns,
                    "max_context_chars": self._max_context_chars,
                    "stale_after_s": self._stale_after_s,
                },
            },
        )
        self._write_trace()

    # -- identity and state -------------------------------------------------

    def capture_identity(self) -> dict:
        """Trace-safe capture identity (no paths, no pixels)."""
        return {
            "trace_id": self.frame.trace_id,
            "sha256": self.frame.content_sha256,
            "width": self.frame.width,
            "height": self.frame.height,
        }

    def matches(self, frame: CapturedFrame) -> bool:
        """True when *frame* is the same capture (same content digest)."""
        return frame.content_sha256 == self.frame.content_sha256

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    def stale(self) -> bool:
        return (not self._closed) and (self._clock() - self._last_activity) > self._stale_after_s

    # -- prompt composition --------------------------------------------------

    def _compose(self, question: str) -> str:
        parts: list[str] = []
        if self._turns:
            lines: list[str] = []
            remaining = self._max_context_chars
            omitted = False
            for turn in reversed(self._turns):
                combined = " ".join(
                    (*turn.answer.visible, *turn.answer.inferred, *turn.answer.unknown)
                )
                block = f"Q: {turn.question}\nA: {combined}"
                if len(block) + 1 > remaining:
                    omitted = True
                    break
                lines.append(block)
                remaining -= len(block) + 1
            if omitted:
                lines.append("(earlier turns omitted)")
            transcript = "\n\n".join(reversed(lines))
            parts.append(
                "Transcript so far (same screenshot; answers are candidate claims):\n" + transcript
            )
        parts.append(f"Current question: {question}")
        if self._evidence_loaded and self._evidence_report is not None:
            block = facts_to_prompt(self._evidence_report)
            if block:
                parts.append(block)
        return "\n\n".join(parts)

    def _ensure_evidence(self) -> None:
        if self._evidence_port is None or self._evidence_loaded:
            return
        self._evidence_loaded = True
        png_bytes = Path(self.frame.image_path).read_bytes() if self.frame.image_path else b""
        try:
            self._evidence_report = gather_evidence(
                png_bytes, self._evidence_port, zoom_factor=self._evidence_zoom
            )
        except Exception as exc:  # noqa: BLE001 - augmentation is optional
            self._emit("evidence", ANALYSING, {"status": "failed", "reason": type(exc).__name__})
            return
        self._emit("evidence", ANALYSING, {"status": "collected", **self._evidence_report.summary()})

    # -- conversation loop ---------------------------------------------------

    def ask(self, question: str) -> dict:
        if self._closed:
            raise SessionClosed()
        if len(self._turns) >= self._max_turns:
            raise TurnLimitReached(self._max_turns)
        self._ensure_evidence()
        stale_warning = self.stale()
        turn_index = len(self._turns) + 1
        prompt = self._compose(question)
        png_bytes = Path(self.frame.image_path).read_bytes() if self.frame.image_path else b""

        self._emit(
            "model_started",
            ANALYSING,
            {"turn": turn_index, "question": question, "stale_warning": stale_warning},
        )
        started = self._clock()
        try:
            answer, timings = self.adapter.predict_image(png_bytes, prompt)
        except KeyboardInterrupt:
            self._emit("cancelled", CANCELLED, {"turn": turn_index, "reason": "user_interrupt"})
            self._write_trace()
            raise
        except Exception as exc:  # noqa: BLE001 - recorded here, re-raised for the caller
            self._emit("failed", FAILED, {"turn": turn_index, "reason": type(exc).__name__})
            self._write_trace()
            raise
        total_ms = (self._clock() - started) * 1000.0

        self._emit(
            "answer",
            ANSWERING,
            {
                "turn": turn_index,
                "visible": list(answer.visible),
                "inferred": list(answer.inferred),
                "unknown": list(answer.unknown),
            },
        )
        self._emit(
            "done",
            DONE,
            {
                "turn": turn_index,
                "first_token_ms": timings.get("first_token_ms") if timings else None,
                "complete_ms": timings.get("complete_ms") if timings else None,
                "total_ms": round(total_ms, 3),
            },
        )
        self._write_trace()
        self._turns.append(
            Turn(
                question=question,
                answer=answer,
                first_token_ms=timings.get("first_token_ms") if timings else None,
                complete_ms=timings.get("complete_ms") if timings else None,
            )
        )
        self._last_activity = self._clock()
        return {
            "turn": turn_index,
            "answer": {
                "visible": list(answer.visible),
                "inferred": list(answer.inferred),
                "unknown": list(answer.unknown),
            },
            "timing_ms": {
                "first_token": timings.get("first_token_ms") if timings else None,
                "complete": timings.get("complete_ms") if timings else None,
                "total": round(total_ms, 3),
            },
            "stale_warning": stale_warning,
            "turns_used": turn_index,
            "evidence": self._evidence_report.summary() if self._evidence_report else None,
        }

    def reset(self) -> bool:
        """Release the artifact and close the session. Returns artifact release."""
        if self._closed:
            return False
        self.store.release(self.frame)
        released = self.frame.image_path is None or not self.frame.image_path.exists()
        self._closed = True
        self._emit("session_reset", DONE, {"released": released, "turns": len(self._turns)})
        self._write_trace()
        return released

    # -- trace ---------------------------------------------------------------

    def _emit(self, event_type: str, state: str, payload: dict) -> None:
        if self._sink is None:
            return
        self._events += 1
        self._sink.emit(
            Event(
                trace_id=self.frame.trace_id,
                event_id=f"e{self._events}",
                ts_ms=self._clock() * 1000.0,
                type=event_type,
                state=state,
                payload=payload,
            )
        )

    def _write_trace(self) -> None:
        if self._sink is not None:
            self._sink.write()
