from __future__ import annotations

import unittest
from types import SimpleNamespace

from vision_assistant.augment_cli import FROZEN_SUBSET, evaluate, select_cases, summarize


def _case(case_id: str, split: str = "heldout"):
    return SimpleNamespace(case_id=case_id, split=split)


def _score(
    *,
    passed: bool,
    ui: float,
    unsupported: float = 0.0,
    forbidden: int = 0,
    recall: float = 1.0,
    abstain: bool = True,
) -> dict:
    return {
        "pass": passed,
        "ui_string_match": ui,
        "required_fact_recall": recall,
        "unsupported_claim_rate": unsupported,
        "forbidden_claim_count": forbidden,
        "abstain_correct": abstain,
    }


class SelectCasesTest(unittest.TestCase):
    def test_frozen_subset_resolves_in_order(self) -> None:
        cases = [_case(case_id) for case_id in FROZEN_SUBSET]
        selected = select_cases(cases)
        self.assertEqual([case.case_id for case in selected], list(FROZEN_SUBSET))

    def test_unknown_ids_fail_loudly(self) -> None:
        with self.assertRaises(SystemExit):
            select_cases([_case("m004-dialog-14")], case_ids=["nope"])

    def test_heldout_all_filters_splits(self) -> None:
        cases = [
            _case("a", split="dev"),
            _case("b", split="heldout"),
            _case("c", split="legacy"),
        ]
        selected = select_cases(cases, heldout_all=True)
        self.assertEqual([case.case_id for case in selected], ["b"])


class SummarizeEvaluateTest(unittest.TestCase):
    def _rows(self) -> list[dict]:
        return [
            {
                "case_id": "m004-dialog-14",
                "baseline": _score(passed=False, ui=0.0),
                "ocr": _score(passed=True, ui=1.0),
            },
            {
                "case_id": "m004-small_text-13",
                "baseline": _score(passed=True, ui=1.0),
                "ocr": _score(passed=False, ui=0.5, unsupported=0.1),
            },
        ]

    def test_summary_counts_and_means(self) -> None:
        summary = summarize(self._rows())
        self.assertEqual(summary["cases"], 2)
        self.assertEqual(summary["baseline"]["passes"], 1)
        self.assertEqual(summary["ocr"]["passes"], 1)
        self.assertEqual(summary["ocr"]["ui_string_match_mean"], 0.75)
        self.assertEqual(summary["ocr"]["unsupported_claim_rate_mean"], 0.05)
        self.assertEqual(summary["ocr"]["forbidden_claim_total"], 0)

    def test_evaluate_flags_guard_regressions(self) -> None:
        gate = evaluate(self._rows())
        self.assertEqual(gate["small_text_regressions"], ["m004-small_text-13"])
        self.assertEqual(gate["baseline_passes"], 1)
        self.assertEqual(gate["ocr_passes"], 1)
        self.assertEqual(gate["dialog14_baseline_pass"], False)
        self.assertEqual(gate["dialog14_ocr_pass"], True)


if __name__ == "__main__":
    unittest.main()
