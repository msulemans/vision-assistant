"""Gate boundaries independent of image rendering or model execution."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vision_assistant.bakeoff import Candidate, run_candidate
from vision_assistant.ports import LabelledAnswer


class BakeoffGateTest(unittest.TestCase):
    def run_rows(self, passes=23, *, forbidden=0, missing=False, count=24):
        candidate = Candidate(
            name="gate-fixture", family="fake", params_b=4, licence="test",
            quantization="fake", revision="fake", sha256="fake",
            runtime_kind="fake", artifact_size_mib=3000,
            first_token_ms=839, complete_ms=1389,
            cold_readiness_ms=30000, rss_gib=3.792, swap_mib=0,
            acquisition_gib=4,
        )
        if missing:
            candidate = replace(candidate, cold_readiness_ms=None, acquisition_gib=None)
        cases = [SimpleNamespace(case_id=str(i), category="dialog") for i in range(count)]
        rows = [dict(
            case_id=str(i), category="dialog", split="heldout",
            required_fact_recall=1.0, unsupported_claim_rate=0.0,
            forbidden_claim_count=forbidden if i == 0 else 0,
            ui_string_match=1.0 if i < passes else 0.0,
            abstain_correct=True, **{"pass": i < passes},
        ) for i in range(count)]
        with patch("vision_assistant.bakeoff.score", side_effect=rows):
            return run_candidate(candidate, lambda _: LabelledAnswer((), (), ()), cases)

    def test_v4_accepts_23_of_24_with_complete_resources(self):
        result = self.run_rows()
        self.assertTrue(result["quality_ok"])
        self.assertTrue(result["pass_thresholds"])
        self.assertAlmostEqual(result["case_pass_rate"], 23 / 24)
        self.assertEqual(result["required_case_pass_rate"], 0.95)

    def test_v4_rejects_22_of_24(self):
        self.assertFalse(self.run_rows(passes=22)["quality_ok"])

    def test_pass_rate_does_not_override_forbidden_claims(self):
        self.assertFalse(self.run_rows(forbidden=1)["quality_ok"])

    def test_missing_resources_block_overall_pass_not_quality(self):
        result = self.run_rows(missing=True)
        self.assertTrue(result["quality_ok"])
        self.assertFalse(result["resource_ok"])
        self.assertFalse(result["pass_thresholds"])
        self.assertEqual(result["resource_measured"], 2)
        self.assertEqual(result["missing_resources"], ["cold_readiness_ms", "acquisition_gib"])

    def test_empty_run_cannot_pass(self):
        self.assertFalse(self.run_rows(count=0)["pass_thresholds"])
