"""Process-tree RSS and swap sampling for bake-off resource gates.

`docs/METRICS.md` requires peak active memory and swap growth to be measured
with a recorded method. This module samples with the system tools already
present on macOS (`ps`, `sysctl`) so the package keeps its stdlib-only rule.
Parse functions are pure and unit-tested with fixed inputs; the sampler has a
background-thread wrapper for use during a model run.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Callable

_PS_RSS = re.compile(r"^\s*(\d+)\s*$")
_SWAP_USED = re.compile(r"used\s*=\s*([0-9.]+)M")


def parse_ps_rss_mib(text: str) -> float:
    """Sum `ps -o rss=` output (KiB rows, one per line) into MiB."""
    total_kib = 0
    for line in text.splitlines():
        match = _PS_RSS.match(line)
        if match:
            total_kib += int(match.group(1))
    return total_kib / 1024.0


def parse_swap_used_mib(text: str) -> float:
    """Parse `sysctl -n vm.swapusage` ("used = 512.25M") into MiB."""
    match = _SWAP_USED.search(text)
    return float(match.group(1)) if match else 0.0


class ProcessTreeSampler:
    """Samples a process tree's resident set size via `ps` (no dependencies)."""

    def __init__(self, pid: int, runner: Callable[..., object] = subprocess.run) -> None:
        self.pid = int(pid)
        self._runner = runner

    def _ps(self, *args: str) -> str:
        result = self._runner(["ps", *args], capture_output=True, text=True, check=False)
        return getattr(result, "stdout", "") or ""

    def pids(self) -> list[int]:
        children = self._ps("-o", "pid=", "--ppid", str(self.pid)).split()
        return [self.pid, *(int(child) for child in children if child.isdigit())]

    def sample_mib(self) -> float:
        total = 0.0
        for pid in self.pids():
            total += parse_ps_rss_mib(self._ps("-o", "rss=", "-p", str(pid)))
        return total


def swap_used_mib(runner: Callable[..., object] = subprocess.run) -> float:
    """Current swap used on macOS, in MiB."""
    result = runner(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, check=False)
    return parse_swap_used_mib(getattr(result, "stdout", "") or "")


class PeakSampler:
    """Samples a process tree in the background and keeps the peak RSS (MiB).

    Also records starting and ending swap so the caller can report swap growth.
    """

    def __init__(
        self,
        pid: int,
        *,
        interval_s: float = 1.0,
        tree: ProcessTreeSampler | None = None,
        swap_reader: Callable[[], float] = swap_used_mib,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tree = tree if tree is not None else ProcessTreeSampler(pid)
        self._interval_s = interval_s
        self._swap_reader = swap_reader
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_mib = 0.0
        self.swap_start_mib = 0.0
        self.swap_end_mib = 0.0

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak_mib = max(self.peak_mib, self._tree.sample_mib())
            self._stop.wait(self._interval_s)

    def start(self) -> None:
        self.swap_start_mib = self._swap_reader()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_s + 5)
        self.swap_end_mib = self._swap_reader()
