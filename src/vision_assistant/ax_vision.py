"""Read-only macOS Accessibility snapshot adapter (M012).

Compiles `tools/ax_dump.swift` once into a cached helper binary (same pattern
as the M007 OCR helper) and turns its JSON output into `AxSnapshot` records:
one entry per window with a flat list of elements (role, subrole, title,
description, value, identifier, frame in screen points, enabled/focused
state, tree path).

Read-only guarantees: this module only runs the helper in its read modes and
never posts input or performs Accessibility actions; the helper is written to
match. Secure text-field values are dropped at parse time even if a helper
sent them. Permission is never requested implicitly: `check()` reports the
trust state, and `request_permission()` is only safe to call from an explicit
user action.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOL_DIR = REPO_ROOT / "runs" / "m012-tools"
DEFAULT_HELPER_SOURCE = REPO_ROOT / "tools" / "ax_dump.swift"

MAX_ELEMENTS = 4000
MAX_DEPTH = 16

SECURE_SUBROLE = "AXSecureTextField"


class AxUnavailable(RuntimeError):
    """The Accessibility snapshot could not be produced.

    Reasons: ``toolchain`` (no swiftc), ``compile`` (build failure),
    ``permission`` (Accessibility access not granted), ``timeout``,
    ``helper`` (helper crashed or failed), ``bad_output``.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        message = f"accessibility snapshot unavailable ({reason})"
        if detail:
            message += f": {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class AxElement:
    role: str
    subrole: str | None
    title: str | None
    description: str | None
    value: str | None
    identifier: str | None
    frame: tuple[float, float, float, float] | None
    enabled: bool | None
    focused: bool | None
    secure: bool
    depth: int
    path: str

    @property
    def display_name(self) -> str:
        for candidate in (self.title, self.description, self.identifier):
            if candidate:
                return candidate
        return self.role


@dataclass(frozen=True)
class AxWindow:
    title: str | None
    frame: tuple[float, float, float, float] | None
    focused: bool | None
    cg_window_id: int | None
    elements: tuple[AxElement, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AxSnapshot:
    app: str | None
    pid: int | None
    windows: tuple[AxWindow, ...] = field(default_factory=tuple)


def _frame_from(raw: object) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, dict):
        return None
    try:
        return (
            float(raw["x"]),
            float(raw["y"]),
            float(raw["w"]),
            float(raw["h"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _optional_str(raw: object) -> str | None:
    if isinstance(raw, str) and raw:
        return raw
    return None


def _value_str(raw: object) -> str | None:
    """AX values may arrive as strings or numbers; keep them textual."""
    if isinstance(raw, bool):
        return "1" if raw else "0"
    if isinstance(raw, str):
        return raw if raw else None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        return f"{raw:g}"
    return None


def _parse_elements(
    children: object,
    *,
    depth: int,
    prefix: str,
    out: list[AxElement],
) -> None:
    if not isinstance(children, list) or depth > MAX_DEPTH:
        return
    for index, raw in enumerate(children):
        if len(out) >= MAX_ELEMENTS:
            return
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        if not isinstance(role, str) or not role:
            continue
        subrole = _optional_str(raw.get("subrole"))
        secure = bool(raw.get("secure")) or subrole == SECURE_SUBROLE
        value = None if secure else _value_str(raw.get("value"))
        element = AxElement(
            role=role,
            subrole=subrole,
            title=_optional_str(raw.get("title")),
            description=_optional_str(raw.get("description")),
            value=value,
            identifier=_optional_str(raw.get("identifier")),
            frame=_frame_from(raw.get("frame")),
            enabled=raw.get("enabled") if isinstance(raw.get("enabled"), bool) else None,
            focused=raw.get("focused") if isinstance(raw.get("focused"), bool) else None,
            secure=secure,
            depth=depth,
            path=f"{prefix}{index}",
        )
        out.append(element)
        _parse_elements(
            raw.get("children"),
            depth=depth + 1,
            prefix=f"{element.path}/",
            out=out,
        )


def _parse_snapshot(payload: object) -> AxSnapshot:
    if not isinstance(payload, dict):
        raise AxUnavailable("bad_output", "helper output is not a JSON object")
    windows_raw = payload.get("windows")
    if not isinstance(windows_raw, list):
        raise AxUnavailable("bad_output", "helper output has no windows list")
    windows: list[AxWindow] = []
    for window_index, raw in enumerate(windows_raw):
        if not isinstance(raw, dict):
            continue
        elements: list[AxElement] = []
        _parse_elements(
            raw.get("elements"),
            depth=0,
            prefix=f"w{window_index}/",
            out=elements,
        )
        cg_window_id = raw.get("cg_window_id")
        windows.append(
            AxWindow(
                title=_optional_str(raw.get("title")),
                frame=_frame_from(raw.get("frame")),
                focused=raw.get("focused") if isinstance(raw.get("focused"), bool) else None,
                cg_window_id=cg_window_id if isinstance(cg_window_id, int) else None,
                elements=tuple(elements),
            )
        )
    pid = payload.get("pid")
    return AxSnapshot(
        app=_optional_str(payload.get("app")),
        pid=pid if isinstance(pid, int) else None,
        windows=tuple(windows),
    )


class AxVisionAdapter:
    """Runs the read-only AX helper; never requests permission by itself."""

    def __init__(
        self,
        *,
        tool_dir: Path | None = None,
        helper_source: Path | None = None,
        timeout_s: float = 15.0,
        compile_timeout_s: float = 120.0,
    ) -> None:
        self.tool_dir = Path(tool_dir) if tool_dir is not None else DEFAULT_TOOL_DIR
        self.helper_source = (
            Path(helper_source) if helper_source is not None else DEFAULT_HELPER_SOURCE
        )
        self.timeout_s = timeout_s
        self.compile_timeout_s = compile_timeout_s
        self._helper: Path | None = None

    @property
    def helper_path(self) -> Path:
        return self.tool_dir / "ax_dump"

    def ensure_helper(self) -> Path:
        if self._helper is not None:
            return self._helper
        if self.helper_path.is_file() and os.access(self.helper_path, os.X_OK):
            source = self.helper_source
            stale = (
                source.is_file()
                and source.stat().st_mtime > self.helper_path.stat().st_mtime
            )
            if not stale:
                self._helper = self.helper_path
                return self._helper
        swiftc = shutil.which("swiftc") or "/usr/bin/swiftc"
        if not Path(swiftc).exists():
            raise AxUnavailable("toolchain", "swiftc not found; install Xcode command line tools")
        if not self.helper_source.is_file():
            raise AxUnavailable("compile", f"helper source not found at {self.helper_source}")
        self.tool_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [swiftc, "-O", str(self.helper_source), "-o", str(self.helper_path)],
                capture_output=True,
                timeout=self.compile_timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise AxUnavailable("compile", "timed out compiling the ax_dump helper") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()[-300:]
            raise AxUnavailable("compile", f"ax_dump build failed: {detail}")
        self._helper = self.helper_path
        return self._helper

    def _run(self, args: list[str]) -> tuple[int, bytes, bytes]:
        helper = self.ensure_helper()
        try:
            result = subprocess.run(
                [str(helper), *args],
                capture_output=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise AxUnavailable("timeout", f"ax_dump timed out after {self.timeout_s}s") from exc
        except OSError as exc:
            raise AxUnavailable("helper", f"cannot run ax_dump: {exc}") from exc
        return result.returncode, result.stdout, result.stderr

    @staticmethod
    def _decode(stdout: bytes) -> object:
        try:
            return json.loads(stdout.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AxUnavailable("bad_output", "ax_dump produced invalid JSON") from exc

    def check(self) -> dict:
        """Report the Accessibility trust state without prompting."""
        code, stdout, stderr = self._run(["--check"])
        payload = self._decode(stdout)
        if code != 0 or not isinstance(payload, dict) or "trusted" not in payload:
            detail = stderr.decode("utf-8", "replace").strip()[-200:]
            raise AxUnavailable("helper", f"ax_dump --check failed: {detail}")
        return {"trusted": bool(payload.get("trusted"))}

    def request_permission(self) -> dict:
        """Trigger the macOS prompt once. Only call from an explicit user action."""
        code, stdout, stderr = self._run(["--request-permission"])
        payload = self._decode(stdout)
        if code != 0 or not isinstance(payload, dict):
            detail = stderr.decode("utf-8", "replace").strip()[-200:]
            raise AxUnavailable("helper", f"ax_dump --request-permission failed: {detail}")
        return {"trusted": bool(payload.get("trusted")), "prompted": True}

    def snapshot(
        self,
        *,
        pid: int | None = None,
        app_name: str | None = None,
        frontmost: bool = False,
        max_depth: int = 12,
    ) -> AxSnapshot:
        """Read a snapshot of one application's windows. Read-only."""
        provided = (pid is not None, app_name is not None, frontmost)
        if sum(1 for value in provided if value) > 1:
            raise ValueError("pass exactly one of pid, app_name, frontmost")
        args = ["--dump"]
        if pid is not None:
            args += ["--pid", str(int(pid))]
        elif app_name is not None:
            args += ["--app", str(app_name)]
        else:
            args += ["--frontmost"]
        if max_depth != 12:
            args += ["--max-depth", str(int(max_depth))]
        code, stdout, stderr = self._run(args)
        if code == 2:
            raise AxUnavailable(
                "permission",
                "Accessibility access is not granted to the host terminal "
                "(run the explicit --request-permission flow to opt in)",
            )
        payload = self._decode(stdout)
        if code != 0:
            detail = stderr.decode("utf-8", "replace").strip()[-200:]
            if isinstance(payload, dict) and payload.get("error") == "permission":
                raise AxUnavailable("permission", detail or "not granted")
            raise AxUnavailable("helper", f"ax_dump exited {code}: {detail}")
        if isinstance(payload, dict) and payload.get("trusted") is False:
            raise AxUnavailable("permission", "not granted")
        return _parse_snapshot(payload)

    @staticmethod
    def snapshot_to_dict(snapshot: AxSnapshot) -> dict:
        """Serializable form for CLI output; secure values are already gone."""
        def element_dict(element: AxElement) -> dict:
            return {
                "path": element.path,
                "depth": element.depth,
                "role": element.role,
                "subrole": element.subrole,
                "title": element.title,
                "description": element.description,
                "value": element.value,
                "identifier": element.identifier,
                "frame": list(element.frame) if element.frame else None,
                "enabled": element.enabled,
                "focused": element.focused,
                "secure": element.secure,
            }

        return {
            "app": snapshot.app,
            "pid": snapshot.pid,
            "windows": [
                {
                    "title": window.title,
                    "frame": list(window.frame) if window.frame else None,
                    "focused": window.focused,
                    "cg_window_id": window.cg_window_id,
                    "elements": [element_dict(element) for element in window.elements],
                }
                for window in snapshot.windows
            ],
        }
