from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SWIFT_SOURCE = REPO_ROOT / "tools" / "ax_dump.swift"
PYTHON_SOURCES = (
    REPO_ROOT / "src" / "vision_assistant" / "ax_vision.py",
    REPO_ROOT / "src" / "vision_assistant" / "grounding.py",
    REPO_ROOT / "src" / "vision_assistant" / "grounding_cli.py",
    REPO_ROOT / "src" / "vision_assistant" / "grounding_fixture.py",
    REPO_ROOT / "src" / "vision_assistant" / "grounding_eval.py",
)

# Action-capable APIs. Any of these in the M012 surface would mean the
# read-only claim is false: they perform Accessibility actions, write
# attribute values, or post synthetic input events.
FORBIDDEN_IN_SWIFT = (
    "AXUIElementPerformAction",
    "AXUIElementSetAttributeValue",
    "AXUIElementSetMessagingTimeout",
    "kAXPressAction",
    "kAXPickAction",
    "CGEvent",
    "postEvent",
    "NSPasteboard",
    "CGWarpMouseCursorPosition",
    "IOHIDPostEvent",
)

FORBIDDEN_IN_PYTHON = (
    "AXUIElementPerformAction",
    "AXUIElementSetAttributeValue",
    "CGEvent",
    "postEvent",
    "NSPasteboard",
    "osascript",
    "pyautogui",
    "pynput",
    "Quartz",
)


class ReadOnlySurfaceTest(unittest.TestCase):
    def test_swift_helper_contains_no_action_apis(self) -> None:
        source = SWIFT_SOURCE.read_text(encoding="utf-8")
        for token in FORBIDDEN_IN_SWIFT:
            self.assertNotIn(token, source, f"forbidden API {token!r} in ax_dump.swift")
        # Positive control: the helper really does read attributes.
        self.assertIn("AXUIElementCopyAttributeValue", source)
        # The permission prompt exists but only behind the explicit mode.
        self.assertIn("--request-permission", source)

    def test_python_surface_contains_no_action_apis(self) -> None:
        for path in PYTHON_SOURCES:
            source = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_IN_PYTHON:
                self.assertNotIn(token, source, f"forbidden API {token!r} in {path.name}")

    def test_only_the_explicit_flag_requests_permission(self) -> None:
        helper = (REPO_ROOT / "src" / "vision_assistant" / "ax_vision.py").read_text(encoding="utf-8")
        snapshot_body = helper.split("def snapshot(")[1].split("def ")[0]
        self.assertNotIn("request_permission", snapshot_body)
        cli = (REPO_ROOT / "src" / "vision_assistant" / "grounding_cli.py").read_text(encoding="utf-8")
        self.assertIn("--request-permission", cli)


if __name__ == "__main__":
    unittest.main()
