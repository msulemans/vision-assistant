from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vision_assistant.ax_vision import AxElement, AxSnapshot, AxWindow
from vision_assistant.executor import (
    AxActionPort,
    ExecutionRefusal,
    plan_action,
    recheck_plan,
    window_from_snapshot,
)
from vision_assistant.intents import parse_intent


def _element(
    identifier: str | None = "app:sync-toggle",
    *,
    role: str = "AXCheckBox",
    title: str | None = "Sync",
    value: str | None = "0",
    frame: tuple[float, float, float, float] | None = (200.0, 380.0, 20.0, 20.0),
    enabled: bool | None = True,
    secure: bool = False,
    subrole: str | None = None,
    path: str = "w0/0",
) -> AxElement:
    return AxElement(
        role=role,
        subrole=subrole,
        title=title,
        description=None,
        value=value,
        identifier=identifier,
        frame=frame,
        enabled=enabled,
        focused=None,
        secure=secure,
        depth=0,
        path=path,
    )


def _snapshot(
    elements: tuple[AxElement, ...] = (),
    *,
    title: str = "Practice App",
    frame: tuple[float, float, float, float] | None = (100.0, 100.0, 480.0, 300.0),
    app: str | None = "Practice App",
    focused: bool = True,
) -> AxSnapshot:
    window = AxWindow(title=title, frame=frame, focused=focused, cg_window_id=1, elements=elements)
    return AxSnapshot(app=app, pid=1, windows=(window,))


def _intent(payload: dict):
    return parse_intent(payload)


class PlanActionTest(unittest.TestCase):
    def test_click_builds_identity_addressed_spec(self) -> None:
        snapshot = _snapshot((_element(),))
        plan = plan_action(_intent({"kind": "click_element", "element_id": "app:sync-toggle"}), snapshot)
        self.assertEqual(plan.kind, "click_element")
        self.assertEqual(plan.spec["action"], "press")
        self.assertEqual(plan.spec["element"], {"identifier": "app:sync-toggle"})
        self.assertEqual(plan.spec["expect_window_frame"], [100.0, 100.0, 480.0, 300.0])
        self.assertEqual(plan.element.identifier, "app:sync-toggle")
        self.assertIn("Sync", plan.description)

    def test_click_on_missing_element_refuses(self) -> None:
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "click_element", "element_id": "app:ghost"}), _snapshot((_element(),)))
        self.assertEqual(caught.exception.reason, "not_found")

    def test_duplicate_identifiers_refuse_as_ambiguous(self) -> None:
        snapshot = _snapshot((_element(path="w0/0"), _element(path="w0/1")))
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "click_element", "element_id": "app:sync-toggle"}), snapshot)
        self.assertEqual(caught.exception.reason, "ambiguous")

    def test_role_mismatch_refuses(self) -> None:
        snapshot = _snapshot((_element(role="AXTextField", title="Search"),))
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "click_element", "element_id": "app:sync-toggle"}), snapshot)
        self.assertEqual(caught.exception.reason, "role_mismatch")

    def test_disabled_element_refuses(self) -> None:
        snapshot = _snapshot((_element(enabled=False),))
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "click_element", "element_id": "app:sync-toggle"}), snapshot)
        self.assertEqual(caught.exception.reason, "disabled_element")

    def test_secure_element_refuses_even_for_click(self) -> None:
        snapshot = _snapshot((_element(role="AXTextField", subrole="AXSecureTextField", secure=True),))
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "click_element", "element_id": "app:sync-toggle"}), snapshot)
        self.assertEqual(caught.exception.reason, "secure_element")

    def test_type_by_field_label_resolves_to_stable_identifier(self) -> None:
        snapshot = _snapshot(
            (
                _element("app:search", role="AXTextField", title="Search", value="", path="w0/1"),
            )
        )
        plan = plan_action(
            _intent({"kind": "type_text", "field": "Search", "text": "hello"}), snapshot
        )
        self.assertEqual(plan.spec["action"], "type")
        self.assertEqual(plan.spec["element"], {"identifier": "app:search"})
        self.assertEqual(plan.spec["text"], "hello")

    def test_type_without_address_refuses(self) -> None:
        snapshot = _snapshot((_element("app:search", role="AXTextField", title="Search"),))
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "type_text", "text": "hello"}), snapshot)
        self.assertEqual(caught.exception.reason, "unaddressed")

    def test_type_onto_button_role_refuses(self) -> None:
        snapshot = _snapshot((_element("app:save", role="AXButton", title="Save"),))
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "type_text", "element_id": "app:save", "text": "x"}), snapshot)
        self.assertEqual(caught.exception.reason, "role_mismatch")

    def test_press_key_builds_key_spec(self) -> None:
        plan = plan_action(_intent({"kind": "press_key", "key": "escape"}), _snapshot((_element(),)))
        self.assertEqual(plan.spec["action"], "key")
        self.assertEqual(plan.spec["key"], "escape")
        self.assertIsNone(plan.element)
        self.assertIn("frontmost", plan.description)

    def test_non_actionable_kind_refuses(self) -> None:
        with self.assertRaises(ExecutionRefusal) as caught:
            plan_action(_intent({"kind": "observe"}), _snapshot((_element(),)))
        self.assertEqual(caught.exception.reason, "not_actionable")

    def test_window_selection(self) -> None:
        with self.assertRaises(ExecutionRefusal) as caught:
            window_from_snapshot(_snapshot((), title="Other"), title="Practice App")
        self.assertEqual(caught.exception.reason, "window_missing")
        snapshot = AxSnapshot(app="X", pid=1, windows=())
        with self.assertRaises(ExecutionRefusal):
            window_from_snapshot(snapshot, title="Practice App")


class RecheckTest(unittest.TestCase):
    def _plan(self):
        return plan_action(_intent({"kind": "click_element", "element_id": "app:sync-toggle"}), _snapshot((_element(),)))

    def test_unchanged_freshness_passes(self) -> None:
        recheck_plan(self._plan(), _snapshot((_element(),)))

    def test_moved_element_is_stale(self) -> None:
        with self.assertRaises(ExecutionRefusal) as caught:
            recheck_plan(self._plan(), _snapshot((_element(frame=(240.0, 420.0, 20.0, 20.0)),)))
        self.assertEqual(caught.exception.reason, "stale_frame")

    def test_missing_element_is_not_found(self) -> None:
        with self.assertRaises(ExecutionRefusal) as caught:
            recheck_plan(self._plan(), _snapshot((_element("app:notify-toggle", title="Notifications"),)))
        self.assertEqual(caught.exception.reason, "not_found")

    def test_missing_window_refuses(self) -> None:
        fresh = AxSnapshot(app="Practice App", pid=1, windows=())
        with self.assertRaises(ExecutionRefusal) as caught:
            recheck_plan(self._plan(), fresh)
        self.assertEqual(caught.exception.reason, "window_missing")

    def test_element_disabled_after_plan_refuses(self) -> None:
        with self.assertRaises(ExecutionRefusal) as caught:
            recheck_plan(self._plan(), _snapshot((_element(enabled=False),)))
        self.assertEqual(caught.exception.reason, "disabled_element")


def _fake_action_helper(tool_dir: Path, body: str) -> None:
    tool_dir.mkdir(parents=True, exist_ok=True)
    helper = tool_dir / "ax_action"
    helper.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    helper.chmod(0o700)


class AxActionPortTest(unittest.TestCase):
    def _port(self, tool_dir: Path) -> AxActionPort:
        return AxActionPort(
            tool_dir=tool_dir,
            action_source=tool_dir / "missing.swift",
            overlay_source=tool_dir / "missing.swift",
        )

    def test_check_reports_trust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_dir = Path(tmp) / "tools"
            _fake_action_helper(
                tool_dir,
                "import json, sys\nprint(json.dumps({'trusted': True}))\n",
            )
            self.assertTrue(self._port(tool_dir).check()["trusted"])

    def test_perform_parses_success_and_receives_spec_on_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_dir = Path(tmp) / "tools"
            _fake_action_helper(
                tool_dir,
                "import json, sys\n"
                "assert sys.argv[1] == '--perform'\n"
                "spec = json.loads(sys.stdin.read())\n"
                "assert spec['element']['identifier'] == 'app:sync-toggle'\n"
                "print(json.dumps({'performed': True, 'action': 'press', 'key_events': 0}))\n",
            )
            payload = self._port(tool_dir).perform({"element": {"identifier": "app:sync-toggle"}})
            self.assertTrue(payload["performed"])

    def test_helper_refusal_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_dir = Path(tmp) / "tools"
            _fake_action_helper(
                tool_dir,
                "import json, sys\nprint(json.dumps({'performed': False, 'reason': 'disabled_element'}))\n",
            )
            with self.assertRaises(ExecutionRefusal) as caught:
                self._port(tool_dir).perform({"element": {"identifier": "x"}})
            self.assertEqual(caught.exception.reason, "disabled_element")

    def test_permission_denial_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_dir = Path(tmp) / "tools"
            _fake_action_helper(
                tool_dir,
                "import json, sys\nprint(json.dumps({'performed': False, 'reason': 'permission'}))\nsys.exit(2)\n",
            )
            with self.assertRaises(ExecutionRefusal) as caught:
                self._port(tool_dir).plan({"element": {"identifier": "x"}})
            self.assertEqual(caught.exception.reason, "permission")

    def test_invalid_json_raises_bad_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_dir = Path(tmp) / "tools"
            _fake_action_helper(tool_dir, "import sys\nsys.stdout.write('not json')\n")
            with self.assertRaises(ExecutionRefusal) as caught:
                self._port(tool_dir).perform({"element": {"identifier": "x"}})
            self.assertEqual(caught.exception.reason, "bad_output")

    def test_plan_requires_planned_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_dir = Path(tmp) / "tools"
            _fake_action_helper(tool_dir, "import json, sys\nprint(json.dumps({'performed': True}))\n")
            with self.assertRaises(ExecutionRefusal) as caught:
                self._port(tool_dir).plan({"element": {"identifier": "x"}})
            self.assertEqual(caught.exception.reason, "helper")

    def test_overlay_is_best_effort_and_never_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool_dir = Path(tmp) / "missing"
            self.assertFalse(self._port(tool_dir).overlay((0, 0, 10, 10)))

    def test_overlay_passes_region_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool_dir = root / "tools"
            tool_dir.mkdir(parents=True, exist_ok=True)
            marker = root / "marker.txt"
            overlay = tool_dir / "ax_overlay"
            overlay.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                f"open({str(marker)!r}, 'w').write(' '.join(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            overlay.chmod(0o700)
            port = AxActionPort(
                tool_dir=tool_dir,
                action_source=tool_dir / "missing.swift",
                overlay_source=tool_dir / "missing.swift",
            )
            self.assertTrue(port.overlay((10.0, 20.0, 30.0, 40.0), ms=50))
            self.assertEqual(marker.read_text(encoding="utf-8"), "10 20 30 40 --ms 50")


if __name__ == "__main__":
    unittest.main()
