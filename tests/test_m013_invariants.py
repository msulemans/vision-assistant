from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
SRC = REPO_ROOT / "src" / "vision_assistant"

# The writer surface is frozen: exactly one Swift file may contain action
# APIs, and no file anywhere may contain synthetic mouse-event APIs. Clicks
# are AXPress actions on identified elements; coordinates never address.
WRITER_APIS = ("AXUIElementPerformAction", "AXUIElementSetAttributeValue", "CGEvent(keyboardEventSource:")
ACTION_APIS_FORBIDDEN_ELSEWHERE = (
    "AXUIElementPerformAction",
    "AXUIElementSetAttributeValue",
    "CGEvent",
    "kAXPressAction",
)
MOUSE_EVENT_APIS = (
    "CGEventCreateMouseEvent",
    "CGWarpMouseCursorPosition",
    "CGEventCreateScrollWheelEvent",
    "CGEventPostToPid",  # never post events at another process explicitly
)


class WriterSurfaceTest(unittest.TestCase):
    def test_only_ax_action_contains_writer_apis(self) -> None:
        for path in sorted(TOOLS.glob("*.swift")):
            source = path.read_text(encoding="utf-8")
            if path.name == "ax_action.swift":
                for token in WRITER_APIS:
                    self.assertIn(token, source, f"{token!r} missing from ax_action.swift")
            else:
                for token in ACTION_APIS_FORBIDDEN_ELSEWHERE:
                    self.assertNotIn(token, source, f"{token!r} in {path.name}")

    def test_no_mouse_event_apis_anywhere(self) -> None:
        for path in list(TOOLS.glob("*.swift")) + list(SRC.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in MOUSE_EVENT_APIS:
                self.assertNotIn(token, source, f"{token!r} in {path}")

    def test_m013_python_layer_has_no_action_apis(self) -> None:
        for path in (SRC / "executor.py", SRC / "supervised_cli.py"):
            source = path.read_text(encoding="utf-8")
            for token in ("AXUIElementPerformAction", "AXUIElementSetAttributeValue", "CGEvent", "osascript", "pyautogui", "pynput", "Quartz"):
                self.assertNotIn(token, source, f"{token!r} in {path.name}")

    def test_practice_window_exposes_the_frozen_identifiers(self) -> None:
        source = (TOOLS / "practice_window.swift").read_text(encoding="utf-8")
        for identifier in ("app:sync-toggle", "app:notify-toggle", "app:search", "app:save", "app:cancel"):
            self.assertIn(identifier, source)
        self.assertIn("setAccessibilityIdentifier", source)

    def test_overlay_cannot_take_focus_or_mouse_events(self) -> None:
        source = (TOOLS / "ax_overlay.swift").read_text(encoding="utf-8")
        self.assertIn("ignoresMouseEvents", source)
        self.assertIn("override var canBecomeKey: Bool { false }", source)
        self.assertIn("override var canBecomeMain: Bool { false }", source)


if __name__ == "__main__":
    unittest.main()
