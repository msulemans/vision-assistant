"""Regression: Ctrl+C during model startup must stop the llama-server child.

Found by the M006 stop check: interrupting `adapter.start()` left an orphaned
server (and a leftover artifact) because only the generation phase handled
KeyboardInterrupt.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from vision_assistant.runtime_llamaserver import LlamaServerAdapter


class _FakeProcess:
    pid = 4242

    def __init__(self) -> None:
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:  # pragma: no cover - only used if terminate fails
        pass


class StartInterruptTest(unittest.TestCase):
    def test_interrupt_during_start_stops_server(self) -> None:
        process = _FakeProcess()
        adapter = LlamaServerAdapter(
            Path("model.gguf"),
            Path("mmproj.gguf"),
            port=61999,
            runner=lambda argv, **kwargs: process,
        )
        with mock.patch(
            "vision_assistant.runtime_llamaserver.urllib.request.urlopen",
            side_effect=KeyboardInterrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                adapter.start()
        self.assertTrue(process.terminated)
        self.assertIsNone(adapter._process)

    def test_stop_during_load_aborts_start_promptly(self) -> None:
        process = _FakeProcess()
        adapter = LlamaServerAdapter(
            Path("model.gguf"),
            Path("mmproj.gguf"),
            port=61999,
            runner=lambda argv, **kwargs: process,
        )

        def fake_urlopen(*args, **kwargs):
            adapter._process = None  # simulate stop() landing mid-load
            raise OSError("connection refused")

        with mock.patch(
            "vision_assistant.runtime_llamaserver.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), mock.patch("vision_assistant.runtime_llamaserver.time.sleep"):
            with self.assertRaises(RuntimeError) as caught:
                adapter.start(wait_s=60.0)
        self.assertIn("cancelled", str(caught.exception))
        self.assertIsNone(adapter._process)


if __name__ == "__main__":
    unittest.main()
