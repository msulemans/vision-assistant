from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from vision_assistant import action_loop as action_loop_module
from vision_assistant import practice_app as practice_app_module
from vision_assistant import sim_cli as sim_cli_module
from vision_assistant.action_loop import SimulatedActionLoop
from vision_assistant.capture import normalize_png
from vision_assistant.practice_app import FROZEN_TASKS, PracticeApp

TASKS = {task.task_id: task for task in FROZEN_TASKS}

FORBIDDEN_SOURCE_TOKENS = (
    "subprocess",
    "osascript",
    "popen",
    "pynput",
    "quartz",
    "cgevent",
    "pyautogui",
    "ctypes",
    "import os",
)


class LoopFlowTest(unittest.TestCase):
    def test_click_task_completes_with_expected_event_order(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [  # noqa: E731
            {"kind": "click_element", "element_id": "app:sync-toggle"}
        ]
        result = SimulatedActionLoop(app, TASKS["enable-sync"], proposer).run()
        self.assertEqual(result["status"], "done")
        self.assertTrue(app.state["sync_enabled"])
        self.assertEqual(result["host_input_events"], 0)
        types = [event["type"] for event in result["events"]]
        self.assertEqual(
            types,
            ["observe", "propose", "validate", "approve", "execute", "verify", "done"],
        )

    def test_type_text_task_completes(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [  # noqa: E731
            {"kind": "type_text", "text": "hello", "field": "search"}
        ]
        result = SimulatedActionLoop(app, TASKS["type-search"], proposer).run()
        self.assertEqual(result["status"], "done")
        self.assertEqual(app.state["search_text"], "hello")

    def test_escape_closes_the_dialog(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [  # noqa: E731
            {"kind": "press_key", "key": "escape"}
        ]
        result = SimulatedActionLoop(app, TASKS["cancel-dialog"], proposer).run()
        self.assertEqual(result["status"], "done")
        self.assertFalse(app.state["dialog_open"])

    def test_denied_intent_is_final_and_never_executes(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [  # noqa: E731
            {"kind": "type_text", "text": "hunter2!", "field": "Password"}
        ]
        result = SimulatedActionLoop(app, TASKS["type-search"], proposer).run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "denied")
        self.assertEqual(app.state["search_text"], "")
        self.assertNotIn("execute", [event["type"] for event in result["events"]])

    def test_cancel_is_final(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [{"kind": "cancel"}]  # noqa: E731
        result = SimulatedActionLoop(app, TASKS["enable-sync"], proposer).run()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["reason"], "cancel_intent")

    def test_stale_observation_is_refused(self) -> None:
        app = PracticeApp()

        def proposer(png, instruction, revision):
            app.revision += 1  # the app changed after the observation
            return [{"kind": "click_element", "element_id": "app:sync-toggle"}]

        result = SimulatedActionLoop(app, TASKS["enable-sync"], proposer).run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "stale_observation")
        self.assertFalse(app.state["sync_enabled"])
        executes = [event for event in result["events"] if event["type"] == "execute"]
        self.assertEqual(executes[-1]["applied"], False)

    def test_approver_denial_is_final(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [  # noqa: E731
            {"kind": "click_element", "element_id": "app:sync-toggle"}
        ]
        loop = SimulatedActionLoop(
            app, TASKS["enable-sync"], proposer, approver=lambda intent, decision: False
        )
        result = loop.run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "approval_denied")
        self.assertFalse(app.state["sync_enabled"])

    def test_unknown_element_exhausts_retries(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [  # noqa: E731
            {"kind": "click_element", "element_id": "app:missing"}
        ]
        result = SimulatedActionLoop(app, TASKS["enable-sync"], proposer).run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "execute_failed")
        retries = [event for event in result["events"] if event["type"] == "retry"]
        self.assertEqual(len(retries), 3)  # MAX_RETRIES + the denying attempt

    def test_step_budget_blocks_an_observe_loop(self) -> None:
        app = PracticeApp()
        proposer = lambda png, instruction, revision: [{"kind": "observe"}]  # noqa: E731
        loop = SimulatedActionLoop(app, TASKS["enable-sync"], proposer, max_steps=3)
        result = loop.run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "step_budget_exhausted")
        self.assertEqual(result["steps"], 3)

    def test_emergency_stop_is_final(self) -> None:
        app = PracticeApp()
        holder: dict = {}

        def proposer(png, instruction, revision):
            holder["loop"].stop()
            return [{"kind": "observe"}]

        loop = SimulatedActionLoop(app, TASKS["enable-sync"], proposer)
        holder["loop"] = loop
        result = loop.run()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["reason"], "emergency_stop")


class InvariantTest(unittest.TestCase):
    def test_no_execution_capability_in_the_m011_modules(self) -> None:
        for module in (action_loop_module, practice_app_module, sim_cli_module):
            source = Path(inspect.getsourcefile(module)).read_text(encoding="utf-8").lower()
            for token in FORBIDDEN_SOURCE_TOKENS:
                with self.subTest(module=module.__name__, token=token):
                    self.assertNotIn(token, source)

    def test_render_is_a_valid_stable_png(self) -> None:
        app = PracticeApp()
        first = app.render()
        normalize_png(first)
        self.assertEqual(first, app.render())
        app.state["sync_enabled"] = True
        app.revision += 1
        self.assertNotEqual(first, app.render())


if __name__ == "__main__":
    unittest.main()
