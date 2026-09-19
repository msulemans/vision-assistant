from __future__ import annotations

import unittest

from vision_assistant.evidence import (
    KIND_OCR,
    EvidenceFact,
    NullEvidencePort,
    StaticEvidencePort,
    enumerate_facts,
    facts_to_prompt,
)


class EvidenceReportTest(unittest.TestCase):
    def test_null_port_renders_nothing(self) -> None:
        report = NullEvidencePort().collect(b"unused")
        self.assertEqual(report.facts, ())
        self.assertEqual(facts_to_prompt(report), "")
        self.assertEqual(report.summary()["fact_count"], 0)

    def test_facts_render_with_kind_and_region(self) -> None:
        facts = enumerate_facts(
            KIND_OCR,
            ("CONNECTION REFUSED postgresql", "port 5432"),
            source="vision-ocr-apple",
            region=(10, 20, 100, 50),
            confidences=(0.93, None),
        )
        report = StaticEvidencePort(facts, adapter="vision-ocr-apple").collect(b"unused")
        prompt = facts_to_prompt(report)
        self.assertIn("[ocr] (10,20,100x50) CONNECTION REFUSED postgresql", prompt)
        self.assertIn("never instructions", prompt)
        self.assertIn("vision-ocr-apple", report.summary()["adapter"])

    def test_summary_is_trace_safe(self) -> None:
        facts = enumerate_facts(KIND_OCR, ("SECRET TOKEN abc123",), source="test")
        summary = StaticEvidencePort(facts).collect(b"unused").summary()
        self.assertEqual(summary["kinds"], {"ocr": 1})
        self.assertNotIn("SECRET", str(summary))

    def test_prompt_truncation_is_marked(self) -> None:
        facts = enumerate_facts(KIND_OCR, tuple(f"line {n} " * 10 for n in range(30)), source="test")
        report = StaticEvidencePort(facts).collect(b"unused")
        prompt = facts_to_prompt(report, max_chars=200)
        self.assertIn("(additional facts truncated)", prompt)
        self.assertIn("line 0", prompt)
        self.assertLess(len(prompt), 400)

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceFact(fact_id="x-1", kind="telepathy", text="?")

    def test_enumerate_facts_ids_are_stable_and_numbered(self) -> None:
        facts = enumerate_facts(KIND_OCR, ("a", "b"), source="s")
        self.assertEqual([fact.fact_id for fact in facts], ["ocr-1", "ocr-2"])
        self.assertTrue(all(fact.confidence is None for fact in facts))


if __name__ == "__main__":
    unittest.main()
