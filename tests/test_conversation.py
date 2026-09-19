from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from vision_assistant.assistant import preview_image
from vision_assistant.capture import PNG_SIGNATURE, _png_chunk
from vision_assistant.conversation import (
    ConversationSession,
    SessionClosed,
    TurnLimitReached,
)
from vision_assistant.ports import LabelledAnswer
from vision_assistant.pixels import decode_png


def _make_png(width: int = 24, height: int = 16) -> bytes:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


class _FakeAdapter:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.pngs: list[bytes] = []

    def predict_image(self, png_bytes: bytes, question: str):
        self.prompts.append(question)
        self.pngs.append(png_bytes)
        answer = LabelledAnswer(
            visible=("VISIBLE FACT",), inferred=(), unknown=("UNKNOWN PART",)
        )
        return answer, {"first_token_ms": 10.0, "complete_ms": 20.0}


def _read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _open_session(root: Path, *, trace_id: str = "va-session", **kwargs):
    root.mkdir(parents=True, exist_ok=True)
    (root / "shot.png").write_bytes(_make_png())
    _preview, frame, store, _ = preview_image(
        root / "shot.png", artifacts_root=root / "artifacts", trace_id=trace_id
    )
    adapter = _FakeAdapter()
    session = ConversationSession(frame, store, adapter, trace_dir=root / "traces", **kwargs)
    return session, adapter, frame


class ConversationSessionTest(unittest.TestCase):
    def test_follow_up_carries_history_into_the_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session, adapter, _ = _open_session(Path(tmp))
            session.ask("what is shown?")
            session.ask("and what is unknown?")
            self.assertEqual(adapter.prompts[0], "Current question: what is shown?")
            self.assertIn("Transcript so far", adapter.prompts[1])
            self.assertIn("VISIBLE FACT", adapter.prompts[1])
            self.assertIn("what is shown?", adapter.prompts[1])
            self.assertIn("Current question: and what is unknown?", adapter.prompts[1])

    def test_transcript_budget_drops_oldest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session, adapter, _ = _open_session(Path(tmp), max_context_chars=60)
            session.ask("first question?")
            session.ask("second question?")
            session.ask("third question?")
            latest = adapter.prompts[2]
            self.assertIn("(earlier turns omitted)", latest)
            self.assertNotIn("first question?", latest)
            self.assertIn("second question?", latest)

    def test_turn_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session, _, _ = _open_session(Path(tmp), max_turns=1)
            session.ask("one?")
            with self.assertRaises(TurnLimitReached):
                session.ask("two?")

    def test_reset_releases_the_artifact_and_closes_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session, _, frame = _open_session(Path(tmp))
            self.assertTrue(Path(frame.image_path).exists())
            self.assertTrue(session.reset())
            self.assertFalse(Path(frame.image_path).exists())
            with self.assertRaises(SessionClosed):
                session.ask("still there?")
            self.assertFalse(session.reset())

    def test_new_capture_starts_with_empty_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_a, _adapter_a, frame_a = _open_session(root / "a", trace_id="va-a")
            (root / "b").mkdir(parents=True, exist_ok=True)
            (root / "b" / "shot.png").write_bytes(_make_png(32, 20))
            _preview, frame_b, store_b, _ = preview_image(
                root / "b" / "shot.png",
                artifacts_root=root / "b" / "artifacts",
                trace_id="va-b",
            )
            adapter_b = _FakeAdapter()
            session_b = ConversationSession(
                frame_b, store_b, adapter_b, trace_dir=root / "b" / "traces"
            )
            session_a.ask("question for a?")
            session_b.ask("question for b?")
            self.assertTrue(session_a.matches(frame_a))
            self.assertFalse(session_a.matches(frame_b))
            self.assertEqual(adapter_b.prompts[0], "Current question: question for b?")

    def test_large_capture_is_downscaled_for_the_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session, adapter, _ = _open_session(Path(tmp), model_image_max_pixels=100)
            session.ask("scaled?")
            sent = decode_png(adapter.pngs[0])
            self.assertEqual((sent.width, sent.height), (12, 8))

    def test_small_capture_reaches_the_model_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session, adapter, frame = _open_session(Path(tmp))
            expected = Path(frame.image_path).read_bytes()
            session.ask("unchanged?")
            self.assertEqual(adapter.pngs[0], expected)

    def test_stale_warning_after_idle_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now = {"t": 0.0}
            session, _, _ = _open_session(
                Path(tmp), clock=lambda: now["t"], stale_after_s=100.0
            )
            now["t"] = 50.0
            self.assertFalse(session.ask("fresh?")["stale_warning"])
            now["t"] = 1000.0
            result = session.ask("stale?")
            self.assertTrue(result["stale_warning"])
            self.assertEqual(result["turn"], 2)

    def test_session_trace_records_turns_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session, _, _ = _open_session(root, trace_id="va-trace")
            session.ask("first?")
            session.ask("second?")
            session.reset()
            records = _read_trace(root / "traces" / "va-trace.jsonl")
            self.assertEqual(records[0]["type"], "meta")
            types = [record["type"] for record in records[1:]]
            self.assertEqual(
                types,
                [
                    "session_started",
                    "model_started",
                    "answer",
                    "done",
                    "model_started",
                    "answer",
                    "done",
                    "session_reset",
                ],
            )
            self.assertEqual(records[2]["payload"]["turn"], 1)
            self.assertEqual(records[-1]["payload"]["released"], True)


if __name__ == "__main__":
    unittest.main()
