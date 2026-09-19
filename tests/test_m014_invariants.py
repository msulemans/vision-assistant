from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
SRC = REPO_ROOT / "src" / "vision_assistant"

# M014 additions must not widen the writer surface: the Python agent modules
# contain no action APIs, and the extended Swift tools stay read-only except
# the frozen `ax_action.swift` (checked by the M013 invariant suite).
ACTION_TOKENS = (
    "AXUIElementPerformAction",
    "AXUIElementSetAttributeValue",
    "CGEvent",
    "kAXPressAction",
    "osascript",
    "pyautogui",
    "pynput",
    "Quartz",
)


class AgentSurfaceTest(unittest.TestCase):
    def test_agent_modules_have_no_action_apis(self) -> None:
        for name in ("agent.py", "agent_cli.py", "agent_eval.py"):
            source = (SRC / name).read_text(encoding="utf-8")
            for token in ACTION_TOKENS:
                self.assertNotIn(token, source, f"{token!r} in {name}")

    def test_agent_acts_only_through_the_injected_port(self) -> None:
        source = (SRC / "agent.py").read_text(encoding="utf-8")
        self.assertIn("self.port.perform", source)
        self.assertIn("self.port.plan", source)
        self.assertNotIn("subprocess", source)

    def test_budgets_recovery_and_markers_are_frozen(self) -> None:
        source = (SRC / "agent.py").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_MAX_STEPS = 8", source)
        self.assertIn("DEFAULT_MAX_SECONDS = 120.0", source)
        self.assertIn("DEFAULT_MAX_RECOVERIES = 2", source)
        self.assertIn("RECOVERABLE_REFUSALS", source)
        self.assertIn("INJECTION_MARKERS", source)
        self.assertIn("unapproved_actions", source)

    def test_eval_ceiling_is_registered(self) -> None:
        source = (SRC / "agent_eval.py").read_text(encoding="utf-8")
        self.assertIn("INTERRUPT_P95_CEILING_MS = 1500.0", source)


class ToolSurfaceTest(unittest.TestCase):
    def test_practice_window_exposes_m014_controls(self) -> None:
        source = (TOOLS / "practice_window.swift").read_text(encoding="utf-8")
        for identifier in (
            "app:sync-toggle",
            "app:notify-toggle",
            "app:search",
            "app:save",
            "app:cancel",
            "app:dialog-button",
            "app:injection-button",
            "app:nudge-button",
        ):
            self.assertIn(identifier, source)
        self.assertIn("NSAlert", source)
        self.assertIn("runModal", source)
        self.assertIn("--dialog-after", source)
        for token in ACTION_TOKENS:
            self.assertNotIn(token, source, f"{token!r} in practice_window.swift")

    def test_ax_dump_front_mode_stays_read_only(self) -> None:
        source = (TOOLS / "ax_dump.swift").read_text(encoding="utf-8")
        self.assertIn('case "--front"', source)
        self.assertIn("frontmostApplication", source)
        self.assertIn('object["subrole"]', source)
        for token in ACTION_TOKENS:
            self.assertNotIn(token, source, f"{token!r} in ax_dump.swift")


if __name__ == "__main__":
    unittest.main()
