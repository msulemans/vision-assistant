"""M009 loopback UI server: the trusted side of the browser assistant.

Serves one dependency-free page plus a small JSON API. The server owns capture
ingest, the ephemeral artifact lifecycle, the M008 conversation session, the
model lifecycle, and traces. Security posture: binds 127.0.0.1 only, rejects
foreign Origins, caps request sizes, requires Content-Length, and never logs
request lines or bodies.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .capture import ImagePolicy, ImageValidationError
from .conversation import ConversationSession

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIN_DIR = REPO_ROOT / "models" / "qwen3.5-4b"
PAGE_PATH = Path(__file__).resolve().parent / "ui_page.html"
MAX_JSON_BYTES = 65536
_JSON_TYPE = "application/json"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class UiServerState:
    """Owns the current capture, the conversation session, and the model."""

    def __init__(
        self,
        *,
        adapter_factory,
        artifacts_root: Path,
        trace_dir: Path,
        evidence_port=None,
        max_capture_bytes: int | None = None,
    ) -> None:
        self.adapter_factory = adapter_factory
        self.artifacts_root = Path(artifacts_root)
        self.trace_dir = Path(trace_dir)
        self.evidence_port = evidence_port
        self.max_capture_bytes = max_capture_bytes or ImagePolicy().max_file_bytes
        self._lock = threading.Lock()
        self._ask_lock = threading.Lock()
        self._capture: tuple | None = None  # (frame, store)
        self._session: ConversationSession | None = None
        self._adapter = None

    # -- capture -------------------------------------------------------------

    def capture(self, png_bytes: bytes) -> dict:
        if not png_bytes:
            raise ApiError(400, "empty_body", "no image bytes were sent")
        if len(png_bytes) > self.max_capture_bytes:
            raise ApiError(413, "too_large", f"image exceeds {self.max_capture_bytes} bytes")
        from .assistant import preview_image

        trace_id = f"ui-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        fd, temp_name = tempfile.mkstemp(suffix=".png")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(png_bytes)
            try:
                preview, frame, store, _ = preview_image(
                    temp_path, artifacts_root=self.artifacts_root, trace_id=trace_id
                )
            except ImageValidationError as exc:
                raise ApiError(400, "invalid_image", str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)
        with self._lock:
            if self._capture is not None:
                old_frame, old_store = self._capture
                old_store.release(old_frame)
            self._session = None
            self._capture = (frame, store)
        return {
            "status": "captured",
            "token": frame.trace_id,
            "width": preview.width,
            "height": preview.height,
            "byte_size": preview.byte_size,
            "sha256": preview.sha256,
            "ingest_ms": preview.ingest_ms,
        }

    # -- ask -----------------------------------------------------------------

    def ask(self, token: str, question: str) -> dict:
        from .conversation import SessionClosed, TurnLimitReached

        question = question.strip()
        if not question:
            raise ApiError(400, "empty_question", "ask a question first")
        with self._ask_lock:
            with self._lock:
                if self._capture is None:
                    raise ApiError(409, "no_capture", "capture an image first")
                frame, store = self._capture
                if token != frame.trace_id:
                    raise ApiError(
                        409, "stale_capture", "that token belongs to a previous capture"
                    )
                if self._session is None:
                    adapter = self._ensure_adapter()
                    self._session = ConversationSession(
                        frame,
                        store,
                        adapter,
                        evidence_port=self.evidence_port,
                        trace_dir=self.trace_dir,
                    )
                session = self._session
            try:
                result = session.ask(question)
            except TurnLimitReached as exc:
                raise ApiError(409, "turn_limit", str(exc)) from exc
            except SessionClosed as exc:
                raise ApiError(409, "session_closed", str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - surfaced to the page as typed JSON
                raise ApiError(500, "model_error", f"{type(exc).__name__}: {exc}") from exc
            return {"status": "answered", **result}

    def _ensure_adapter(self):
        if self._adapter is None:
            try:
                self._adapter = self.adapter_factory()
                self._adapter.start()
            except Exception as exc:  # noqa: BLE001
                self._adapter = None
                raise ApiError(
                    503, "model_unavailable", f"{type(exc).__name__}: {exc}"
                ) from exc
        return self._adapter

    # -- reset / stop / status ------------------------------------------------

    def reset(self, token: str) -> dict:
        with self._lock:
            if self._capture is None:
                raise ApiError(409, "no_capture", "capture an image first")
            frame, store = self._capture
            if token != frame.trace_id:
                raise ApiError(409, "stale_capture", "that token belongs to a previous capture")
            session = self._session
            self._session = None
            self._capture = None
        if session is not None:
            released = session.reset()
        else:
            store.release(frame)
            released = frame.image_path is None or not frame.image_path.exists()
        return {"status": "reset", "released": released}

    def stop(self) -> dict:
        with self._lock:
            adapter = self._adapter
            self._adapter = None
            capture = self._capture
            self._session = None
            self._capture = None
        model_stopped = False
        if adapter is not None:
            adapter.stop()
            model_stopped = True
        released = True
        if capture is not None:
            frame, store = capture
            store.release(frame)
            released = frame.image_path is None or not frame.image_path.exists()
        return {"status": "stopped", "model_stopped": model_stopped, "released": released}

    def status(self) -> dict:
        with self._lock:
            capture = self._capture
            session = self._session
            model_running = self._adapter is not None
        return {
            "status": "ok",
            "capture": (
                {
                    "token": capture[0].trace_id,
                    "sha256": capture[0].content_sha256,
                    "width": capture[0].width,
                    "height": capture[0].height,
                }
                if capture is not None
                else None
            ),
            "turns": len(session.turns) if session is not None else 0,
            "stale": session.stale() if session is not None else False,
            "model_running": model_running,
            "busy": self._ask_lock.locked(),
        }

    def shutdown(self) -> None:
        with self._lock:
            adapter = self._adapter
            self._adapter = None
            capture = self._capture
            self._capture = None
            self._session = None
        if adapter is not None:
            adapter.stop()
        if capture is not None:
            capture[1].release(capture[0])


class UiRequestHandler(BaseHTTPRequestHandler):
    server_version = "VisionAssistantUI/1.0"
    timeout = 20

    def log_message(self, *args) -> None:  # never log request lines or bodies
        pass

    @property
    def state(self) -> UiServerState:
        return self.server.state  # type: ignore[attr-defined]

    # -- helpers ------------------------------------------------------------

    def _allowed_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        port = self.server.server_address[1]  # type: ignore[attr-defined]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", _JSON_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _forbidden_origin(self) -> None:
        self._send_json(
            403,
            {
                "status": "failed",
                "code": "forbidden_origin",
                "message": "requests must come from this loopback page",
            },
        )

    def _not_found(self) -> None:
        self._send_json(404, {"status": "failed", "code": "not_found", "message": "unknown path"})

    def _read_body(self, limit: int) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None:
            raise ApiError(411, "length_required", "Content-Length is required")
        try:
            size = int(length)
        except ValueError as exc:
            raise ApiError(400, "bad_length", "invalid Content-Length") from exc
        if size < 0 or size > limit:
            raise ApiError(413, "too_large", f"body exceeds {limit} bytes")
        return self.rfile.read(size)

    def _front_page(self) -> None:
        page = PAGE_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    # -- routes ---------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if not self._allowed_origin():
            self._forbidden_origin()
            return
        if self.path in ("/", "/index.html"):
            self._front_page()
            return
        if self.path == "/api/status":
            self._send_json(200, self.state.status())
            return
        self._not_found()

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if not self._allowed_origin():
            self._forbidden_origin()
            return
        try:
            if self.path == "/api/capture":
                body = self._read_body(self.state.max_capture_bytes)
                self._send_json(200, self.state.capture(body))
                return
            if self.path in ("/api/ask", "/api/reset"):
                try:
                    payload = json.loads(self._read_body(MAX_JSON_BYTES) or b"{}")
                except json.JSONDecodeError:
                    self._send_json(
                        400,
                        {"status": "failed", "code": "bad_json", "message": "invalid JSON body"},
                    )
                    return
                if not isinstance(payload, dict):
                    raise ApiError(400, "bad_request", "a JSON object is required")
                token = str(payload.get("token") or "")
                if self.path == "/api/ask":
                    question = str(payload.get("question") or "")
                    self._send_json(200, self.state.ask(token, question))
                else:
                    self._send_json(200, self.state.reset(token))
                return
            if self.path == "/api/stop":
                self._read_body(MAX_JSON_BYTES)  # drain any body
                self._send_json(200, self.state.stop())
                return
            self._not_found()
        except ApiError as exc:
            self._send_json(
                exc.status, {"status": "failed", "code": exc.code, "message": exc.message}
            )


class UiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, state: UiServerState) -> None:
        super().__init__(address, UiRequestHandler)
        self.state = state


def _default_adapter_factory(pin_dir: Path, ctx_size: int):
    def factory():
        from .runtime_llamaserver import LlamaServerAdapter

        pin = json.loads((pin_dir / "pin.json").read_text(encoding="utf-8"))
        model = next(f for f in pin["files"] if f["role"] == "model")
        mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")
        return LlamaServerAdapter(
            pin_dir / model["name"],
            pin_dir / mmproj["name"],
            ctx_size=ctx_size,
            jinja=True,
            chat_template_kwargs={"enable_thinking": False},
            log_path=REPO_ROOT / "runs" / "ui-server.log",
        )

    return factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M009 local UI server (127.0.0.1 only)")
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument("--pin-dir", type=Path, default=DEFAULT_PIN_DIR)
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--evidence-ocr", action="store_true", help="include M007 OCR facts")
    parser.add_argument("--open", action="store_true", help="open the page in the browser")
    parser.add_argument(
        "--artifacts-root", type=Path, default=REPO_ROOT / "runs" / "m009-artifacts"
    )
    parser.add_argument("--trace-dir", type=Path, default=REPO_ROOT / "runs" / "m009")
    args = parser.parse_args(argv)

    if not (args.pin_dir / "pin.json").exists():
        print(json.dumps({"status": "failed", "reason": f"no pin at {args.pin_dir / 'pin.json'}"}))
        return 1

    evidence_port = None
    if args.evidence_ocr:
        from .ocr_vision import VisionOcrAdapter

        evidence_port = VisionOcrAdapter()

    state = UiServerState(
        adapter_factory=_default_adapter_factory(args.pin_dir, args.ctx_size),
        artifacts_root=args.artifacts_root,
        trace_dir=args.trace_dir,
        evidence_port=evidence_port,
    )
    server = UiServer(("127.0.0.1", args.port), state)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Vision Assistant UI on {url} (loopback only; Ctrl+C stops everything)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.shutdown()
        server.server_close()
    print(json.dumps({"status": "stopped"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
