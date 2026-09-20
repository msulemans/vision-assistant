"""M019A invariants: the typed contracts stay frozen and fail-closed.

These are source-level and behavior-level pins for the M019 layer added on
top of the frozen M018 modes: the capability manifest, the absence of raw
actions in typed modes, the structural credential/submission denials, and
the helper's two additive semantic commands.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from vision_assistant import browser_agent as agent
from vision_assistant import browser_session as bs
from vision_assistant import browser_targets as bt
from vision_assistant import browser_tasks as tasks

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
SRC = REPO_ROOT / "src" / "vision_assistant"


class ModeContractTest(unittest.TestCase):
    def test_capability_manifest_is_frozen_and_disjoint(self) -> None:
        self.assertEqual(tasks.TYPED_MODES, ("answer", "navigate", "form", "stop"))
        for mode in tasks.TYPED_MODES:
            allowed = set(tasks.MODE_CAPABILITIES[mode])
            self.assertTrue(allowed.issubset(set(tasks.TYPED_ACTIONS)))
        self.assertEqual(
            tasks.MODE_CAPABILITIES["answer"],
            ("scroll", "wait", "finish_answer", "stop"))
        self.assertEqual(tasks.MODE_CAPABILITIES["stop"], ("stop",))

    def test_raw_actions_are_absent_from_every_typed_mode(self) -> None:
        for mode in tasks.TYPED_MODES:
            for raw in ("click", "type_text", "type", "navigate"):
                self.assertNotIn(raw, tasks.MODE_CAPABILITIES[mode])
                _parsed, error = tasks.validate_typed_action(
                    {"kind": raw}, mode=mode)
                self.assertIsNotNone(error)

    def test_typed_schema_enum_matches_the_manifest(self) -> None:
        for mode in tasks.TYPED_MODES:
            schema = agent.typed_action_schema(mode)
            self.assertEqual(schema["properties"]["action"]["enum"],
                             list(tasks.MODE_CAPABILITIES[mode]))
            self.assertNotIn("x", schema["properties"])
            self.assertNotIn("y", schema["properties"])


class SourceSurfacesTest(unittest.TestCase):
    def test_agent_wires_the_typed_contracts(self) -> None:
        source = (SRC / "browser_agent.py").read_text(encoding="utf-8")
        for token in ("validate_typed_action", "no_observable_change",
                      "MUTATING_TYPED_ACTIONS", "render_typed_target_block",
                      "TYPED_REFUSAL_HINTS", "TYPED_PROMPT_VERSION"):
            self.assertIn(token, source, token)

    def test_session_semantic_ops_fail_closed(self) -> None:
        source = (SRC / "browser_session.py").read_text(encoding="utf-8")
        for token in ("refused_credential", "read_back_failed",
                      "refused_unauthorized_save", "observation_id",
                      "resolve_ref"):
            self.assertIn(token, source, token)
        self.assertIn("fill_field", source)
        self.assertIn("select_option", source)
        self.assertIn("set_toggle", source)
        self.assertIn("save_form", source)

    def test_budgeted_commands_superset_keeps_m018_frozen(self) -> None:
        self.assertEqual(
            bs.ACTION_COMMANDS,
            ("navigate", "click", "click_target", "type", "key", "scroll", "back"))
        self.assertEqual(bs.TYPED_ACTION_COMMANDS, ("fill", "set_control"))
        source = (SRC / "browser_session.py").read_text(encoding="utf-8")
        self.assertIn("_BUDGETED_COMMANDS", source)
        self.assertIn("ACTION_COMMANDS + TYPED_ACTION_COMMANDS", source)

    def test_answer_values_can_never_be_ui_references(self) -> None:
        _clean, error = tasks.validate_structured_answer({"title": "ui:3"})
        self.assertIn("ui: target reference", error)
        source = (SRC / "browser_tasks.py").read_text(encoding="utf-8")
        self.assertIn("valid_ui_ref", source)


class HelperCommandsTest(unittest.TestCase):
    def test_helper_carries_the_two_additive_commands(self) -> None:
        source = (TOOLS / "browser_window.swift").read_text(encoding="utf-8")
        for token in ('case "fill"', 'case "set_control"', "fillField",
                      "setControl", "validateTypedTarget", "jsLiteral"):
            self.assertIn(token, source, token)
        for error in ("password_field", "focus_failed", "option_not_found",
                      "control_unsupported", "refused_target_hidden",
                      "refused_target_disabled"):
            self.assertIn(error, source, error)

    def test_frozen_target_commands_are_untouched(self) -> None:
        source = (TOOLS / "browser_window.swift").read_text(encoding="utf-8")
        for command in ("navigate", "snapshot", "click", "type", "key", "scroll",
                        "back", "state", "quit", "targets", "click_target"):
            self.assertIn('case "{}"'.format(command), source, command)

    def test_marker_lists_are_frozen(self) -> None:
        self.assertIn("password", bt.CREDENTIAL_MARKERS)
        self.assertIn("submit", bt.SUBMIT_MARKERS)
        self.assertIn("save", bt.SUBMIT_MARKERS)
        self.assertIn("checkout", bt.SUBMIT_MARKERS)


if __name__ == "__main__":
    unittest.main()
