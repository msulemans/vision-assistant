from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"
KIND_DETERMINISTIC = "deterministic"
KIND_REAL = "real"

# Read-only turn state machine states. Terminal states are final.
IDLE = "idle"
SELECTING = "selecting"
CAPTURING = "capturing"
ANALYSING = "analysing"
ANSWERING = "answering"
DONE = "done"
CANCELLED = "cancelled"
TIMED_OUT = "timed_out"
FAILED = "failed"

TERMINAL_STATES = frozenset({DONE, CANCELLED, TIMED_OUT, FAILED})


@dataclass(frozen=True)
class Event:
    """A single versioned event in the deterministic event envelope."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str = ""
    event_id: str = ""
    ts_ms: float = 0.0
    type: str = ""
    state: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
