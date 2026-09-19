from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class PreviewInterruptTest(unittest.TestCase):
    def test_interrupt_during_preview_purges_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {"n": 0}

            def clock() -> float:
                calls["n"] += 1
                if calls["n"] >= 2:  # interrupt after the artifact was written
                    raise KeyboardInterrupt
                return 0.0

            with self.assertRaises(KeyboardInterrupt):
                preview_image(
                    _write_png(root),
                    artifacts_root=root / "artifacts",
                    trace_id="m006-stop",
                    clock=clock,
                )
            self.assertFalse((root / "artifacts" / "m006-stop").exists())


class _FakeStartupAdapter:
    instances: list = []

    def __init__(self, *args, **kwargs) -> None:
        self.stopped = False
        _FakeStartupAdapter.instances.append(self)

    def start(self) -> None:
        raise KeyboardInterrupt

    def stop(self) -> None:
        self.stopped = True


class CliStartupInterruptTest(unittest.TestCase):
    def test_startup_interrupt_is_clean(self) -> None:
        from vision_assistant import assistant_cli

        _FakeStartupAdapter.instances = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pin_dir = root / "pin"
            pin_dir.mkdir()
            (pin_dir / "pin.json").write_text(
                json.dumps(
                    {
                        "files": [
                            {"role": "model", "name": "model.gguf"},
                            {"role": "mmproj", "name": "mmproj.gguf"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with mock.patch(
                "vision_assistant.runtime_llamaserver.LlamaServerAdapter",
                _FakeStartupAdapter,
            ), contextlib.redirect_stdout(stdout):
                code = assistant_cli.main(
                    [
                        str(_write_png(root)),
                        "--pin-dir",
                        str(pin_dir),
                        "--artifacts-root",
                        str(root / "artifacts"),
                        "--trace-dir",
                        str(root / "traces"),
                    ]
                )
            self.assertEqual(code, 130)
            payload = json.loads(stdout.getvalue().strip().splitlines()[-1])
            self.assertEqual(payload["status"], "cancelled")
            self.assertEqual(payload["stage"], "model_start")
            self.assertTrue(_FakeStartupAdapter.instances[0].stopped)
            self.assertEqual(list((root / "artifacts").iterdir()), [])
            traces = list((root / "traces").glob("*.jsonl"))
            self.assertEqual(len(traces), 1)
            records = _read_trace(str(traces[0]))
            self.assertEqual(records[1]["type"], "cancelled")
            self.assertEqual(records[1]["payload"]["stage"], "model_start")


if __name__ == "__main__":
    unittest.main()
