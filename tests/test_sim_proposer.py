from __future__ import annotations

import json
import unittest
from pathlib import Path

from vision_assistant.ports import LabelledAnswer
from vision_assistant.runtime_llamaserver import LlamaServerAdapter
from vision_assistant.sim_cli import PROPOSE_SCHEMA, model_proposer


class _RecordingAdapter:
    def __init__(self, *, fail_with_schema: bool = False) -> None:
        self.calls: list[dict] = []
        self._fail_with_schema = fail_with_schema

    def predict_image(self, png_bytes, question, *, json_schema=None):
        self.calls.append({"question": question, "json_schema": json_schema})
        if json_schema is not None and self._fail_with_schema:
            raise RuntimeError("schema rejected")
        answer = LabelledAnswer(visible=(json.dumps([{"kind": "observe"}]),), inferred=(), unknown=())
        return answer, {"first_token_ms": 1.0, "complete_ms": 2.0}


class ProposerTest(unittest.TestCase):
    def test_schema_constrained_call_is_tried_first(self) -> None:
        adapter = _RecordingAdapter()
        payloads = model_proposer(adapter)(b"x", "turn on sync", 0)
        self.assertEqual(payloads, [{"kind": "observe"}])
        self.assertEqual(adapter.calls[0]["json_schema"], PROPOSE_SCHEMA)
        self.assertEqual(len(adapter.calls), 1)

    def test_falls_back_to_plain_prompt_when_schema_fails(self) -> None:
        adapter = _RecordingAdapter(fail_with_schema=True)
        payloads = model_proposer(adapter)(b"x", "turn on sync", 0)
        self.assertEqual(payloads, [{"kind": "observe"}])
        self.assertIsNotNone(adapter.calls[0]["json_schema"])
        self.assertIsNone(adapter.calls[1]["json_schema"])

    def test_raw_answers_are_recorded(self) -> None:
        record: list[str] = []
        adapter = _RecordingAdapter()
        model_proposer(adapter, record=record)(b"x", "task", 0)
        self.assertEqual(len(record), 1)
        self.assertIn('"kind"', record[0])

    def test_repair_attempt_when_unparseable(self) -> None:
        class _BadThenGood:
            def __init__(self) -> None:
                self.calls = 0

            def predict_image(self, png_bytes, question, *, json_schema=None):
                self.calls += 1
                text = "sorry, prose only" if self.calls == 1 else '[{"kind": "cancel"}]'
                return LabelledAnswer(visible=(text,), inferred=(), unknown=()), {}

        adapter = _BadThenGood()
        payloads = model_proposer(adapter)(b"x", "task", 0)
        self.assertEqual(payloads, [{"kind": "cancel"}])
        self.assertEqual(adapter.calls, 2)

    def test_propose_schema_is_json_serializable(self) -> None:
        json.dumps(PROPOSE_SCHEMA)


class SchemaPayloadTest(unittest.TestCase):
    def _adapter(self, captured: dict) -> LlamaServerAdapter:
        def fake_transport(url, payload, timeout_s):
            captured.update(payload)
            return iter(
                [
                    'data: {"choices": [{"delta": {"content": "[visible] OK"}}]}',
                    "data: [DONE]",
                ]
            )

        return LlamaServerAdapter(Path("m.gguf"), Path("p.gguf"), transport=fake_transport)

    def test_predict_image_sends_response_format_with_schema(self) -> None:
        captured: dict = {}
        adapter = self._adapter(captured)
        adapter.predict_image(b"png", "question", json_schema={"type": "array"})
        self.assertEqual(
            captured["response_format"],
            {"type": "json_object", "schema": {"type": "array"}},
        )

    def test_predict_image_omits_response_format_by_default(self) -> None:
        captured: dict = {}
        adapter = self._adapter(captured)
        adapter.predict_image(b"png", "question")
        self.assertNotIn("response_format", captured)


if __name__ == "__main__":
    unittest.main()
