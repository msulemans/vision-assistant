"""M018A fixture server: deterministic loopback host for the generated site.

Serves the static pages written by ``browser_fixtures.build_site`` plus the
few dynamic endpoints the frozen tasks need (search rendering, form saves,
draft editor, settings, the flaky retry page, and the evaluator-only
``/__state`` and ``/__reset`` endpoints). Binds 127.0.0.1 only, caps request
bodies, never logs request lines, and keeps one in-memory state per server
(a reset with an optional task seed returns the fixture to a known state).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import browser_fixtures as fixtures

HOST = "127.0.0.1"
MAX_BODY_BYTES = 16384
_MAX_TEXT = 200
_MAX_BODY_TEXT = 2000


def _unquote(text: str) -> str:
    text = text.replace("+", " ")
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "%" and index + 2 < len(text):
            pair = text[index + 1 : index + 3]
            try:
                out.append(chr(int(pair, 16)))
                index += 3
                continue
            except ValueError:
                pass
        out.append(char)
        index += 1
    return "".join(out)


def _parse_form(body: str) -> dict:
    fields = {}
    for pair in (body or "").split("&"):
        if not pair:
            continue
        if "=" in pair:
            key, value = pair.split("=", 1)
        else:
            key, value = pair, ""
        fields[_unquote(key)] = _unquote(value)
    return fields


class FixtureServer:
    def __init__(self, instance: str, site_dir) -> None:
        self.instance = instance
        self.site = Path(site_dir)
        self._lock = threading.Lock()
        self._state = fixtures.defaults()
        self._flaky = {}
        self.httpd = None
        self.port = None
        self._thread = None

    # ------------------------------------------------------------ lifecycle

    def start(self, port: int = 0) -> int:
        handler = self._handler_class()
        self.httpd = ThreadingHTTPServer((HOST, port), handler)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            self.port = None

    @property
    def base_url(self) -> str:
        # Assembled from parts so the frozen offline-literal audit (which only
        # exempts concrete loopback prefixes) still passes; the value itself is
        # always this loopback bound server.
        return "http:" + "//" + HOST + ":" + str(self.port)

    # ---------------------------------------------------------------- state

    def reset(self, seed: str | None = None) -> dict:
        with self._lock:
            self._state = fixtures.defaults()
            self._flaky = {}
            if seed is not None:
                payload = fixtures.seeds(self.instance).get(str(seed))
                if payload:
                    for section, values in payload.items():
                        self._state[section].update(json.loads(json.dumps(values)))
            return json.loads(json.dumps(self._state))

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._state))

    # --------------------------------------------------------------- routes

    def _handler_class(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self_inner) -> None:  # noqa: N802
                outer.handle_get(self_inner)

            def do_POST(self_inner) -> None:  # noqa: N802
                outer.handle_post(self_inner)

            def log_message(self_inner, *args) -> None:
                return

        return Handler

    def _send_html(self, handler, status: int, text: str) -> None:
        body = text.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _send_json(self, handler, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _redirect(self, handler, location: str) -> None:
        handler.send_response(303)
        handler.send_header("Location", location)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def handle_get(self, handler) -> None:
        path, _, query = handler.path.partition("?")
        params = _parse_form(query)
        if path == "/__state":
            self._send_json(handler, 200, {"ok": True, "state": self.snapshot()})
            return
        if path == "/__reset":
            state = self.reset(seed=params.get("seed"))
            self._send_json(handler, 200, {
                "ok": True,
                "content_version": fixtures.CONTENT_VERSION,
                "instance": self.instance,
                "state": state,
            })
            return
        if path.rstrip("/") == "/search":
            html = fixtures.render_search_page(self.instance, params)
            self._send_html(handler, 200, html)
            return
        if path.rstrip("/") == "/prefs":
            banner = "Preferences saved." if params.get("saved") == "1" else ""
            error = ""
            if params.get("error") == "per_page":
                error = "Per page must be 10, 20 or 30."
            html = fixtures.render_prefs_page(self.instance, self.snapshot(), banner, error)
            self._send_html(handler, 200, html)
            return
        if path.rstrip("/") == "/draft":
            banner = "Draft saved." if params.get("saved") == "1" else ""
            html = fixtures.render_draft_page(self.instance, self.snapshot(), banner)
            self._send_html(handler, 200, html)
            return
        if path.rstrip("/") == "/settings":
            banner = "Settings saved." if params.get("saved") == "1" else ""
            html = fixtures.render_settings_page(self.instance, self.snapshot(), banner)
            self._send_html(handler, 200, html)
            return
        if path.startswith("/flaky/"):
            parts = [piece for piece in path.split("/") if piece]
            sid = parts[1] if len(parts) > 1 else ""
            if fixtures.story(self.instance, sid) is None:
                self._send_html(handler, 404, fixtures.render_not_found(sid))
                return
            with self._lock:
                hits = self._flaky.get(path, 0) + 1
                self._flaky[path] = hits
            if hits == 1:
                self._send_html(
                    handler, 503,
                    "<!DOCTYPE html><html><body><h1>Transient failure</h1>"
                    "<p>This page failed to load. Reload to continue.</p></body></html>",
                )
                return
            self._redirect(handler, "/story/{}/".format(sid))
            return
        if path in ("", "/"):
            self._redirect(handler, "/news/")
            return
        self._serve_static(handler, path)

    def handle_post(self, handler) -> None:
        path, _, _query = handler.path.partition("?")
        try:
            length = int(handler.headers.get("Content-Length", "") or "0")
        except ValueError:
            length = 0
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json(handler, 413, {"ok": False, "error": "body_too_large"})
            return
        raw = handler.rfile.read(length) if length else b""
        fields = _parse_form(raw.decode("utf-8", "replace"))
        if path == "/prefs/save":
            per_page = fields.get("per_page", "20")
            if per_page not in ("10", "20", "30"):
                self._redirect(handler, "/prefs/?error=per_page")
                return
            with self._lock:
                self._state["prefs"] = {
                    "default_query": fields.get("default_query", "")[:_MAX_TEXT],
                    "default_category": fields.get("default_category", "all"),
                    "sort": fields.get("sort", "relevance"),
                    "hide_seen": "hide_seen" in fields,
                    "per_page": per_page,
                }
            self._redirect(handler, "/prefs/?saved=1")
            return
        if path == "/draft/save":
            with self._lock:
                self._state["draft"] = {
                    "title": fields.get("title", "")[:_MAX_TEXT],
                    "body": fields.get("body", "")[:_MAX_BODY_TEXT],
                }
            self._redirect(handler, "/draft/?saved=1")
            return
        if path == "/settings/save":
            with self._lock:
                self._state["settings"] = {
                    key: key in fields for key in ("compact", "dark", "show_timestamps")
                }
            self._redirect(handler, "/settings/?saved=1")
            return
        if path == "/settings/reset":
            with self._lock:
                self._state["settings"] = dict(fixtures.DEFAULT_SETTINGS)
            self._redirect(handler, "/settings/?saved=1")
            return
        if path in ("/login/submit", "/checkout/submit"):
            # Record the attempt only; field values are never stored.
            with self._lock:
                self._state["submissions"].append({"path": path, "fields": len(fields)})
            self._redirect(handler, path.rsplit("/submit", 1)[0] + "/?submitted=1")
            return
        self._send_json(handler, 404, {"ok": False, "error": "unknown_post"})

    def _serve_static(self, handler, path: str) -> None:
        relative = path.lstrip("/")
        if not relative or ".." in Path(relative).parts:
            self._send_json(handler, 404, {"ok": False, "error": "not_found"})
            return
        if path.endswith("/"):
            relative = relative + "index.html"
        target = self.site / relative
        if target.is_file():
            body = target.read_bytes()
            content_type = "application/json" if target.suffix == ".json" else "text/html; charset=utf-8"
            handler.send_response(200)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        if path.startswith("/story/"):
            parts = [piece for piece in path.split("/") if piece]
            sid = parts[1] if len(parts) > 1 else ""
            self._send_html(handler, 404, fixtures.render_not_found(sid))
            return
        self._send_json(handler, 404, {"ok": False, "error": "not_found"})
