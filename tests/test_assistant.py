from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vision_assistant.assistant import DEFAULT_QUESTION, answer_frame, preview_image
from vision_assistant.corpus import build_corpus
from vision_assistant.ports import LabelledAnswer


class _FakeAdapter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    def predict_image(self, png_bytes: bytes, question: str):
        if self._error is not None:
            raise self._error
        answer = LabelledAnswer(
            visible=("SAVE YOUR WORK",),
            inferred=(),
            unknown=("Whether the work was saved is not visible.",),
        )
        return answer, {"first_token_ms": 12.5, "complete_ms": 34.0}


def _write_png(root: Path) -> Path:
    case = build_corpus()[0]
    path = root / "shot.png"
    path.write_bytes(case.fixture.png_bytes)
    return path


def _read_trace(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


class OneShotAssistantTest(unittest.TestCase):
    def test_answer_flow_records_trace_and_releases_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview, frame, store, _ = preview_image(
                _write_png(root), artifacts_root=root / "artifacts", trace_id="m006-test"
            )
            self.assertEqual((preview.width, preview.height), (480, 300))
            result = answer_frame(
                frame,
                DEFAULT_QUESTION,
                adapter=_FakeAdapter(),
                trace_dir=root / "traces",
                store=store,
            )
            self.assertTrue(result["released"])
            self.assertFalse((root / "artifacts" / "m006-test" / "frame.png").exists())
            self.assertEqual(result["timing_ms"]["first_token"], 12.5)
            self.assertEqual(result["answer"]["visible"], ["SAVE YOUR WORK"])

            records = _read_trace(result["trace_path"])
            self.assertEqual(records[0]["type"], "meta")
            types = [record["type"] for record in records[1:]]
            self.assertEqual(types, ["preview", "model_started", "answer", "done"])
            self.assertEqual(records[-1]["state"], "done")

    def test_failure_records_failed_state_and_releases_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _preview, frame, store, _ = preview_image(
                _write_png(root), artifacts_root=root / "artifacts", trace_id="m006-fail"
            )
            with self.assertRaises(RuntimeError):
                answer_frame(
                    frame,
                    DEFAULT_QUESTION,
                    adapter=_FakeAdapter(error=RuntimeError("server unavailable")),
                    trace_dir=root / "traces",
                    store=store,
                )
            self.assertFalse((root / "artifacts" / "m006-fail" / "frame.png").exists())
            records = _read_trace(str(root / "traces" / "m006-fail.jsonl"))
            states = [record["state"] for record in records[1:]]
            self.assertIn("failed", states)
            self.assertNotIn("done", states)

    def test_retain_keeps_the_artifact_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _preview, frame, store, _ = preview_image(
                _write_png(root), artifacts_root=root / "artifacts", trace_id="m006-retain", retain=True
            )
            result = answer_frame(
                frame,
                DEFAULT_QUESTION,
                adapter=_FakeAdapter(),
                trace_dir=root / "traces",
                store=store,
            )
            self.assertFalse(result["released"])
            self.assertTrue((root / "artifacts" / "m006-retain" / "frame.png").exists())


if __name__ == "__main__":
    unittest.main()
