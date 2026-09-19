from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vision_assistant import evaluation_cli
from vision_assistant.evaluation import (
    COMPARISONS,
    DEFAULT_SITE_DATA,
    FAILURE_CATALOG,
    FAILURE_COMPONENTS,
    REPRODUCTION_COMMANDS,
    TEACH_BACK_TASKS,
    ascii_waterfall,
    generate_site_data,
    latency_waterfall,
    load_trace,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "learning" / "data" / "canonical-turn.jsonl"
GATE_ITEMS = {
    "trace a visual turn",
    "explain image encoding versus text generation",
    "diagnose one hallucination",
    "add a frozen fixture",
    "explain why the model cannot directly own an action",
}


def write_trace(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    return path


class WaterfallTest(unittest.TestCase):
    def test_canonical_trace_loads_and_waterfalls(self) -> None:
        trace = load_trace(CANONICAL)
        waterfall = latency_waterfall(trace)
        self.assertGreater(waterfall["total_ms"], 0)
        self.assertEqual([stage["name"] for stage in waterfall["stages"]], ["before-model", "model", "record"])
        model = waterfall["model"]
        self.assertIsNotNone(model["first_token_ms"])
        self.assertIsNotNone(model["complete_ms"])
        self.assertGreaterEqual(model["complete_ms"], model["first_token_ms"])

    def test_waterfall_math_on_hand_built_trace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_trace(
                Path(raw) / "tiny.jsonl",
                [
                    {"trace_id": "t1", "type": "preview", "ts_ms": 1000.0, "payload": {}},
                    {"trace_id": "t1", "type": "model_started", "ts_ms": 1100.0, "payload": {}},
                    {"trace_id": "t1", "type": "answer", "ts_ms": 1300.0, "payload": {}},
                    {
                        "trace_id": "t1",
                        "type": "done",
                        "ts_ms": 1310.0,
                        "payload": {"first_token_ms": 80.0, "complete_ms": 200.0, "total_ms": 310.0},
                    },
                ],
            )
            waterfall = latency_waterfall(load_trace(path))
            self.assertEqual(waterfall["total_ms"], 310.0)
            stages = {stage["name"]: stage for stage in waterfall["stages"]}
            self.assertEqual(stages["before-model"]["duration_ms"], 100.0)
            self.assertEqual(stages["model"]["duration_ms"], 200.0)
            self.assertEqual(stages["record"]["duration_ms"], 10.0)
            self.assertAlmostEqual(stages["model"]["share"], 200.0 / 310.0, places=3)
            self.assertEqual(waterfall["model"]["first_token_ms"], 80.0)

    def test_missing_events_raise(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_trace(
                Path(raw) / "short.jsonl",
                [{"trace_id": "t1", "type": "preview", "ts_ms": 1.0, "payload": {}}],
            )
            with self.assertRaises(ValueError):
                latency_waterfall(load_trace(path))

    def test_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.jsonl"
            path.write_text("{not json\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_trace(path)

    def test_ascii_rendering_mentions_model_detail(self) -> None:
        text = ascii_waterfall(latency_waterfall(load_trace(CANONICAL)))
        self.assertIn("model detail", text)
        self.assertIn("first token", text)


class CatalogTest(unittest.TestCase):
    def test_failure_catalog_is_honest_and_linked(self) -> None:
        self.assertGreaterEqual(len(FAILURE_CATALOG), 10)
        ids = [entry["id"] for entry in FAILURE_CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in FAILURE_CATALOG:
            with self.subTest(entry=entry["id"]):
                self.assertIn(entry["status"], {"fixed", "known-limitation"})
                self.assertIn(entry["component"], FAILURE_COMPONENTS)
                self.assertTrue(entry["cause"])
                self.assertTrue(entry["fix"])
                evidence = ROOT / "docs" / "evidence" / entry["evidence"]
                self.assertTrue(evidence.is_file(), f"missing evidence for {entry['id']}")

    def test_comparison_contains_the_selected_configuration(self) -> None:
        selected = [entry for entry in COMPARISONS if entry["status"] == "selected"]
        self.assertEqual(len(selected), 1)
        self.assertIn("23/24", selected[0]["held_out"])
        self.assertEqual(selected[0]["rss_gib"], 3.792)

    def test_commands_cover_the_milestones(self) -> None:
        milestones = {entry["milestone"] for entry in REPRODUCTION_COMMANDS}
        for expected in ("M002", "M004", "M010", "M012", "M014", "M015"):
            self.assertIn(expected, milestones)
        for entry in REPRODUCTION_COMMANDS:
            self.assertIn(entry["speed"], {"seconds", "minutes"})
            self.assertTrue(entry["command"])

    def test_teach_back_covers_the_gate_exactly(self) -> None:
        self.assertEqual(len(TEACH_BACK_TASKS), 5)
        self.assertEqual({task["gate_item"] for task in TEACH_BACK_TASKS}, GATE_ITEMS)
        for task in TEACH_BACK_TASKS:
            self.assertGreaterEqual(len(task["checklist"]), 4)
            self.assertTrue(task["where"])
            self.assertTrue(task["hint"])


class SiteDataTest(unittest.TestCase):
    def test_generate_is_deterministic_and_matches_the_committed_golden(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = generate_site_data(Path(raw) / "eval_data.js")
            self.assertEqual(out.read_bytes(), DEFAULT_SITE_DATA.read_bytes())

    def test_payload_shape(self) -> None:
        text = DEFAULT_SITE_DATA.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("// Generated by"))
        body = text[text.index("{"): text.rindex("}") + 1]
        payload = json.loads(body)
        self.assertEqual(
            sorted(payload),
            ["commands", "comparisons", "failures", "generated_from", "teach_back", "waterfall"],
        )
        self.assertEqual(payload["generated_from"], "learning/data/canonical-turn.jsonl")
        self.assertEqual(len(payload["teach_back"]), 5)


class CliTest(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = evaluation_cli.main(list(argv))
        return code, buffer.getvalue()

    def test_trace_json(self) -> None:
        code, output = self.run_cli("trace", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertIn("stages", payload)

    def test_failures_and_commands_and_teachback(self) -> None:
        for argv in (("failures",), ("commands",), ("teachback",)):
            code, output = self.run_cli(*argv)
            self.assertEqual(code, 0, argv)
            self.assertGreater(len(output), 100)

    def test_generate_reports_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            code, output = self.run_cli("generate", "--out", str(Path(raw) / "eval_data.js"))
            self.assertEqual(code, 0)
            payload = json.loads(output)
            self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
