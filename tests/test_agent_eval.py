from __future__ import annotations

import unittest

from vision_assistant.agent_eval import (
    INTERRUPT_P95_CEILING_MS,
    run_interrupt_sampling,
    run_scenarios,
)


class ScenarioGateTest(unittest.TestCase):
    def test_gate_reports_all_pass_and_zero_unapproved(self) -> None:
        report = run_scenarios()
        gate = report["gate"]
        self.assertTrue(gate["all_pass"])
        self.assertEqual(gate["passed"], gate["scenarios"])
        self.assertEqual(gate["unapproved_total"], 0)
        self.assertGreaterEqual(gate["scenarios"], 20)

    def test_gate_result_rows_are_consistent(self) -> None:
        report = run_scenarios()
        for result in report["results"]:
            self.assertEqual(result["perform_calls"], result["steps_used"])
            if result["expected_terminal"] == "finished":
                self.assertEqual(result["terminal"], "finished")


class InterruptSamplingTest(unittest.TestCase):
    def test_interrupt_children_cancel_cleanly(self) -> None:
        report = run_interrupt_sampling(count=3, delay_ms=30)
        gate = report["gate"]
        self.assertEqual(gate["samples_ok"], 3)
        self.assertIsNotNone(gate["p95_ms"])
        self.assertLessEqual(gate["p95_ms"], INTERRUPT_P95_CEILING_MS)
        self.assertTrue(gate["pass"])
        for sample in report["samples"]:
            self.assertEqual(sample["exit_code"], 130)
            self.assertTrue(sample["cancelled_line"])


if __name__ == "__main__":
    unittest.main()
