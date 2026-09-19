"""M011 runner: the pinned model proposes, the loop acts on a toy app.

One model call per step proposes a single intent (JSON array). The loop
validates it, applies the M010 policy, auto-approves inside the simulation,
fake-executes against the practice app, and verifies against state
predicates. Nothing touches the host — execution is a Python state change.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from .action_loop import SimulatedActionLoop
from .intents import ActionPolicy
from .practice_app import FROZEN_TASKS, PracticeApp
from .propose_cli import extract_json_array

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIN_DIR = REPO_ROOT / "models" / "qwen3.5-4b"

PROPOSE_PROMPT = (
    "You control a simulated practice app. TASK: {instruction}\n"
    "Element ids: app:sync-toggle, app:notify-toggle, app:search, "
    "app:save, app:cancel.\n"
    "Propose exactly ONE next action as a JSON array containing one object. "
    "Allowed kinds: observe, click_element (element_id), type_text (text, "
    "field or element_id), press_key (key), scroll (direction, steps), "
    "cancel, finish (summary).\n"
    'Reply with ONLY the JSON array. Example: [{{"kind": "click_element", '
    '"element_id": "app:sync-toggle"}}]'
)
REPAIR_PROMPT = (
    "Your previous reply was not valid JSON. TASK: {instruction}\n"
    "Reply with ONLY a JSON array containing one intent object. Example: "
    '[{{"kind": "click_element", "element_id": "app:sync-toggle"}}]'
)


def model_proposer(adapter, *, repair: bool = True):
    """A proposer backed by the pinned model, with one JSON repair attempt."""

    def propose(png_bytes: bytes, instruction: str, revision: int) -> list:
        answer, _timings = adapter.predict_image(
            png_bytes, PROPOSE_PROMPT.format(instruction=instruction)
        )
        text = " ".join((*answer.visible, *answer.inferred, *answer.unknown))
        payloads = extract_json_array(text)
        if payloads is None and repair:
            answer2, _timings2 = adapter.predict_image(
                png_bytes, REPAIR_PROMPT.format(instruction=instruction)
            )
            text2 = " ".join((*answer2.visible, *answer2.inferred, *answer2.unknown))
            payloads = extract_json_array(text2)
        return payloads or []

    return propose


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M011 simulated action loop (toy app only)")
    parser.add_argument("--pin-dir", type=Path, default=DEFAULT_PIN_DIR)
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument(
        "--tasks", default=None, help="comma-separated task ids (default: all frozen tasks)"
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    from .runtime_llamaserver import LlamaServerAdapter

    wanted = (
        [item.strip() for item in args.tasks.split(",")] if args.tasks else None
    )
    tasks = [task for task in FROZEN_TASKS if wanted is None or task.task_id in wanted]
    if wanted is not None:
        missing = set(wanted) - {task.task_id for task in tasks}
        if missing:
            print(json.dumps({"status": "failed", "reason": f"unknown tasks {sorted(missing)}"}))
            return 1

    pin_path = args.pin_dir / "pin.json"
    if not pin_path.exists():
        print(json.dumps({"status": "failed", "reason": f"no pin at {pin_path}"}))
        return 1
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    model = next(f for f in pin["files"] if f["role"] == "model")
    mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")

    adapter = LlamaServerAdapter(
        args.pin_dir / model["name"],
        args.pin_dir / mmproj["name"],
        ctx_size=args.ctx_size,
        jinja=True,
        chat_template_kwargs={"enable_thinking": False},
        log_path=REPO_ROOT / "runs" / "m011-server.log",
    )
    run_id = f"m011-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    out_path = args.out or REPO_ROOT / "runs" / "m011" / f"sim-{run_id}.json"
    trace_dir = REPO_ROOT / "runs" / "m011"

    app = PracticeApp()
    results: list[dict] = []
    started = time.monotonic()
    try:
        adapter.start()
        for task in tasks:
            print(f"\n=== {task.task_id}: {task.instruction}")
            loop = SimulatedActionLoop(
                app,
                task,
                model_proposer(adapter),
                policy=ActionPolicy(),
                trace_dir=trace_dir,
                trace_id=f"{run_id}-{task.task_id}",
            )
            result = loop.run()
            results.append(result)
            for index, event in enumerate(result["events"]):
                detail = {k: v for k, v in event.items() if k != "type"}
                print(f"  {index:2d} {event['type']:>9s} {json.dumps(detail, sort_keys=True)}")
            print(f"  -> {result['status'].upper()} ({result['reason']}, {result['steps']} steps)")
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "run_id": run_id}))
        return 130
    finally:
        adapter.stop()
    total_ms = (time.monotonic() - started) * 1000.0

    summary = {
        "run_id": run_id,
        "tasks": {
            result["task_id"]: {
                "status": result["status"],
                "reason": result["reason"],
                "steps": result["steps"],
                "host_input_events": result["host_input_events"],
            }
            for result in results
        },
        "all_done": all(result["status"] == "done" for result in results),
        "total_ms": round(total_ms, 1),
    }
    payload = {**summary, "results": results}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nsummary: {json.dumps(summary, sort_keys=True)}")
    print(f"result: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
