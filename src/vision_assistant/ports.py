from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CaptureSource:
    """What the user explicitly selected to capture."""

    kind: str  # "file" | "region" | "window" | "display"
    label: str


@dataclass(frozen=True)
class CapturedFrame:
    """Metadata describing a captured frame. No raw pixels are stored here."""

    trace_id: str
    source: CaptureSource
    width: int
    height: int
    duration_ms: float
    fixture_id: str
    image_path: Path | None = None
    mime_type: str = "image/png"
    byte_size: int = 0
    content_sha256: str = ""
    ephemeral: bool = True

    @property
    def model_ref(self) -> str:
        """Internal model reference. It must never be copied into a trace."""
        return str(self.image_path) if self.image_path is not None else self.fixture_id


class CaptureFailure(RuntimeError):
    """Expected, user-recoverable capture outcome with a stable code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TokenChunk:
    text: str
    duration_ms: float


@dataclass(frozen=True)
class OutputStats:
    """Timings relative to model start (milliseconds)."""

    first_token_ms: float
    answer_complete_ms: float
    chunk_count: int


@dataclass(frozen=True)
class ModelOutput:
    """A model's untrusted answer candidate: streamed chunks plus raw
    statements, plus timings. Statements are labelled only by the policy."""

    chunks: tuple[TokenChunk, ...]
    raw_statements: tuple[str, ...]
    stats: OutputStats


@dataclass(frozen=True)
class LabelledAnswer:
    visible: tuple[str, ...]
    inferred: tuple[str, ...]
    unknown: tuple[str, ...]


@runtime_checkable
class Clock(Protocol):
    def now_ms(self) -> float: ...

    def advance(self, ms: float) -> float: ...


@runtime_checkable
class CapturePort(Protocol):
    def capture(self, *, trace_id: str, source: CaptureSource) -> CapturedFrame: ...


@runtime_checkable
class VisionModelPort(Protocol):
    def generate(self, *, image_ref: str, question: str) -> ModelOutput: ...


@runtime_checkable
class AnswerPolicy(Protocol):
    def label(self, raw_statements: tuple[str, ...], question: str) -> LabelledAnswer: ...
