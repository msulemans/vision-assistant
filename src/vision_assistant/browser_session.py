"""M018B browser session adapter: typed client for the disposable helper.

The helper (``tools/browser_window.swift``) is our own single-view WebKit
browser. This module owns the process lifecycle, the JSON-lines protocol,
coordinate mapping (screenshot pixels → CSS points), the frozen guards
(stale frames, origin escapes, password/no-focus typing refusals, budgets), and
the temporary snapshot directory. All refusals are typed and fail-closed: when
a guard fires, no command reaches the helper.

Safety posture: this Python layer synthesizes nothing — it only writes typed
JSON commands to the helper's stdin. The only event synthesis in the project
lives in `browser_window.swift` (in-app synthesized events; source-scanned
invariants).
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import browser_targets
from . import browser_tasks as tasks

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_SOURCE = REPO_ROOT / "tools" / "browser_window.swift"
DEFAULT_HELPER_BIN = REPO_ROOT / "runs" / "m018-tools" / "browser_window"
DEFAULT_TIMEOUT_MS = 8000

ACTION_COMMANDS = ("navigate", "click", "click_target", "type", "key", "scroll", "back")
# M019A additive commands; both consume the same frozen action budget.
TYPED_ACTION_COMMANDS = ("fill", "set_control")
_BUDGETED_COMMANDS = ACTION_COMMANDS + TYPED_ACTION_COMMANDS


class BrowserError(Exception):
    """Typed browser refusal or failure; ``reason`` is a frozen error code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason if not detail else "{}: {}".format(reason, detail))
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Snapshot:
    seq: int
    width: int
    height: int
    scale: float
    url: str
    path: str


@dataclass(frozen=True)
class TargetList:
    """One observation's visible target list (valid only for its snapshot)."""

    seq: int
    targets: tuple
    truncated: bool
    total: int


def compile_helper(source=None, dest=None) -> Path:
    """Compile (or reuse) the helper binary; rebuild when sources are newer."""

    source_path = Path(source) if source else HELPER_SOURCE
    dest_path = Path(dest) if dest else DEFAULT_HELPER_BIN
    if not source_path.is_file():
        raise BrowserError("helper_source_missing", str(source_path))
    if dest_path.is_file() and dest_path.stat().st_mtime >= source_path.stat().st_mtime:
        return dest_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["swiftc", "-O", str(source_path), "-o", str(dest_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise BrowserError("compile_failed", detail[-1] if detail else "swiftc failed")
    return dest_path


def map_screenshot_point(px: int, py: int, shot: Snapshot) -> tuple:
    """Map screenshot pixels to CSS points using the snapshot's scale."""

    for name, value in (("px", px), ("py", py)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("{} must be an integer".format(name))
    if shot.scale <= 0:
        raise ValueError("snapshot scale must be positive")
    if not 0 <= px < shot.width or not 0 <= py < shot.height:
        raise ValueError("point outside the snapshot ({}x{})".format(shot.width, shot.height))
    return (px / shot.scale, py / shot.scale)


class BrowserSession:
    """One disposable browser helper process with frozen guards and budgets."""

    def __init__(self, port: int, helper_cmd=None, helper_bin=None, width: int = 1280,
                 height: int = 720, timeout_ms: int = DEFAULT_TIMEOUT_MS,
                 snapshot_dir=None, max_steps=None, max_seconds=None,
                 live_origins=None, helper_args=(), scroll_method=None) -> None:
        self.port = int(port)
        self.width = int(width)
        self.height = int(height)
        self.timeout_ms = int(timeout_ms)
        # M018E scoped change: default empty = frozen loopback-only policy.
        self.live_origins = tuple(live_origins or ())
        # M021: optional per-session scroll delivery ("dom" = in-page JS
        # scroll, activation-independent); None keeps the frozen key path.
        self.scroll_method = scroll_method
        self._helper_args = [str(value) for value in helper_args]
        self._helper_cmd = list(helper_cmd) if helper_cmd else None
        self._helper_bin = Path(helper_bin) if helper_bin else None
        self._proc = None
        self._queue = queue.Queue()
        self._reader = None
        self._next_id = 1
        self._steps = 0
        self._max_steps = int(max_steps if max_steps is not None else tasks.LIMITS["max_action_steps"])
        self._max_seconds = float(
            max_seconds if max_seconds is not None else tasks.LIMITS["max_seconds"])
        self._started_at = None
        self.last_snapshot = None
        self.last_targets = None
        self.ready = False
        self.unhealthy = False
        self._closed = False
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else None

    # ------------------------------------------------------------ lifecycle

    def launch(self) -> "BrowserSession":
        if self._closed:
            raise BrowserError("closed")
        if self._helper_cmd is not None:
            command = self._helper_cmd
        else:
            binary = self._helper_bin or compile_helper()
            command = [
                str(binary), "--port", str(self.port),
                "--width", str(self.width), "--height", str(self.height),
            ] + self._helper_args
        try:
            self._proc = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )
        except FileNotFoundError as exc:
            raise BrowserError("helper_missing", str(exc))
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()
        self._started_at = time.monotonic()
        try:
            event = self._read_reply(timeout_ms=10000)
        except BrowserError:
            self.stop()
            raise
        if not (isinstance(event, dict) and event.get("event") == "ready"):
            self.stop()
            raise BrowserError("helper_not_ready")
        self.ready = True
        return self

    def _reader_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                self._queue.put(json.loads(line))
            except ValueError:
                self._queue.put({"ok": False, "error": "bad_json"})
        self._queue.put({"ok": False, "error": "closed"})

    def _read_reply(self, timeout_ms: int) -> dict:
        try:
            reply = self._queue.get(timeout=timeout_ms / 1000.0)
        except queue.Empty:
            self.unhealthy = True
            raise BrowserError("timeout")
        if not isinstance(reply, dict):
            self.unhealthy = True
            raise BrowserError("protocol")
        if not reply.get("ok"):
            error = str(reply.get("error", "helper_error"))
            if error == "closed":
                self.unhealthy = True
                raise BrowserError("closed")
            raise BrowserError(error, str(reply.get("detail", "")))
        return reply

    def _call(self, cmd: str, **fields) -> dict:
        if self._closed:
            raise BrowserError("closed")
        if self.unhealthy:
            raise BrowserError("unhealthy")
        if cmd in _BUDGETED_COMMANDS:
            self._check_budgets()
        request_id = self._next_id
        self._next_id += 1
        payload = {"id": request_id, "cmd": cmd}
        payload.update(fields)
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(json.dumps(payload, sort_keys=True) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            self.unhealthy = True
            raise BrowserError("closed")
        reply = self._read_reply(self.timeout_ms)
        if reply.get("id") != request_id:
            self.unhealthy = True
            raise BrowserError("protocol", "reply id mismatch")
        return reply

    def _check_budgets(self) -> None:
        if self._started_at is None:
            raise BrowserError("not_started")
        if self._steps + 1 > self._max_steps:
            raise BrowserError("budget_steps", "limit {}".format(self._max_steps))
        if time.monotonic() - self._started_at > self._max_seconds:
            raise BrowserError("budget_seconds", "limit {}".format(self._max_seconds))
        self._steps += 1

    def stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.write(json.dumps({"id": self._next_id, "cmd": "quit"}) + "\n")
                proc.stdin.flush()
                proc.wait(timeout=2)
            except (BrokenPipeError, ValueError, OSError, subprocess.TimeoutExpired):
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        if proc is not None:
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
        self._proc = None
        self._closed = True
        if self.snapshot_dir is not None and self.snapshot_dir.exists():
            shutil.rmtree(self.snapshot_dir, ignore_errors=True)

    def __enter__(self) -> "BrowserSession":
        return self.launch()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # --------------------------------------------------------------- guards

    def _origin_allowed(self, url: str) -> bool:
        if url.startswith("/") and not url.startswith("//"):
            return True
        for prefix in ("http://127.0.0.1:", "http://localhost:"):
            if url.startswith(prefix):
                port_part = url[len(prefix):].split("/", 1)[0]
                return port_part == str(self.port)
        for origin in self.live_origins:
            # Strict boundary check: the origin itself or a path/query under
            # it. "news.ycombinator.com.evil.example" can never match.
            if (url == origin or url.startswith(origin + "/")
                    or url.startswith(origin + "?")):
                return True
        return False

    # -------------------------------------------------------------- actions

    def navigate(self, url: str) -> str:
        if not isinstance(url, str) or not url:
            raise BrowserError("refused_origin", "empty url")
        if url.startswith("//"):
            raise BrowserError("refused_origin", "protocol-relative url")
        if not self._origin_allowed(url):
            raise BrowserError("refused_origin", url)
        reply = self._call("navigate", url=url)
        return str(reply.get("url", ""))

    def snapshot(self, path=None) -> Snapshot:
        if path is None:
            if self.snapshot_dir is None:
                raise BrowserError("no_snapshot_dir")
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            path = self.snapshot_dir / "shot-{:04d}.png".format(self._next_id)
        reply = self._call("snapshot", path=str(path))
        shot = Snapshot(
            seq=int(reply["seq"]), width=int(reply["width"]), height=int(reply["height"]),
            scale=float(reply["scale"]), url=str(reply.get("url", "")), path=str(path),
        )
        self.last_snapshot = shot
        return shot

    def click(self, px: int, py: int) -> str:
        if self.last_snapshot is None:
            raise BrowserError("refused_stale", "no snapshot yet")
        try:
            css_x, css_y = map_screenshot_point(px, py, self.last_snapshot)
        except ValueError as exc:
            raise BrowserError("refused_viewport", str(exc))
        if not 0 <= css_x < self.width or not 0 <= css_y < self.height:
            raise BrowserError("refused_viewport", "outside the css viewport")
        reply = self._call("click", x=css_x, y=css_y, seq=self.last_snapshot.seq)
        return str(reply.get("url", ""))

    def targets(self) -> TargetList:
        """Fetch the current observation's visible target list (M018T)."""

        if self.last_snapshot is None:
            raise BrowserError("refused_target_stale", "no snapshot yet")
        reply = self._call("targets")
        seq = int(reply.get("seq", -1))
        if seq != self.last_snapshot.seq:
            self.last_targets = None
            raise BrowserError("refused_target_stale", "page changed since the observation")
        entries = []
        for item in reply.get("targets") or []:
            if not isinstance(item, dict):
                continue
            t_id = item.get("id")
            role = item.get("role")
            rect = item.get("rect")
            if (not isinstance(t_id, str) or role not in browser_targets.TARGET_ROLES
                    or not (isinstance(rect, list) and len(rect) == 4)):
                continue
            try:
                rect_values = tuple(float(value) for value in rect)
            except (TypeError, ValueError):
                continue
            entries.append(browser_targets.TargetEntry(
                id=t_id, role=role,
                label=browser_targets.sanitize_label(item.get("label")),
                rect=rect_values,
                enabled=bool(item.get("enabled", False)),
                focused=bool(item.get("focused", False)),
            ))
        self.last_targets = TargetList(
            seq=seq, targets=tuple(entries),
            truncated=bool(reply.get("truncated", False)),
            total=int(reply.get("total", len(entries))))
        return self.last_targets

    def click_target(self, target_id: str, method=None) -> str:
        """Click a listed target by opaque id; resolve and re-validate in the helper.

        All guards fail closed BEFORE anything is written to the helper: a
        missing/stale target list, a stale observation, a malformed or unknown
        id, or a role outside the allowlist never reach the browser. M019
        typed operations pass ``method="dom"`` for semantic activation with
        identical guards; the frozen M018 paths keep synthesized events.
        """

        if self.last_snapshot is None or self.last_targets is None:
            raise BrowserError("refused_target_stale",
                               "no current target list; observe again")
        if self.last_targets.seq != self.last_snapshot.seq:
            raise BrowserError("refused_target_stale", "observe again before clicking")
        if not browser_targets.valid_target_id(target_id):
            raise BrowserError("refused_target_stale", "malformed target id")
        if target_id not in {entry.id for entry in self.last_targets.targets}:
            raise BrowserError("refused_target_stale", "unknown target id; observe again")
        fields = {"target": target_id, "seq": self.last_snapshot.seq}
        if method:
            fields["method"] = str(method)
        reply = self._call("click_target", **fields)
        return str(reply.get("url", ""))

    def state(self) -> dict:
        return self._call("state")

    def type_text(self, text: str) -> int:
        if not isinstance(text, str) or not text:
            raise BrowserError("refused_focus", "empty text")
        state = self.state()
        focused = state.get("focused") or {}
        if focused.get("password"):
            raise BrowserError("refused_password", "focused element is a password field")
        if not focused.get("editable"):
            raise BrowserError("refused_focus", "no focused editable element")
        reply = self._call("type", text=text)
        return int(reply.get("typed", 0))

    def press_key(self, key: str) -> None:
        self._call("key", key=key)

    def scroll(self, direction: str, amount, method=None):
        """Scroll the page; returns the helper-reported page count/fraction.

        ``amount`` stays untouched (int for the frozen key path; a float is
        meaningful only with ``method="dom"``, where it is a viewport
        fraction — M022 trusted 70% traversal steps).
        """

        fields = {"direction": direction, "amount": amount}
        chosen = method or self.scroll_method
        if chosen:
            fields["method"] = str(chosen)
        reply = self._call("scroll", **fields)
        return reply.get("pages", 0)

    def links(self) -> dict:
        """Trusted DOM metadata: laid-out links as {row, label, href} rows.

        Used only by trusted post-selection mapping (M022); callers must
        never render these values into a model prompt.
        """

        reply = self._call("links")
        rows = []
        for item in reply.get("links") or []:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            href = item.get("href")
            if not isinstance(label, str) or not isinstance(href, str):
                continue
            try:
                row = int(item.get("row", -1))
            except (TypeError, ValueError):
                row = -1
            rows.append({"row": row, "label": label[:200], "href": href[:500]})
        return {"links": rows, "truncated": bool(reply.get("truncated"))}

    def back(self) -> str:
        reply = self._call("back")
        return str(reply.get("url", ""))

    # ------------------------------------------------- M019 semantic ops

    @property
    def observation_id(self) -> str:
        if self.last_snapshot is None:
            return ""
        return "obs-{}".format(self.last_snapshot.seq)

    def resolve_ref(self, ref: str):
        """Resolve a typed ``ui:N`` reference against the current observation."""

        if self.last_snapshot is None or self.last_targets is None:
            raise BrowserError("refused_target_stale",
                               "no current target list; observe again")
        if self.last_targets.seq != self.last_snapshot.seq:
            raise BrowserError("refused_target_stale", "observe again before acting")
        if not browser_targets.valid_ui_ref(ref):
            raise BrowserError("refused_target_stale", "malformed target_ref")
        for entry in self.last_targets.targets:
            if browser_targets.ui_ref_for(entry.id) == ref:
                return entry
        raise BrowserError("refused_target_stale", "unknown target_ref; observe again")

    def _check_typed_observation(self, observation_id: str) -> None:
        if observation_id != self.observation_id:
            raise BrowserError("refused_target_stale", "stale observation")

    def fill_field(self, ref: str, text: str, observation_id: str) -> str:
        """Trusted focus → clear → type → read-back as one bounded operation.

        Everything is checked before any command reaches the helper: stale
        observation, credential-classified label, and role. The helper then
        re-checks element identity, visibility, enabled state, and the live
        ``type=password`` attribute before it focuses and writes.
        """

        entry = self.resolve_ref(ref)
        self._check_typed_observation(observation_id)
        info = browser_targets.classify_control(entry.role, entry.label)
        if info["credential"]:
            raise BrowserError("refused_credential",
                               "credential fields are never filled")
        if entry.role not in ("text_input", "textarea"):
            raise BrowserError("refused_target_role", "fill_field needs a text field")
        if not isinstance(text, str) or len(text) > tasks.MAX_TEXT_CHARS:
            raise BrowserError("refused_focus", "text must be a short string")
        if any(ord(char) < 32 for char in text):
            raise BrowserError("refused_focus",
                               "text must not contain control characters")
        reply = self._call("fill", target=entry.id, value=text,
                           seq=self.last_snapshot.seq)
        read_back = str(reply.get("value", ""))
        if read_back != text:
            raise BrowserError("read_back_failed", "typed value did not stick")
        return read_back

    def select_option(self, ref: str, option: str, observation_id: str) -> str:
        entry = self.resolve_ref(ref)
        self._check_typed_observation(observation_id)
        if entry.role != "select":
            raise BrowserError("refused_target_role",
                               "select_option needs a select control")
        if (not isinstance(option, str) or not 1 <= len(option) <= 80
                or any(ord(char) < 32 for char in option)):
            raise BrowserError("refused_target_role",
                               "option must be a short visible string")
        reply = self._call("set_control", target=entry.id, mode="select",
                           option=option, seq=self.last_snapshot.seq)
        got = str(reply.get("value", ""))
        if got != option:
            raise BrowserError("read_back_failed", "selection did not stick")
        return got

    def set_toggle(self, ref: str, value: bool, observation_id: str) -> bool:
        entry = self.resolve_ref(ref)
        self._check_typed_observation(observation_id)
        if entry.role not in ("checkbox", "radio"):
            raise BrowserError("refused_target_role",
                               "set_toggle needs a checkbox or radio")
        if not isinstance(value, bool):
            raise BrowserError("refused_target_role", "value must be true or false")
        reply = self._call("set_control", target=entry.id, mode="toggle",
                           value=value, seq=self.last_snapshot.seq)
        got = bool(reply.get("checked", False))
        if got != value:
            raise BrowserError("read_back_failed", "toggle did not stick")
        return got

    def save_form(self, ref: str, observation_id: str, authorized_saves=()) -> str:
        """Authorized fixture-local save: click the declared save control.

        The task must have declared this exact ``ui:`` reference as its local
        save; anything else fails closed before any command is sent.
        """

        entry = self.resolve_ref(ref)
        self._check_typed_observation(observation_id)
        if not browser_targets.submit_authorized(ref, authorized_saves):
            raise BrowserError("refused_unauthorized_save",
                               "this task does not authorize saving")
        if entry.role != "button":
            raise BrowserError("refused_target_role", "save_form needs a button")
        reply = self._call("click_target", target=entry.id,
                           seq=self.last_snapshot.seq, method="dom")
        return str(reply.get("url", ""))

    @property
    def steps_used(self) -> int:
        return self._steps
