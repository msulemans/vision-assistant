"""M006 one-shot assistant CLI: preview one screenshot, ask one question.

    python -m vision_assistant.assistant_cli shot.png --preview-only
    python -m vision_assistant.assistant_cli shot.png

The default path uses the pinned Qwen3.5-4B configuration selected in M005
(thinking off, context pinned at 4096). The private artifact is deleted before
the command exits unless --retain is given.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIN_DIR = REPO_ROOT / "models" / "qwen3.5-4b"


def _trace_id() -> str:
    return f"m006-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot local Vision Assistant (M006)")
    parser.add_argument("image", type=Path, help="a PNG screenshot you explicitly selected")
    parser.add_argument("--question", default=None, help="one question about the screenshot")
    parser.add_argument("--pin-dir", type=Path, default=DEFAULT_PIN_DIR, help="pinned model directory")
    parser.add_argument("--ctx-size", type=int, default=4096, help="bounded context (M005 selection)")
    parser.add_argument("--think", action="store_true", help="keep the model's thinking mode (Qwen only)")
    parser.add_argument("--preview-only", action="store_true", help="normalize + report; no model run")
    parser.add_argument("--retain", action="store_true", help="keep the private artifact (testing only)")
    parser.add_argument("--trace-dir", type=Path, default=REPO_ROOT / "runs" / "m006")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=REPO_ROOT / "runs" / "m006-artifacts",
        help="private artifact root (tests override this)",
    )
    args = parser.parse_args(argv)

    from .assistant import (
        DEFAULT_QUESTION,
        answer_frame,
        preview_image,
        record_interruption,
    )

    trace_id = _trace_id()
    try:
        preview, frame, store, _ingestor = preview_image(
            args.image,
            artifacts_root=args.artifacts_root,
            trace_id=trace_id,
            retain=args.retain,
        )
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "stage": "preview"}))
        return 130
    except Exception as exc:  # noqa: BLE001 - the CLI reports typed capture failures
        print(json.dumps({"status": "failed", "stage": "preview", "reason": str(exc)}))
        return 1

    print(
        f"image: {preview.width}x{preview.height}, {preview.byte_size} bytes, "
        f"sha256 {preview.sha256[:12]}..., ingest {preview.ingest_ms:.1f} ms"
    )
    if args.preview_only:
        store.release(frame)
        released = frame.image_path is None or not frame.image_path.exists()
        print(json.dumps({"status": "previewed", "released": released}))
        return 0

    pin_path = args.pin_dir / "pin.json"
    if not pin_path.exists():
        print(json.dumps({"status": "failed", "stage": "model", "reason": f"no pin at {pin_path}"}))
        store.release(frame)
        return 1
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    model = next(f for f in pin["files"] if f["role"] == "model")
    mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")

    from .runtime_llamaserver import LlamaServerAdapter

    adapter = LlamaServerAdapter(
        args.pin_dir / model["name"],
        args.pin_dir / mmproj["name"],
        ctx_size=args.ctx_size,
        jinja=not args.think,
        chat_template_kwargs={"enable_thinking": False} if not args.think else None,
        log_path=REPO_ROOT / "runs" / "assistant-server.log",
    )
    trace_path = args.trace_dir / f"{trace_id}.jsonl"
    stage = "model_start"
    try:
        adapter.start()
        stage = "answer"
        result = answer_frame(
            frame,
            args.question or DEFAULT_QUESTION,
            adapter=adapter,
            trace_dir=args.trace_dir,
            store=store,
        )
    except KeyboardInterrupt:
        store.release(frame)
        if stage != "answer":
            # The answer flow records its own `cancelled` trace; earlier
            # stages have none yet.
            record_interruption(args.trace_dir, trace_id, stage=stage)
        print(json.dumps({"status": "cancelled", "stage": stage, "trace": str(trace_path)}))
        return 130
    except Exception as exc:  # noqa: BLE001 - report cleanly; the server log has details
        store.release(frame)
        print(
            json.dumps(
                {"status": "failed", "stage": stage, "reason": f"{type(exc).__name__}: {exc}"}
            )
        )
        return 1
    finally:
        adapter.stop()

    answer = result["answer"]
    for label in ("visible", "inferred", "unknown"):
        print(f"[{label}]")
        for line in answer[label] or ["(none)"]:
            print(f"  {line}")
    timing = result["timing_ms"]
    first = f"{timing['first_token']:.0f} ms" if timing["first_token"] is not None else "n/a"
    complete = f"{timing['complete']:.0f} ms" if timing["complete"] is not None else "n/a"
    print(f"\nfirst token {first} - complete {complete} - total {timing['total']:.0f} ms")
    print(f"trace: {result['trace_path']}")
    print(f"artifact released: {result['released']}")
    print(json.dumps({"status": "answered", "trace_id": result["trace_id"], "released": result["released"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
