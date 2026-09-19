from __future__ import annotations

import unittest
from pathlib import Path

from vision_assistant.package_cli import (
    INSTALL_SCRIPT,
    PERMISSION_EDUCATION,
    VISION_WRAPPER,
    audit_offline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "vision_assistant"

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
NETWORK_TOKENS = ("curl", "http://", "https://", "urllib", "pip install", "brew install")


class PackagingSurfaceTest(unittest.TestCase):
    def test_package_modules_have_no_action_apis(self) -> None:
        for name in ("profiles.py", "manifest.py", "package_cli.py"):
            source = (SRC / name).read_text(encoding="utf-8")
            for token in ACTION_TOKENS:
                self.assertNotIn(token, source, f"{token!r} in {name}")

    def test_doctor_never_prompts_for_permissions(self) -> None:
        source = (SRC / "package_cli.py").read_text(encoding="utf-8")
        self.assertNotIn("request_permission", source)
        self.assertIn("PERMISSION_EDUCATION", source)

    def test_installer_and_wrapper_are_offline(self) -> None:
        for template in (INSTALL_SCRIPT, VISION_WRAPPER):
            for token in NETWORK_TOKENS:
                self.assertNotIn(token, template, f"{token!r} in installer template")

    def test_wrapper_checks_venv_and_dispatches(self) -> None:
        self.assertIn("venv/bin/python", VISION_WRAPPER)
        self.assertIn("run the bundle's install.sh first", VISION_WRAPPER)
        for module in ("package_cli", "assistant_cli", "ui_server", "grounding_cli", "agent_cli"):
            self.assertIn(f"vision_assistant.{module}", VISION_WRAPPER)

    def test_permission_education_covers_the_three_capabilities(self) -> None:
        capabilities = " ".join(entry["capability"] for entry in PERMISSION_EDUCATION)
        self.assertIn("Read a selected window", capabilities)
        self.assertIn("Ground targets", capabilities)
        self.assertIn("Perform supervised actions", capabilities)
        for entry in PERMISSION_EDUCATION:
            for key in ("permission", "why", "default", "revoke"):
                self.assertTrue(entry.get(key), f"{key} missing in {entry['capability']}")


class OfflineInvariantTest(unittest.TestCase):
    def test_repo_source_passes_the_frozen_offline_audit(self) -> None:
        self.assertEqual(audit_offline(SRC), [])

    def test_manifest_module_is_network_free(self) -> None:
        source = (SRC / "manifest.py").read_text(encoding="utf-8")
        for token in ("urllib", "subprocess", "socket", "https://"):
            self.assertNotIn(token, source, f"{token!r} in manifest.py")


if __name__ == "__main__":
    unittest.main()
