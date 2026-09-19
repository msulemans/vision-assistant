from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vision_assistant.ax_vision import AxUnavailable, AxVisionAdapter

PARSE_PAYLOAD = {
    "app": "FixtureApp",
    "pid": 42,
    "trusted": True,
    "windows": [
        {
            "title": "SETTINGS",
            "focused": True,
            "cg_window_id": 777,
            "frame": {"x": 100.0, "y": 50.0, "w": 520.0, "h": 340.0},
            "elements": [
                {
                    "role": "AXButton",
                    "title": "SAVE",
                    "identifier": "a.save",
                    "frame": {"x": 300.0, "y": 300.0, "w": 100.0, "h": 30.0},
                    "enabled": True,
                    "focused": False,
                },
                {
                    "role": "AXGroup",
                    "title": "PANEL",
                    "value": 3,
                    "children": [
                        {"role": "AXStaticText", "value": "READY", "enabled": False},
                    ],
                },
                {
                    "role": "AXTextField",
                    "subrole": "AXSecureTextField",
                    "value": "<redacted-secure>",
                    "secure": True,
                },
            ],
        }
    ],
}


def _fake_helper(tool_dir: Path, body: str) -> None:
    tool_dir.mkdir(parents=True, exist_ok=True)
    helper = tool_dir / "ax_dump"
    helper.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    helper.chmod(0o700)


def _json_helper(tool_dir: Path, payload: object, exit_code: int = 0) -> None:
    _fake_helper(
        tool_dir,
        "import json, sys\n"
        f"print(json.dumps({payload!r}))\n"
        f"sys.exit({exit_code})\n",
    )


class AxVisionAdapterTest(unittest.TestCase):
    def _adapter(self, tool_dir: Path) -> AxVisionAdapter:
        return AxVisionAdapter(tool_dir=tool_dir, helper_source=tool_dir / "missing.swift")

    def test_check_reports_trust_without_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _json_helper(root / "tools", {"trusted": True})
            self.assertTrue(self._adapter(root / "tools").check()["trusted"])
            _json_helper(root / "tools2", {"trusted": False})
            self.assertFalse(self._adapter(root / "tools2").check()["trusted"])

    def test_snapshot_parses_windows_and_element_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _json_helper(root / "tools", PARSE_PAYLOAD)
            snapshot = self._adapter(root / "tools").snapshot(pid=42)
            self.assertEqual(snapshot.app, "FixtureApp")
            self.assertEqual(snapshot.pid, 42)
            self.assertEqual(len(snapshot.windows), 1)
            window = snapshot.windows[0]
            self.assertEqual(window.title, "SETTINGS")
            self.assertEqual(window.frame, (100.0, 50.0, 520.0, 340.0))
            self.assertTrue(window.focused)
            self.assertEqual(window.cg_window_id, 777)
            paths = [element.path for element in window.elements]
            self.assertEqual(paths, ["w0/0", "w0/1", "w0/1/0", "w0/2"])
            button = window.elements[0]
            self.assertEqual(button.frame, (300.0, 300.0, 100.0, 30.0))
            self.assertEqual(button.display_name, "SAVE")
            group_child = window.elements[2]
            self.assertEqual(group_child.depth, 1)
            self.assertEqual(group_child.enabled, False)
            self.assertEqual(window.elements[1].value, "3")  # numbers become strings

    def test_secure_values_are_dropped_even_if_the_helper_sends_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "app": "FixtureApp",
                "pid": 1,
                "trusted": True,
                "windows": [
                    {
                        "elements": [
                            {
                                "role": "AXTextField",
                                "subrole": "AXSecureTextField",
                                "value": "hunter2",
                            }
                        ]
                    }
                ],
            }
            _json_helper(root / "tools", payload)
            snapshot = self._adapter(root / "tools").snapshot(pid=1)
            element = snapshot.windows[0].elements[0]
            self.assertTrue(element.secure)
            self.assertIsNone(element.value)
            self.assertNotIn("hunter2", repr(snapshot))

    def test_permission_denial_is_a_typed_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _json_helper(root / "tools", {"error": "permission", "trusted": False}, exit_code=2)
            with self.assertRaises(AxUnavailable) as caught:
                self._adapter(root / "tools").snapshot(pid=7)
            self.assertEqual(caught.exception.reason, "permission")

    def test_invalid_json_raises_bad_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fake_helper(root / "tools", "import sys\nsys.stdout.write('not json')\n")
            with self.assertRaises(AxUnavailable) as caught:
                self._adapter(root / "tools").snapshot(pid=7)
            self.assertEqual(caught.exception.reason, "bad_output")

    def test_helper_is_called_with_exactly_the_requested_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool_dir = root / "tools"
            tool_dir.mkdir(parents=True, exist_ok=True)
            helper = tool_dir / "ax_dump"
            helper.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "expected = " + json.dumps(["--dump", "--pid", "42", "--max-depth", "6"]) + "\n"
                "if sys.argv[1:] != expected:\n"
                "    sys.exit(9)\n"
                "print(json.dumps({'app': 'ok', 'pid': 42, 'trusted': True, 'windows': []}))\n",
                encoding="utf-8",
            )
            helper.chmod(0o700)
            adapter = self._adapter(tool_dir)
            snapshot = adapter.snapshot(pid=42, max_depth=6)
            self.assertEqual(snapshot.app, "ok")
            self.assertEqual(snapshot.windows, ())

            helper.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if sys.argv[1:] != ['--dump', '--frontmost']:\n"
                "    sys.exit(9)\n"
                "print(json.dumps({'app': 'ok', 'pid': 42, 'trusted': True, 'windows': []}))\n",
                encoding="utf-8",
            )
            helper.chmod(0o700)
            adapter = self._adapter(tool_dir)
            self.assertEqual(adapter.snapshot(frontmost=True).app, "ok")

    def test_missing_source_and_no_toolchain_raise_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = AxVisionAdapter(tool_dir=root / "tools", helper_source=root / "missing.swift")
            with self.assertRaises(AxUnavailable) as caught:
                adapter.snapshot(pid=1)
            self.assertIn(caught.exception.reason, {"compile", "toolchain"})


if __name__ == "__main__":
    unittest.main()
