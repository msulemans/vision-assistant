from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeClock:
    """A deterministic, injectable clock for the fake vertical slice.

    Time is monotonic milliseconds from a fixed origin. The turn orchestrator
    advances the clock by each reported stage duration so the emitted trace is
    exact and reproducible across runs.
    """

    epoch_ms: int = 1_750_000_000_000
    _now_ms: float | None = None

    def __post_init__(self) -> None:
        if self._now_ms is None:
            self._now_ms = float(self.epoch_ms)

    def now_ms(self) -> float:
        assert self._now_ms is not None
        return self._now_ms

    def advance(self, ms: float) -> float:
        assert self._now_ms is not None
        self._now_ms += ms
        return self._now_ms
