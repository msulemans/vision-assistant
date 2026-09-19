"""M008 measurement: frozen reference/correction tasks over bounded sessions.

Each task runs in a fresh ConversationSession bound to one synthetic capture:
the frozen corpus question as a seed turn, then the task's follow-up, scored
with the deterministic checks from `conversation_eval`. Records per-task
pass, prompt sizes, timings, and artifact-release flags. Synthetic fixtures
only; never user screenshots.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIN_DIR = REPO_ROOT / "models" / "qwen3.5-4b"


class _RecordingAdapter:
    def __init__(self, inner: object) -> None:
        self.inner = inner
        self.prompts: list[str] = []

    def predict_image(self, png_bytes: bytes, question: str):
        self.prompts.append(question)
        return self.inner.predict_image(png_bytes, question)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M008 reference/correction measurement")
    parser.add_argument("--pin-dir", type=Path, default=DEFAULT_PIN_DIR)
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--evidence-ocr", action="store_true", help="include M007 OCR facts")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from .assistant import preview_image
    from .conversation import MAX_CONTEXT_CHARS, ConversationSession
    from .conversation_eval import TASKS, check_passes
    from .corpus import build_corpus
    from .runtime_llamaserver import LlamaServerAdapter

    print("building the frozen corpus in memory...")
    cases = {case.case_id: case for case in build_corpus()}
    missing = [task.case_id for task in TASKS if task.case_id not in cases]
    if missing:
        raise SystemExit(f"unknown case ids: {missing}")

    pin_path = args.pin_dir / "pin.json"
    if not pin_path.exists():
        print(json.dumps({"status": "failed", "reason": f"no pin at {pin_path}"}))
        return 1
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    model = next(f for f in pin["files"] if f["role"] == "model")
    mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")

    evidence_port = None
    if args.evidence_ocr:
        from .ocr_vision import VisionOcrAdapter

        evidence_port = VisionOcrAdapter()

    adapter = LlamaServerAdapter(
        args.pin_dir / model["name"],
        args.pin_dir / mmproj["name"],
        ctx_size=args.ctx_size,
        jinja=True,
        chat_template_kwargs={"enable_thinking": False},
        log_path=REPO_ROOT / "runs" / "m008-server.log",
    )
    run_id = f"m008-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    out_path = args.out or REPO_ROOT / "runs" / "m008" / f"results-{run_id}.json"
    artifacts_root = REPO_ROOT / "runs" / "m008-artifacts"
    cases_dir = REPO_ROOT / "runs" / "m008" / "cases"

    rows: list[dict] = []
    try:
        adapter.start()
        started = time.monotonic()
        for task in TASKS:
            case = cases[task.case_id]
            cases_dir.mkdir(parents=True, exist_ok=True)
            source = cases_dir / f"{case.case_id}.png"
            source.write_bytes(case.fixture.png_bytes)
            trace_id = f"{run_id}-{task.task_id}"
            _preview, frame, store, _ = preview_image(
                source, artifacts_root=artifacts_root, trace_id=trace_id
            )
            recorder = _RecordingAdapter(adapter)
            session = ConversationSession(
                frame,
                store,
                recorder,
                evidence_port=evidence_port,
                trace_dir=REPO_ROOT / "runs" / "m008",
            )
            seed = session.ask(case.question)
            follow = session.ask(task.follow_up)
            lines = (
                *follow["answer"]["visible"],
                *follow["answer"]["inferred"],
                *follow["answer"]["unknown"],
            )
            passed, reason = check_passes(task.check, tuple(lines))
            released = session.reset()
            rows.append(
                {
                    "task_id": task.task_id,
                    "kind": task.kind,
                    "case_id": task.case_id,
                    "pass": passed,
                    "reason": reason,
                    "released": released,
                    "prompt_chars": [len(prompt) for prompt in recorder.prompts],
                    "seed_ms": seed["timing_ms"]["complete"],
                    "follow_ms": follow["timing_ms"]["complete"],
                    "answers": {"seed": seed["answer"], "follow": follow["answer"]},
                }
            )
            print(
                f"{task.task_id:22s} {'PASS' if passed else 'FAIL'}"
                f"  ({reason})  follow={follow['timing_ms']['complete']:.0f} ms"
                f"  released={released}"
            )
        total_ms = (time.monotonic() - started) * 1000.0
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "run_id": run_id}))
        return 130
    finally:
        adapter.stop()

    max_prompt = max((max(row["prompt_chars"]) for row in rows), default=0)
    summary = {
        "tasks": len(rows),
        "reference_passes": sum(1 for row in rows if row["kind"] == "reference" and row["pass"]),
        "reference_total": sum(1 for row in rows if row["kind"] == "reference"),
        "correction_passes": sum(1 for row in rows if row["kind"] == "correction" and row["pass"]),
        "correction_total": sum(1 for row in rows if row["kind"] == "correction"),
        "all_released": all(row["released"] for row in rows),
        "max_prompt_chars": max_prompt,
        "prompt_bounded": max_prompt <= MAX_CONTEXT_CHARS + 2500,
    }
    result = {
        "run_id": run_id,
        "config": {
            "candidate": "qwen3.5-4b",
            "ctx_size": args.ctx_size,
            "evidence": "vision-ocr-apple, zoom x2" if args.evidence_ocr else None,
        },
        "rows": rows,
        "summary": summary,
        "total_ms": round(total_ms, 1),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nsummary: {json.dumps(summary, sort_keys=True)}")
    print(f"result: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
