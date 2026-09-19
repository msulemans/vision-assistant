from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from vision_assistant.grounding_eval import run_frozen_gate
from vision_assistant.grounding_fixture import FROZEN_TASKS
from vision_assistant.pixels import decode_png


def _buggy_region(frame, window_frame, image_size, *, clip=True):
    """A plausible regression: forget to subtract the window origin."""
    iw, ih = image_size
    scale_x = iw / window_frame[2]
    scale_y = ih / window_frame[3]
    return (
        round(frame[0] * scale_x),
        round(frame[1] * scale_y),
        round(frame[2] * scale_x),
        round(frame[3] * scale_y),
    )


class FrozenGateTest(unittest.TestCase):
    def test_gate_passes_on_every_task_and_variant_and_is_deterministic(self) -> None:
        first = run_frozen_gate(write=False)
        second = run_frozen_gate(write=False)
        self.assertEqual(first["summary"], second["summary"])
        summary = first["summary"]
        self.assertEqual(summary["checks"], len(FROZEN_TASKS) * 4)
        self.assertEqual(summary["passed"], summary["checks"])
        self.assertTrue(summary["gate_pass"])
        self.assertTrue(all(row["passed"] for row in first["rows"]))
        for name, counts in summary["variants"].items():
            self.assertEqual(counts, {"checks": len(FROZEN_TASKS), "passed": len(FROZEN_TASKS)})

    def test_gate_has_teeth_for_an_offset_mapping_regression(self) -> None:
        with mock.patch("vision_assistant.grounding.image_region_for_frame", new=_buggy_region):
            payload = run_frozen_gate(write=False)
        summary = payload["summary"]
        self.assertFalse(summary["gate_pass"])
        positives = [row for row in payload["rows"] if row["expect"] == "found"]
        self.assertTrue(positives)
        for row in positives:
            self.assertTrue(row["identity_ok"], row)
            self.assertFalse(row["region_ok"], row)
        negatives = [row for row in payload["rows"] if row["expect"] != "found"]
        self.assertTrue(all(row["passed"] for row in negatives))

    def test_gate_fails_when_an_expectation_points_at_the_wrong_element(self) -> None:
        tasks = tuple(
            replace(task, expected_id="backup") if task.task_id == "resolve-search-field" else task
            for task in FROZEN_TASKS
        )
        payload = run_frozen_gate(tasks=tasks, write=False)
        self.assertFalse(payload["summary"]["gate_pass"])
        failing = [row for row in payload["rows"] if row["task_id"] == "resolve-search-field"]
        self.assertEqual(len(failing), 4)
        for row in failing:
            self.assertFalse(row["identity_ok"])
            self.assertFalse(row["passed"])

    def test_gate_writes_result_json_and_renderable_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            payload = run_frozen_gate(out_dir=out_dir, write=True, run_id="test-run")
            result = out_dir / "grounding-test-run.json"
            self.assertTrue(result.is_file())
            written = json.loads(result.read_text(encoding="utf-8"))
            self.assertTrue(written["summary"]["gate_pass"])
            self.assertEqual(written["run_id"], "test-run")
            fixtures = out_dir / "fixtures"
            for name, size in (("stacked-1x", (520, 340)), ("stacked-2x", (1040, 680))):
                png = fixtures / f"{name}.png"
                self.assertTrue(png.is_file(), name)
                pixels = decode_png(png.read_bytes())
                self.assertEqual((pixels.width, pixels.height), size)
            self.assertEqual(len(list(fixtures.iterdir())), 4)


if __name__ == "__main__":
    unittest.main()
