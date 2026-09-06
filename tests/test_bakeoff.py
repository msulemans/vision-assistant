from __future__ import annotations

import unittest

from vision_assistant.bakeoff import (
    FROZEN_BAKEOFF,
    Candidate,
    _p95,
    bad_adapter,
    gold_adapter,
    promote,
    run_candidate,
)
from vision_assistant.corpus import build_corpus


def _fake(name: str, params_b: float, size_mib: float, first_ms: float, complete_ms: float) -> Candidate:
    return Candidate(
        name=name,
        family="probe",
        params_b=params_b,
        licence="Apache-2.0",
        quantization="q4",
        revision="fake",
        sha256="fake",
        runtime_kind="fake",
        artifact_size_mib=size_mib,
        cold_readiness_ms=30000.0,
        rss_gib=4.0,
        swap_mib=100.0,
        acquisition_gib=12.0,
        first_token_ms=first_ms,
        complete_ms=complete_ms,
    )


class BakeoffHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.held = [c for c in build_corpus() if c.split == "heldout"]
        self.gold = gold_adapter()
        self.bad = bad_adapter()

    def test_frozen_contract_is_locked(self) -> None:
        self.assertEqual(FROZEN_BAKEOFF["schema_version"], "1.0")
        self.assertIn("candidate_rule", FROZEN_BAKEOFF)
        self.assertIn("promotion", FROZEN_BAKEOFF)
        kinds = {r["kind"] for r in FROZEN_BAKEOFF["runtime_matrix"]}
        self.assertTrue({"llama.cpp", "mlx-vlm", "ollama"}.issubset(kinds))
        self.assertIn("cold_readiness_ms", FROZEN_BAKEOFF["ceilings"])
        self.assertIn("balanced_active_rss_gib", FROZEN_BAKEOFF["ceilings"])

    def test_gold_candidates_pass_and_mini_wins(self) -> None:
        mini = run_candidate(_fake("gold-mini", 1.0, 2000, 1200, 8000), self.gold, self.held)
        large = run_candidate(_fake("gold-large", 4.0, 6000, 2500, 14000), self.gold, self.held)
        promoted = promote([large, mini])
        self.assertTrue(mini["pass_thresholds"])
        self.assertTrue(large["pass_thresholds"])
        self.assertEqual(promoted, "gold-mini")

    def test_bad_candidate_fails_the_gate(self) -> None:
        bad = run_candidate(_fake("bad-tiny", 0.5, 1000, 800, 5000), self.bad, self.held)
        self.assertFalse(bad["pass_thresholds"])
        self.assertFalse(bad["quality_ok"])
        self.assertGreater(bad["forbidden_claims"], 0)

    def test_nearest_rank_p95(self) -> None:
        data = list(range(1, 21))  # 20 values, 95th percentile = 19
        self.assertEqual(_p95(data), 19.0)
        self.assertEqual(_p95([]), 0.0)


if __name__ == "__main__":
    unittest.main()
