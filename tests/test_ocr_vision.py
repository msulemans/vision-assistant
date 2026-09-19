from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vision_assistant.ocr_vision import OcrUnavailable, VisionOcrAdapter


def _fake_helper(tool_dir: Path, body: str) -> None:
    tool_dir.mkdir(parents=True, exist_ok=True)
    helper = tool_dir / "vision_ocr"
    helper.write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    helper.chmod(0o700)


class VisionOcrAdapterTest(unittest.TestCase):
    def test_collect_parses_facts_and_cleans_its_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fake_helper(
                root / "tools",
                "import json, sys\n"
                "print(json.dumps(["
                "{'text': 'CONNECTION REFUSED', 'x': 10, 'y': 20, 'w': 100, 'h': 12, "
                "'confidence': 0.91},"
                "{'text': '   ', 'x': 0, 'y': 0, 'w': 5, 'h': 5, 'confidence': 0.5},"
                "] + [None]))\n",
            )
            adapter = VisionOcrAdapter(
                tool_dir=root / "tools",
                helper_source=root / "missing.swift",
                workdir=root / "work",
            )
            report = adapter.collect(b"unused-bytes")
            self.assertEqual(len(report.facts), 1)  # blank line and junk are skipped
            fact = report.facts[0]
            self.assertEqual(fact.fact_id, "ocr-1")
            self.assertEqual(fact.region, (10, 20, 100, 12))
            self.assertEqual(fact.confidence, 0.91)
            summary = report.summary()
            self.assertEqual(summary["kinds"], {"ocr": 1})
            self.assertNotIn("CONNECTION", str(summary))
            self.assertEqual(list((root / "work").iterdir()), [])  # temp file deleted

    def test_missing_source_raises_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = VisionOcrAdapter(
                tool_dir=root / "tools",
                helper_source=root / "missing.swift",
            )
            with self.assertRaises(OcrUnavailable):
                adapter.collect(b"unused")

    def test_helper_failure_raises_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fake_helper(
                root / "tools",
                "import sys\nsys.stderr.write('boom'); sys.exit(1)\n",
            )
            adapter = VisionOcrAdapter(
                tool_dir=root / "tools",
                helper_source=root / "missing.swift",
                workdir=root / "work",
            )
            with self.assertRaises(OcrUnavailable):
                adapter.collect(b"unused")


if __name__ == "__main__":
    unittest.main()
