from __future__ import annotations

import itertools
from dataclasses import asdict

from .clock import FakeClock
from .events import (
    ANALYSING,
    ANSWERING,
    CANCELLED,
    CAPTURING,
    DONE,
    FAILED,
    IDLE,
    KIND_DETERMINISTIC,
    SELECTING,
    TERMINAL_STATES,
    TIMED_OUT,
    Event,
)
from .ports import CaptureSource
from .trace import JsonlTraceSink

POLICY_MS = 5.0


class ReadOnlyTurn:
    """Drives one deterministic read-only visual turn.

    The turn owns the state machine and emits a versioned event for every
    meaningful transition. Cancellation, timeout, and failure are first-class
    outcomes, and cancellation prevents any later model/UI event from
    appearing in the trace.
    """

    def __init__(
        self,
        *,
        trace_id: str,
        clock: FakeClock,
        capture,
        model,
        policy,
        sink: JsonlTraceSink,
        timeout_ms: float | None = None,
    ) -> None:
        self.trace_id = trace_id
        self._clock = clock
        self._capture = capture
        self._model = model
        self._policy = policy
        self._sink = sink
        self._timeout_ms = timeout_ms
        self._state = IDLE
        self._cancelled = False
        self._cancel_after_emit: str | None = None
        self._event_ids = itertools.count(1)
        self._started_ms: float | None = None

    @property
    def state(self) -> str:
        return self._state

    def _emit(self, event_type: str, state: str, **payload) -> None:
        ts = self._clock.now_ms()
        if self._started_ms is None:
            self._started_ms = ts
        event = Event(
            trace_id=self.trace_id,
            event_id=f"e{next(self._event_ids):06d}",
            ts_ms=ts,
            type=event_type,
            state=state,
            payload=payload,
        )
        self._sink.emit(event)
        if self._cancel_after_emit == event_type:
            self._cancelled = True

    def _transition(self, state: str) -> None:
        if self._state in TERMINAL_STATES and state != self._state:
            raise RuntimeError(f"cannot move from terminal state {self._state!r}")
        self._state = state

    def _check_timeout(self) -> bool:
        if self._timeout_ms is None or self._started_ms is None:
            return False
        return (self._clock.now_ms() - self._started_ms) > self._timeout_ms

    def _finish_cancel(self) -> str:
        self._transition(CANCELLED)
        self._emit("turn.cancelled", CANCELLED, final_state=CANCELLED)
        return CANCELLED

    def _finish_timeout(self, reason: str) -> str:
        self._transition(TIMED_OUT)
        self._emit("turn.timed_out", TIMED_OUT, final_state=TIMED_OUT, reason=reason)
        return TIMED_OUT

    def _finish_failed(self, reason: str) -> str:
        self._transition(FAILED)
        self._emit("turn.failed", FAILED, final_state=FAILED, reason=reason)
        return FAILED

    def run(
        self,
        *,
        source: CaptureSource,
        question: str,
        cancel_after_emit: str | None = None,
    ) -> str:
        """Run the read-only turn and return the terminal state.

        *cancel_after_emit* offers a deterministic hook to request cancellation
        right after a given event type has been emitted. It is used only to
        exercise the cancel path in the deterministic vertical slice.
        """
        if self._state != IDLE:
            raise RuntimeError(f"turn already started (state={self._state!r})")
        self._cancel_after_emit = cancel_after_emit
        self._started_ms = self._clock.now_ms()

        # SELECTING
        self._transition(SELECTING)
        self._emit(
            "turn.started",
            SELECTING,
            source=asdict(source),
            question=question,
            kind=KIND_DETERMINISTIC,
        )

        # CAPTURING
        self._transition(CAPTURING)
        self._emit("capture.requested", CAPTURING, source_kind=source.kind, source_label=source.label)
        try:
            frame = self._capture.capture(trace_id=self.trace_id, source=source)
        except Exception as exc:  # noqa: BLE001 - capture failure is an expected outcome
            return self._finish_failed(f"capture: {exc}")
        self._clock.advance(frame.duration_ms)
        if self._cancelled:
            return self._finish_cancel()
        if self._check_timeout():
            return self._finish_timeout("capture exceeded budget")
        self._emit(
            "capture.frame_ready",
            CAPTURING,
            width=frame.width,
            height=frame.height,
            fixture_id=frame.fixture_id,
            duration_ms=frame.duration_ms,
            source_kind=source.kind,
            source_label=source.label,
        )

        # ANALYSING
        self._transition(ANALYSING)
        self._emit("model.started", ANALYSING, image_ref=frame.fixture_id, question=question)
        try:
            output = self._model.generate(image_ref=frame.fixture_id, question=question)
        except Exception as exc:  # noqa: BLE001 - model failure is an expected outcome
            return self._finish_failed(f"model: {exc}")
        self._clock.advance(output.stats.first_token_ms)
        if self._cancelled:
            return self._finish_cancel()
        if self._check_timeout():
            return self._finish_timeout("model exceeded budget")
        self._emit("model.first_token", ANALYSING, first_token_ms=output.stats.first_token_ms)

        # ANSWERING (streamed)
        self._transition(ANSWERING)
        for index, chunk in enumerate(output.chunks):
            self._clock.advance(chunk.duration_ms)
            if self._cancelled:
                return self._finish_cancel()
            if self._check_timeout():
                return self._finish_timeout("model exceeded budget")
            self._emit("model.token", ANSWERING, index=index, text=chunk.text, duration_ms=chunk.duration_ms)

        # Trusted answer policy labels the model's untrusted candidate.
        self._clock.advance(POLICY_MS)
        answer = self._policy.label(output.raw_statements, question)
        total_ms = self._clock.now_ms() - self._started_ms
        self._emit(
            "answer.ready",
            ANSWERING,
            visible=list(answer.visible),
            inferred=list(answer.inferred),
            unknown=list(answer.unknown),
            first_token_ms=output.stats.first_token_ms,
            answer_complete_ms=output.stats.answer_complete_ms,
            total_ms=total_ms,
        )

        self._transition(DONE)
        self._emit("turn.completed", DONE, final_state=DONE, total_ms=total_ms)
        return DONE
