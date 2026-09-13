from __future__ import annotations

import hashlib
import json
import unittest

from vision_assistant.corpus import CATEGORIES, build_corpus, manifest
from vision_assistant.corpus_cli import FROZEN, bad_answer, gold_answer
from vision_assistant.ports import LabelledAnswer
from vision_assistant.scorer import score


class CorpusMilestoneTest(unittest.TestCase):
    """Deterministic gate checks for the Milestone 004 frozen corpus."""

    def setUp(self) -> None:
        self.cases = build_corpus()

    def test_case_count_and_splits(self) -> None:
        self.assertEqual(len(self.cases), 48)
        self.assertEqual(sum(1 for c in self.cases if c.split == "dev"), 24)
        self.assertEqual(sum(1 for c in self.cases if c.split == "heldout"), 24)

    def test_eight_categories_six_each(self) -> None:
        by_cat: dict[str, int] = {}
        for case in self.cases:
            by_cat[case.category] = by_cat.get(case.category, 0) + 1
        self.assertEqual(set(by_cat), set(CATEGORIES))
        for category in CATEGORIES:
            self.assertEqual(by_cat[category], 6)

    def test_deterministic_manifest(self) -> None:
        m1 = json.dumps(manifest(self.cases), sort_keys=True).encode("utf-8")
        m2 = json.dumps(manifest(build_corpus()), sort_keys=True).encode("utf-8")
        self.assertEqual(hashlib.sha256(m1).hexdigest(), hashlib.sha256(m2).hexdigest())

    def test_every_case_has_sha256_and_dims(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertEqual(len(case.content_sha256), 64)
                self.assertEqual((case.width, case.height), (480, 300))
                self.assertEqual(case.fixture.width, case.width)

    def test_gold_answers_pass(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertTrue(score(case, gold_answer(case))["pass"])

    def test_bad_answers_fail(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertFalse(score(case, bad_answer(case))["pass"])

    def test_frozen_config_thresholds_are_locked(self) -> None:
        self.assertEqual(FROZEN["corpus_size"], 48)
        self.assertEqual(FROZEN["dev_cases"], 24)
        self.assertEqual(FROZEN["heldout_cases"], 24)
        self.assertIn("promotion", FROZEN)
        self.assertIn("ceilings", FROZEN)
        self.assertLessEqual(FROZEN["thresholds"]["unsupported_claim_rate"], 0.05)

    def test_numeric_evidence_counts_as_recall(self) -> None:
        """A short but meaningful number ("78" in "CPU 78%") must not be dropped."""
        case = next(c for c in self.cases if c.case_id == "m004-dashboard-01")
        paraphrase = LabelledAnswer(visible=("The CPU usage reads 78 percent.",), inferred=(), unknown=())
        self.assertEqual(score(case, paraphrase)["required_fact_recall"], 1.0)
        vague = LabelledAnswer(visible=("The CPU looks busy.",), inferred=(), unknown=())
        self.assertEqual(score(case, vague)["required_fact_recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
