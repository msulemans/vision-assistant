from __future__ import annotations

import unittest
from pathlib import Path

from vision_assistant import browser_session as bs
from vision_assistant import browser_tasks as tasks

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
SRC = REPO_ROOT / "src" / "vision_assistant"

SYNTHESIS_TOKENS = (
    "NSEvent", "sendEvent", "CGEvent", "CGWarpMouseCursorPosition",
    "CGEventPostToPid", "CGEventCreateMouseEvent", "pyautogui", "pynput",
)


class SynthesisSurfaceTest(unittest.TestCase):
    def test_only_browser_window_synthesizes_ui_events(self) -> None:
        for path in sorted(TOOLS.glob("*.swift")):
            source = path.read_text(encoding="utf-8")
            if path.name == "browser_window.swift":
                self.assertIn("NSEvent.mouseEvent(", source)
                self.assertIn("window.sendEvent(", source)
                self.assertNotIn("CGEvent", source)
            elif path.name == "ax_action.swift":
                # The M013-sanctioned writer uses keyboard CGEvent only; it
                # must never grow in-app NSEvent synthesis or mouse APIs.
                self.assertNotIn("NSEvent", source)
                for token in ("CGEventCreateMouseEvent", "CGWarpMouseCursorPosition",
                              "CGEventCreateScrollWheelEvent", "CGEventPostToPid"):
                    self.assertNotIn(token, source)
            else:
                for token in ("NSEvent", "sendEvent", "CGEvent"):
                    self.assertNotIn(token, source, "{} in {}".format(token, path.name))

    def test_browser_window_keeps_the_frozen_guards(self) -> None:
        source = (TOOLS / "browser_window.swift").read_text(encoding="utf-8")
        for token in ("nonPersistent", "decidePolicyFor", "focusScript",
                      "url.port == self.port", "stale_frame", "password_field",
                      "no_editable_focus", "outside_viewport"):
            self.assertIn(token, source, token)
        self.assertNotIn("CGEvent", source)

    def test_no_event_synthesis_in_python(self) -> None:
        for path in sorted(SRC.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in SYNTHESIS_TOKENS:
                self.assertNotIn(token, source, "{} in {}".format(token, path.name))

    def test_helper_protocol_commands_match_the_adapter(self) -> None:
        source = (TOOLS / "browser_window.swift").read_text(encoding="utf-8")
        for command in ("navigate", "snapshot", "click", "type", "key", "scroll",
                        "back", "state", "quit", "targets", "click_target"):
            self.assertIn('case "{}"'.format(command), source, command)
        self.assertEqual(
            bs.ACTION_COMMANDS,
            ("navigate", "click", "click_target", "type", "key", "scroll", "back"))


class AdapterContractTest(unittest.TestCase):
    def test_budgets_come_from_the_frozen_manifest(self) -> None:
        source = (SRC / "browser_session.py").read_text(encoding="utf-8")
        self.assertIn('tasks.LIMITS["max_action_steps"]', source)
        self.assertIn('tasks.LIMITS["max_seconds"]', source)

    def test_refusal_reasons_are_typed_and_stable(self) -> None:
        # Reasons the ADAPTER itself raises (helper-side codes surface as
        # pass-through BrowserErrors; all five target codes are pinned by
        # TargetExtractionPrivacyTest and browser_targets.TARGET_REFUSAL_HINTS).
        reasons = (
            "refused_origin", "refused_stale", "refused_viewport",
            "refused_password", "refused_focus", "budget_steps", "budget_seconds",
            "timeout", "unhealthy", "closed", "compile_failed", "helper_not_ready",
            "refused_target_stale",
        )
        source = (SRC / "browser_session.py").read_text(encoding="utf-8")
        for reason in reasons:
            self.assertIn('"{}"'.format(reason), source, reason)

    def test_default_viewport_matches_the_manifest(self) -> None:
        session = bs.BrowserSession(port=1)
        self.assertEqual((session.width, session.height),
                         (tasks.VIEWPORT["width"], tasks.VIEWPORT["height"]))

    def test_manifest_limits_still_frozen(self) -> None:
        self.assertEqual(tasks.LIMITS["max_action_steps"], 20)
        self.assertEqual(tasks.LIMITS["max_seconds"], 120)


class TargetExtractionPrivacyTest(unittest.TestCase):
    def _extract_script(self) -> str:
        source = (TOOLS / "browser_window.swift").read_text(encoding="utf-8")
        start = (source.index('let extractScript = """')
                 + len('let extractScript = """'))
        end = source.index('"""', start)
        return source[start:end]

    def test_extraction_script_reads_only_the_visible_surface(self) -> None:
        script = self._extract_script()
        self.assertIn("m018Targets", script)
        self.assertIn("getBoundingClientRect", script)
        for token in (".value", ".href", "getAttribute(", "localStorage",
                      "sessionStorage", "cookie", "fetch(", "XMLHttpRequest",
                      "WebSocket", "postMessage", "innerHTML", "outerHTML",
                      "document.write"):
            self.assertNotIn(token, script, token)

    def test_helper_carries_the_five_target_refusal_codes(self) -> None:
        source = (TOOLS / "browser_window.swift").read_text(encoding="utf-8")
        for code in ("refused_target_stale", "refused_target_hidden",
                     "refused_target_disabled", "refused_target_moved",
                     "refused_target_offscreen"):
            self.assertIn(code, source, code)
        self.assertIn("sendClickEvents", source)
        self.assertIn("clickTarget", source)


if __name__ == "__main__":
    unittest.main()
