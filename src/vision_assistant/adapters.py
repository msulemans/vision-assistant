from __future__ import annotations

from .fixture import SyntheticFixture
from .ports import (
    CapturedFrame,
    CaptureSource,
    LabelledAnswer,
    ModelOutput,
    OutputStats,
    TokenChunk,
)


class FakeCapturePort:
    """Fake capture: never touches real pixels or macOS privacy permissions.

    It closes over a synthetic fixture so the frame metadata (dimensions,
    fixture id) belongs to trusted, generated content only.
    """

    def __init__(self, fixture: SyntheticFixture, *, duration_ms: float = 12.0) -> None:
        self._fixture = fixture
        self._duration_ms = duration_ms

    def capture(self, *, trace_id: str, source: CaptureSource) -> CapturedFrame:
        return CapturedFrame(
            trace_id=trace_id,
            source=source,
            width=self._fixture.width,
            height=self._fixture.height,
            duration_ms=self._duration_ms,
            fixture_id=self._fixture.id,
        )


class FailingCapturePort:
    """A capture adapter that raises, used to exercise the FAILED path."""

    def __init__(self, *, message: str = "simulated capture failure") -> None:
        self._message = message

    def capture(self, *, trace_id: str, source: CaptureSource) -> CapturedFrame:
        raise RuntimeError(self._message)


class FakeVisionModelPort:
    """A fake, deterministic model.

    Returns streamed token chunks plus raw, UNTRUSTED statements. Statements
    carry a leading tag ("Visible:", "Inferred:", "Unknown:") that the answer
    policy later maps to labelled sections. Nothing here is a real model.
    """

    # fmt: off
    _TOKENS = (
        "A dialog titled ",
        "\u201cConnect to Database\u201d ",
        "is visible. It asks you to ",
        "confirm the connection before continuing.",
    )
    _STATEMENTS = (
        "Visible: A dialog titled \u201cConnect to Database\u201d is visible.",
        "Visible: A red hint is shown next to the second input field.",
        "Inferred: The service may need a password before connecting.",
        "Unknown: The root cause is not fully determined from the image.",
    )
    # fmt: on

    def __init__(self, *, pre_token_ms: float = 95.0, chunk_durations: tuple[float, ...] = (30.0, 25.0, 28.0, 22.0)) -> None:
        self._pre_token_ms = pre_token_ms
        self._chunk_durations = chunk_durations

    def generate(self, *, image_ref: str, question: str) -> ModelOutput:
        chunks = tuple(
            TokenChunk(text=text, duration_ms=self._chunk_durations[(i % len(self._chunk_durations))])
            for i, text in enumerate(self._TOKENS)
        )
        complete_ms = self._pre_token_ms + sum(chunk.duration_ms for chunk in chunks)
        return ModelOutput(
            chunks=chunks,
            raw_statements=self._STATEMENTS,
            stats=OutputStats(
                first_token_ms=self._pre_token_ms,
                answer_complete_ms=complete_ms,
                chunk_count=len(chunks),
            ),
        )


class FakeAnswerPolicy:
    """Maps an untrusted model answer to labelled evidence/inference/unknown.

    The label is derived deterministically from the leading tag in each raw
    statement. It is a stand-in for the real policy that will later enforce
    what may (and may not) be claimed from screen evidence.
    """

    _PREFIX = {"Visible": "visible", "Inferred": "inferred", "Unknown": "unknown"}

    def label(self, raw_statements: tuple[str, ...], question: str) -> LabelledAnswer:
        buckets: dict[str, list[str]] = {"visible": [], "inferred": [], "unknown": []}
        for statement in raw_statements:
            tag, _, text = statement.partition(":")
            section = self._PREFIX.get(tag.strip(), "unknown")
            buckets[section].append(text.strip() if text.strip() else statement)
        return LabelledAnswer(
            visible=tuple(buckets["visible"]),
            inferred=tuple(buckets["inferred"]),
            unknown=tuple(buckets["unknown"]),
        )
