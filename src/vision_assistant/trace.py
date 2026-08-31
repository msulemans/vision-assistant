from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .events import Event, SCHEMA_VERSION

# Keys that must never be written to a trace. Milestone 002 has no real pixel
# or sensitive data, but the redaction path is exercised as a contract.
REDACTED_KEYS = frozenset(
    {"pixels", "raw_image", "raw_text", "sensitive", "secret", "password", "token", "path"}
)


def redact(payload: dict) -> dict:
    """Return a copy of *payload* with sensitive keys replaced by "[redacted]".

    Works recursively on nested dicts. Lists are walked elementwise.
    """
    out: dict = {}
    for key, value in payload.items():
        if key.lower() in REDACTED_KEYS:
            out[key] = "[redacted]"
        elif isinstance(value, dict):
            out[key] = redact(value)
        elif isinstance(value, (list, tuple)):
            out[key] = [redact(item) if isinstance(item, dict) else item for item in value]
        else:
            out[key] = value
    return out


def _dumps(record: dict) -> str:
    # Deterministic, compact, key-sorted JSON so byte-identical traces repeat.
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


class JsonlTraceSink:
    """Writes a deterministic JSONL trace: a meta line plus one event per line."""

    def __init__(
        self,
        path: Path,
        *,
        trace_id: str,
        kind: str = "deterministic",
        created_at_ms: float | None = None,
    ) -> None:
        self._path = Path(path)
        self._trace_id = trace_id
        self._kind = kind
        self._created_at_ms = created_at_ms if created_at_ms is not None else 0.0
        self._lines: list[str] = []
        self._closed = False

    def meta(self) -> dict:
        return {
            "type": "meta",
            "schema_version": SCHEMA_VERSION,
            "trace_id": self._trace_id,
            "kind": self._kind,
            "created_at_ms": self._created_at_ms,
        }

    def emit(self, event: Event) -> None:
        if self._closed:
            raise RuntimeError("trace sink is already closed")
        record = asdict(event)
        record["payload"] = redact(record["payload"])
        self._lines.append(_dumps(record))

    def write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        header = _dumps(self.meta())
        self._path.write_text("\n".join([header, *self._lines]) + "\n", encoding="utf-8")

    def read_back(self) -> list[dict]:
        """Parse the written JSONL back into records (round-trip check)."""
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def close(self) -> None:
        self._closed = True
