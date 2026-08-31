from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from vision_assistant.cli import SCENARIOS, run_scenario
from vision_assistant.fixture import generate_fixture

EXPECTED_FINAL = {
    "success": "done",
    "failure": "failed",
    "cancel": "cancelled",
    "timeout": "timed_out",
}


class SpineRegressionTest(unittest.TestCase):
    """Deterministic gate checks for the Milestone 002 event spine."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.outdir = Path(self._tmp.name)
        self.fixture = generate_fixture(path=self.outdir / "fixtures" / "fixture.png")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_terminal_states(self) -> None:
        for name, expected in EXPECTED_FINAL.items():
            with self.subTest(name=name):
                final, path, _ = run_scenario(name, outdir=self.outdir, fixture=self.fixture)
                self.assertEqual(final, expected)
                self.assertTrue(path.exists())

    def test_deterministic_and_round_trip(self) -> None:
        for name in SCENARIOS:
            with self.subTest(name=name):
                _, p1, records1 = run_scenario(name, outdir=self.outdir, fixture=self.fixture)
                _, p2, records2 = run_scenario(name, outdir=self.outdir, fixture=self.fixture)
                self.assertEqual(
                    hashlib.sha256(p1.read_bytes()).hexdigest(),
                    hashlib.sha256(p2.read_bytes()).hexdigest(),
                )
                self.assertEqual(records1, records2)

    def test_cancel_suppresses_later_events(self) -> None:
        _, _, records = run_scenario("cancel", outdir=self.outdir, fixture=self.fixture)
        types = [r.get("type") for r in records]
        self.assertIn("turn.cancelled", types)
        self.assertNotIn("model.started", types)
        self.assertNotIn("answer.ready", types)

    def test_failure_keeps_reason_and_no_answer(self) -> None:
        _, _, records = run_scenario("failure", outdir=self.outdir, fixture=self.fixture)
        types = [r.get("type") for r in records]
        self.assertIn("turn.failed", types)
        self.assertNotIn("answer.ready", types)


if __name__ == "__main__":
    unittest.main()
