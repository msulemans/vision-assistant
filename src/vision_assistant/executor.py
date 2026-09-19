"""M013 supervised executor: plan, guard, and post approved actions.

The only action-capable artifact in the project is `tools/ax_action.swift`.
This module builds the action spec from an approved typed intent and a fresh
read-only AX snapshot, enforces identity/role/secret/enabled/window guards,
re-checks freshness immediately before posting, and records attribution.
It contains no action APIs itself — a source-scan test keeps the read-only
and write-capable surfaces strictly separate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ax_vision import REPO_ROOT, AxElement, AxSnapshot, AxWindow
from .grounding import TargetSpec, resolve_target

DEFAULT_TOOL_DIR = REPO_ROOT / "runs" / "m013-tools"
DEFAULT_ACTION_SOURCE = REPO_ROOT / "tools" / "ax_action.swift"
DEFAULT_OVERLAY_SOURCE = REPO_ROOT / "tools" / "ax_overlay.swift"

GUI_ACTION_KINDS = ("click_element", "type_text", "press_key")
CLICK_ROLES = frozenset(
    {"AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXMenuItem"}
)
TYPE_ROLES = frozenset({"AXTextField", "AXTextArea", "AXComboBox"})
FRAME_TOLERANCE = 1.0


class ExecutionRefusal(RuntimeError):
    """A guard refused the action (or the helper did). Nothing was posted."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        message = f"execution refused ({reason})"
        if detail:
            message += f": {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class ActionPlan:
    kind: str
    spec: dict
    window_title: str | None
    element: AxElement | None
    description: str


def window_from_snapshot(snapshot: AxSnapshot, *, title: str | None = None) -> AxWindow:
    windows = snapshot.windows
    if title is not None:
        matches = [window for window in windows if window.title == title]
        if not matches:
            raise ExecutionRefusal("window_missing", f"no window titled {title!r}")
        if len(matches) > 1:
            raise ExecutionRefusal("ambiguous", f"{len(matches)} windows titled {title!r}")
        return matches[0]
    focused = [window for window in windows if window.focused]
    if focused:
        return focused[0]
    if windows:
        return windows[0]
    raise ExecutionRefusal("window_missing", "snapshot contains no windows")


def _frame_close(
    first: tuple[float, float, float, float] | None,
    second: tuple[float, float, float, float] | None,
    tolerance: float = FRAME_TOLERANCE,
) -> bool:
    if first is None or second is None:
        return False
    return all(abs(a - b) <= tolerance for a, b in zip(first, second))


def _resolve_element(
    window: AxWindow,
    *,
    element_id: str | None = None,
    text: str | None = None,
    role: str | None = None,
) -> AxElement:
    spec = TargetSpec(text if text is not None else (element_id or ""), role=role, element_id=element_id)
    result = resolve_target(window.elements, spec)
    if result.status != "found" or result.chosen is None:
        raise ExecutionRefusal(result.status, result.message)
    return result.chosen.element


def _guard_element(element: AxElement, allowed_roles: frozenset[str]) -> None:
    """Shared element guards; refusals are final and post nothing."""
    if element.secure:
        raise ExecutionRefusal("secure_element", f"{element.identifier or element.display_name!r} is a secure field")
    if element.enabled is False:
        raise ExecutionRefusal("disabled_element", f"{element.identifier or element.display_name!r} is disabled")
    if element.role not in allowed_roles:
        raise ExecutionRefusal(
            "role_mismatch", f"role {element.role} is not addressable for this action"
        )
    if not element.identifier:
        raise ExecutionRefusal("no_stable_identifier", "element has no stable AX identifier")


def plan_action(intent, snapshot: AxSnapshot, *, window_title: str | None = None) -> ActionPlan:
    """Build the action spec for one approved intent against a fresh snapshot."""
    if intent.kind not in GUI_ACTION_KINDS:
        raise ExecutionRefusal("not_actionable", f"{intent.kind!r} performs no host action")
    window = window_from_snapshot(snapshot, title=window_title)
    if window.frame is None:
        raise ExecutionRefusal("window_missing", "window has no geometry")
    if snapshot.app is None:
        raise ExecutionRefusal("window_missing", "snapshot has no application name")

    if intent.kind == "click_element":
        element = _resolve_element(window, element_id=intent.params["element_id"])
        _guard_element(element, CLICK_ROLES)
        spec = {
            "action": "press",
            "app": snapshot.app,
            "window_title": window.title,
            "element": {"identifier": element.identifier},
            "expect_window_frame": list(window.frame),
        }
        description = (
            f"press {element.role} {element.display_name!r} "
            f"(id {element.identifier}) in {window.title!r}"
        )
        return ActionPlan("click_element", spec, window.title, element, description)

    if intent.kind == "type_text":
        element_id = intent.params.get("element_id")
        field = intent.params.get("field")
        if element_id:
            element = _resolve_element(window, element_id=element_id)
        elif field:
            element = _resolve_element(window, text=field, role="textfield")
        else:
            raise ExecutionRefusal("unaddressed", "type_text requires an element_id or field")
        _guard_element(element, TYPE_ROLES)
        spec = {
            "action": "type",
            "app": snapshot.app,
            "window_title": window.title,
            "element": {"identifier": element.identifier},
            "text": intent.params["text"],
            "expect_window_frame": list(window.frame),
        }
        description = (
            f"type {len(intent.params['text'])} characters into {element.role} "
            f"{element.display_name!r} (id {element.identifier}) in {window.title!r}"
        )
        return ActionPlan("type_text", spec, window.title, element, description)

    # press_key: no element; the helper additionally requires the target app to
    # be frontmost before posting anything.
    spec = {
        "action": "key",
        "app": snapshot.app,
        "window_title": window.title,
        "key": intent.params["key"],
    }
    description = f"press key {intent.params['key']!r} (target window {window.title!r} must be frontmost)"
    return ActionPlan("press_key", spec, window.title, None, description)


def recheck_plan(plan: ActionPlan, fresh: AxSnapshot) -> AxWindow:
    """Freshness gate, taken after confirmation and before posting.

    The window must still exist with the same geometry, and the planned
    element must still resolve uniquely with the same frame, enabled state,
    and no secure subrole. Anything else refuses with nothing posted.
    """
    window = window_from_snapshot(fresh, title=plan.window_title)
    if plan.element is not None:
        element = _resolve_element(window, element_id=plan.element.identifier)
        if not _frame_close(element.frame, plan.element.frame):
            raise ExecutionRefusal(
                "stale_frame",
                f"target moved between plan and posting: {plan.element.frame} -> {element.frame}",
            )
        if element.enabled is False:
            raise ExecutionRefusal("disabled_element", "target became disabled")
        if element.secure:
            raise ExecutionRefusal("secure_element", "target became a secure field")
    return window


def _ensure_binary(source: Path, target: Path, *, compile_timeout_s: float) -> Path:
    if target.is_file() and os.access(target, os.X_OK):
        stale = source.is_file() and source.stat().st_mtime > target.stat().st_mtime
        if not stale:
            return target
    swiftc = shutil.which("swiftc") or "/usr/bin/swiftc"
    if not Path(swiftc).exists():
        raise ExecutionRefusal("toolchain", "swiftc not found; install Xcode command line tools")
    if not source.is_file():
        raise ExecutionRefusal("compile", f"helper source not found at {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [swiftc, "-O", str(source), "-o", str(target)],
            capture_output=True,
            timeout=compile_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExecutionRefusal("compile", f"timed out compiling {source.name}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()[-300:]
        raise ExecutionRefusal("compile", f"{source.name} build failed: {detail}")
    return target


class AxActionPort:
    """Runs the action helper; every refusal from the helper is typed."""

    def __init__(
        self,
        *,
        tool_dir: Path | None = None,
        action_source: Path | None = None,
        overlay_source: Path | None = None,
        timeout_s: float = 20.0,
        compile_timeout_s: float = 120.0,
    ) -> None:
        self.tool_dir = Path(tool_dir) if tool_dir is not None else DEFAULT_TOOL_DIR
        self.action_source = (
            Path(action_source) if action_source is not None else DEFAULT_ACTION_SOURCE
        )
        self.overlay_source = (
            Path(overlay_source) if overlay_source is not None else DEFAULT_OVERLAY_SOURCE
        )
        self.timeout_s = timeout_s
        self.compile_timeout_s = compile_timeout_s
        self._action: Path | None = None
        self._overlay: Path | None = None

    @property
    def action_path(self) -> Path:
        return self.tool_dir / "ax_action"

    @property
    def overlay_path(self) -> Path:
        return self.tool_dir / "ax_overlay"

    def ensure_action_helper(self) -> Path:
        if self._action is None:
            self._action = _ensure_binary(
                self.action_source, self.action_path, compile_timeout_s=self.compile_timeout_s
            )
        return self._action

    def ensure_overlay_helper(self) -> Path:
        if self._overlay is None:
            self._overlay = _ensure_binary(
                self.overlay_source, self.overlay_path, compile_timeout_s=self.compile_timeout_s
            )
        return self._overlay

    def check(self) -> dict:
        helper = self.ensure_action_helper()
        try:
            result = subprocess.run([str(helper), "--check"], capture_output=True, timeout=self.timeout_s)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ExecutionRefusal("helper", str(exc)) from exc
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ExecutionRefusal("bad_output", "ax_action produced invalid JSON") from exc
        if result.returncode != 0 or "trusted" not in payload:
            raise ExecutionRefusal("helper", "ax_action --check failed")
        return {"trusted": bool(payload["trusted"])}

    def _call(self, mode: str, spec: dict) -> dict:
        helper = self.ensure_action_helper()
        try:
            result = subprocess.run(
                [str(helper), mode],
                input=json.dumps(spec).encode("utf-8"),
                capture_output=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExecutionRefusal("helper", f"ax_action timed out after {self.timeout_s}s") from exc
        except OSError as exc:
            raise ExecutionRefusal("helper", f"cannot run ax_action: {exc}") from exc
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ExecutionRefusal("bad_output", "ax_action produced invalid JSON") from exc
        if result.returncode == 2 or payload.get("reason") == "permission":
            raise ExecutionRefusal(
                "permission",
                "Accessibility access is not granted to the host terminal",
            )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()[-200:]
            raise ExecutionRefusal("helper", f"ax_action exited {result.returncode}: {detail}")
        reason = payload.get("reason")
        if payload.get("performed") is not True and reason:
            raise ExecutionRefusal(str(reason), str(payload.get("identifier") or ""))
        return payload

    def plan(self, spec: dict) -> dict:
        payload = self._call("--plan", spec)
        if payload.get("planned") is not True:
            raise ExecutionRefusal("helper", "ax_action plan did not report planned")
        return payload

    def perform(self, spec: dict) -> dict:
        payload = self._call("--perform", spec)
        if payload.get("performed") is not True:
            raise ExecutionRefusal("perform_failed", "ax_action reported no success")
        return payload

    def overlay(self, region: tuple[float, float, float, float], *, ms: int = 1200) -> bool:
        """Best-effort visible target highlight; never blocks execution."""
        try:
            helper = self.ensure_overlay_helper()
            result = subprocess.run(
                [
                    str(helper),
                    str(round(region[0])),
                    str(round(region[1])),
                    str(round(region[2])),
                    str(round(region[3])),
                    "--ms",
                    str(int(ms)),
                ],
                capture_output=True,
                timeout=max(5.0, ms / 1000.0 + 5.0),
            )
        except (ExecutionRefusal, subprocess.TimeoutExpired, OSError):
            return False
        return result.returncode == 0
