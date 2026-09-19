from __future__ import annotations

import http.client
import json
import struct
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

from vision_assistant.capture import PNG_SIGNATURE, _png_chunk
from vision_assistant.ports import LabelledAnswer
from vision_assistant.ui_server import UiServer, UiServerState


def _make_png(width: int = 24, height: int = 16) -> bytes:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


class _FakeAdapter:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def predict_image(self, png_bytes: bytes, question: str):
        self.prompts.append(question)
        answer = LabelledAnswer(visible=("VISIBLE",), inferred=(), unknown=())
        return answer, {"first_token_ms": 1.0, "complete_ms": 2.0}


class UiServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.adapters: list[_FakeAdapter] = []

        def factory() -> _FakeAdapter:
            adapter = _FakeAdapter()
            self.adapters.append(adapter)
            return adapter

        state = UiServerState(
            adapter_factory=factory,
            artifacts_root=self.root / "artifacts",
            trace_dir=self.root / "traces",
        )
        self.server = UiServer(("127.0.0.1", 0), state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.state.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def _request(self, method: str, path: str, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response.status, payload

    def _capture(self, png: bytes | None = None):
        status, payload = self._request(
            "POST", "/api/capture", png or _make_png(), {"Content-Type": "image/png"}
        )
        return status, json.loads(payload)

    def _post_json(self, path: str, payload: dict):
        status, body = self._request(
            "POST", path, json.dumps(payload), {"Content-Type": "application/json"}
        )
        return status, json.loads(body)

    def test_capture_ask_follow_up_reset_cycle(self) -> None:
        status, captured = self._capture()
        self.assertEqual(status, 200)
        self.assertEqual(captured["status"], "captured")
        token = captured["token"]
        artifact = self.root / "artifacts" / token / "frame.png"
        self.assertTrue(artifact.exists())

        status, first = self._post_json(
            "/api/ask", {"token": token, "question": "what is shown?"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(first["turn"], 1)
        self.assertEqual(first["answer"]["visible"], ["VISIBLE"])

        status, second = self._post_json(
            "/api/ask", {"token": token, "question": "and what is unknown?"}
        )
        self.assertEqual(second["turn"], 2)
        self.assertIn("Transcript so far", self.adapters[0].prompts[1])

        status, payload = self._request("GET", "/api/status")
        state = json.loads(payload)
        self.assertEqual(state["turns"], 2)
        self.assertTrue(state["model_running"])
        self.assertEqual(state["capture"]["token"], token)

        status, released = self._post_json("/api/reset", {"token": token})
        self.assertTrue(released["released"])
        self.assertFalse(artifact.exists())

    def test_stop_releases_capture_and_model(self) -> None:
        _status, captured = self._capture()
        self._post_json("/api/ask", {"token": captured["token"], "question": "hi"})
        status, payload = self._request("POST", "/api/stop")
        stopped = json.loads(payload)
        self.assertEqual(status, 200)
        self.assertTrue(stopped["model_stopped"])
        self.assertTrue(stopped["released"])
        self.assertTrue(self.adapters[0].stopped)
        self.assertFalse((self.root / "artifacts" / captured["token"] / "frame.png").exists())
        _status, payload = self._request("GET", "/api/status")
        self.assertIsNone(json.loads(payload)["capture"])

    def test_foreign_origin_is_rejected(self) -> None:
        status, _payload = self._request("GET", "/", headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, page = self._request(
            "GET", "/", headers={"Origin": f"http://127.0.0.1:{self.port}"}
        )
        self.assertEqual(status, 200)
        self.assertIn(b"Vision Assistant", page)

    def test_typed_failures(self) -> None:
        status, payload = self._capture(b"definitely not a png")
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "invalid_image")

        status, payload = self._post_json("/api/ask", {"token": "none", "question": "?"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "no_capture")

        _status, captured = self._capture()
        status, payload = self._post_json(
            "/api/ask", {"token": "old-token", "question": "?"}
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "stale_capture")
        self.assertNotEqual(captured["token"], "old-token")

        self.server.state.max_capture_bytes = 100
        status, _payload = self._capture(_make_png(48, 32))
        self.assertEqual(status, 413)

    def test_status_starts_idle(self) -> None:
        status, payload = self._request("GET", "/api/status")
        self.assertEqual(status, 200)
        state = json.loads(payload)
        self.assertIsNone(state["capture"])
        self.assertFalse(state["model_running"])


if __name__ == "__main__":
    unittest.main()
