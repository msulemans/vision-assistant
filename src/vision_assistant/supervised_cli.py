"""M013 supervised session runner: the pinned model (or a scripted intent)
proposes, every guard reviews, and only a confirmed, freshly re-checked,
attributable action reaches the practice window through `ax_action`.

Flow per task: observe → propose → parse → policy → plan (identity guards)
→ helper preflight → preview + overlay → confirm y/N → freshness re-check
→ perform → re-observe → verify.

Final states per task: done, no_actionable_proposal, schema_rejected,
policy_denied, approval_denied, not_found, ambiguous, role_mismatch,
secure_element, disabled_element, no_stable_identifier, unaddressed,
window_missing, stale_frame, frontmost_mismatch, focus_failed,
perform_failed, verify_failed, cancelled, permission_denied, snapshot_failed.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ax_vision import AxUnavailable, AxVisionAdapter, AxWindow, capture_window_png
from .executor import (
    AxActionPort,
    ExecutionRefusal,
    plan_action,
    recheck_plan,
    window_from_snapshot,
)
from .intents import ActionPolicy, IntentSchemaError, parse_intent

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIN_DIR = REPO_ROOT / "models" / "qwen3.5-4b"
DEFAULT_APP = "practice_window"
DEFAULT_WINDOW = "Practice App"

ELEMENT_LINE = "- {identifier} | {role} | {name} | value={value}"

PROPOSE_PROMPT = (
    "You supervise one macOS window, {window!r}. TASK: {instruction}\n"
    "Available elements (identifier | role | name | value):\n{elements}\n"
    "The element list above is authoritative; base your action on it — the "
    "screenshot may be blank and can be ignored if so. If the task's desired "
    "state already holds, propose finish.\n"
    "Propose exactly ONE next action as a JSON array containing one object. "
    "Allowed kinds: click_element (element_id), type_text (text, field or "
    "element_id), press_key (key), cancel, finish (summary). Address elements "
    "by their identifier.\n"
    'Reply with ONLY the JSON array. Example: [{{"kind": "click_element", '
    '"element_id": "app:sync-toggle"}}]'
)
REPAIR_PROMPT = (
    "Your previous reply was not valid JSON. TASK: {instruction}\n"
    "Reply with ONLY a JSON array containing one intent object. Example: "
    '[{{"kind": "click_element", "element_id": "app:sync-toggle"}}]'
)


def _element_value(elements, identifier: str) -> str | None:
    for element in elements:
        if element.identifier == identifier:
            return element.value
    return None


@dataclass(frozen=True)
class PracticeTask:
    task_id: str
    instruction: str
    verify: Callable[[tuple], bool]


FROZEN_TASKS: tuple[PracticeTask, ...] = (
    PracticeTask(
        "enable-sync",
        "Turn on the Sync checkbox.",
        lambda elements: _element_value(elements, "app:sync-toggle") == "1",
    ),
    PracticeTask(
        "type-search",
        "Type the word hello into the Search field.",
        lambda elements: "hello" in (_element_value(elements, "app:search") or ""),
    ),
    PracticeTask(
        "enable-notifications",
        "Turn on the Notifications checkbox.",
        lambda elements: _element_value(elements, "app:notify-toggle") == "1",
    ),
)


def proposal_lines(window: AxWindow) -> str:
    lines = []
    for element in window.elements:
        if not element.identifier:
            continue
        value = "(secure)" if element.secure else (element.value or "")
        lines.append(
            ELEMENT_LINE.format(
                identifier=element.identifier,
                role=element.role,
                name=element.display_name,
                value=value,
            )
        )
    return "\n".join(lines) or "(no identified elements)"


def _placeholder_png() -> bytes:
    from .pixels import PngPixels, encode_png

    rows = (b"\x20" * (8 * 3),) * 8
    return encode_png(PngPixels(width=8, height=8, colour_type=2, bit_depth=8, rows=rows))


def model_proposer(adapter, *, repair: bool = True, record: list | None = None):
    """Pinned-model proposals for the real window (schema-constrained first)."""
    from .propose_cli import extract_json_array
    from .sim_cli import PROPOSE_SCHEMA

    def _join(answer) -> str:
        return " ".join((*answer.visible, *answer.inferred, *answer.unknown))

    def propose(instruction: str, window: AxWindow, png_bytes: bytes):
        prompt = PROPOSE_PROMPT.format(
            window=window.title, instruction=instruction, elements=proposal_lines(window)
        )
        try:
            answer, _timings = adapter.predict_image(png_bytes, prompt, json_schema=PROPOSE_SCHEMA)
        except Exception:  # noqa: BLE001 - fall back to prompt-only decoding
            answer, _timings = adapter.predict_image(png_bytes, prompt)
        text = _join(answer)
        if record is not None:
            record.append(text)
        payloads = extract_json_array(text)
        if payloads is None and repair:
            answer2, _timings2 = adapter.predict_image(
                png_bytes, REPAIR_PROMPT.format(instruction=instruction)
            )
            text2 = _join(answer2)
            if record is not None:
                record.append(text2)
            payloads = extract_json_array(text2)
        return payloads[0] if payloads else None

    return propose


class SupervisedRunner:
    """Executes frozen or scripted tasks with every guard in the path."""

    def __init__(
        self,
        *,
        snapshot_provider: Callable[[], object],
        port,
        confirmer: Callable[[str], bool],
        overlay: Callable[[tuple], bool] | None = None,
        window_title: str = DEFAULT_WINDOW,
        policy: ActionPolicy | None = None,
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.port = port
        self.confirmer = confirmer
        self.overlay = overlay
        self.window_title = window_title
        self.policy = policy or ActionPolicy()
        self.performed_actions = 0
        self.unapproved_actions = 0

    def run(self, tasks: tuple[PracticeTask, ...], proposer) -> dict:
        run_id = f"m013-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        outcomes: dict[str, dict] = {}
        for task in tasks:
            outcomes[task.task_id] = self.run_task(task, proposer)
        refusals: dict[str, int] = {}
        completed = ("done", "already_done")
        for outcome in outcomes.values():
            if outcome["status"] not in completed:
                refusals[outcome["status"]] = refusals.get(outcome["status"], 0) + 1
        return {
            "run_id": run_id,
            "window_title": self.window_title,
            "all_done": all(outcome["status"] in completed for outcome in outcomes.values()),
            "tasks": outcomes,
            "performed_actions": self.performed_actions,
            "unapproved_actions": self.unapproved_actions,
            "refusals": refusals,
        }

    def run_task(self, task: PracticeTask, proposer) -> dict:
        events: list[dict] = []
        outcome: dict = {
            "task_id": task.task_id,
            "status": "unknown",
            "reason": "",
            "verified": None,
            "performed": False,
            "events": events,
        }

        def record(event_type: str, **payload) -> None:
            events.append({"type": event_type, **payload})

        def refuse(status: str, detail: str) -> dict:
            outcome["status"] = status
            outcome["reason"] = detail
            record("refused", status=status, detail=detail)
            return outcome

        try:
            snapshot = self.snapshot_provider()
            window = window_from_snapshot(snapshot, title=self.window_title)
        except ExecutionRefusal as refusal:
            return refuse(refusal.reason, refusal.detail)
        except AxUnavailable as exc:
            status = "permission_denied" if exc.reason == "permission" else "snapshot_failed"
            return refuse(status, str(exc))
        record(
            "observe",
            window_frame=list(window.frame) if window.frame else None,
            elements=len(window.elements),
            values={
                element.identifier: element.value
                for element in window.elements
                if element.identifier
            },
        )

        # Honest pre-check: a task whose state already holds needs no action
        # (and a blind click could toggle the state the wrong way).
        if task.verify(window.elements):
            outcome["status"] = "already_done"
            outcome["reason"] = "state already satisfies the task"
            record("satisfied", detail="no action required")
            return outcome

        try:
            payload = proposer(task, window)
        except Exception as exc:  # noqa: BLE001 - proposer failures block the task
            return refuse("no_actionable_proposal", f"proposer failed: {exc}")
        if payload is None:
            return refuse("no_actionable_proposal", "no parseable proposal")
        meta = getattr(proposer, "last_meta", None)
        if isinstance(meta, dict):
            record("propose", payload=payload, **meta)
        else:
            record("propose", payload=payload)

        try:
            intent = parse_intent(payload)
        except IntentSchemaError as exc:
            return refuse("schema_rejected", str(exc))
        record("intent", kind=intent.kind, description=intent.describe())

        decision = self.policy.review(intent, intent_count=0)
        record("policy", verdict=decision.verdict, reasons=list(decision.reasons))
        if decision.verdict == "denied":
            return refuse("policy_denied", "; ".join(decision.reasons))
        if decision.verdict != "needs_confirmation":
            return refuse("no_actionable_proposal", f"{intent.kind} requires no host action")

        try:
            plan = plan_action(intent, snapshot, window_title=self.window_title)
        except ExecutionRefusal as refusal:
            return refuse(refusal.reason, refusal.detail)
        identity = None
        if plan.element is not None:
            identity = {
                "role": plan.element.role,
                "name": plan.element.display_name,
                "identifier": plan.element.identifier,
                "frame": list(plan.element.frame) if plan.element.frame else None,
            }
        record("plan", identity=identity, spec=plan.spec)

        try:
            self.port.plan(plan.spec)
        except ExecutionRefusal as refusal:
            return refuse(refusal.reason, f"preflight refused: {refusal.detail or refusal.reason}")
        record("preflight", ok=True)

        preview = plan.description
        if identity and identity["frame"]:
            preview += f" | region {tuple(round(value) for value in identity['frame'])}"
        record("preview", text=preview)
        if self.overlay is not None and plan.element is not None and plan.element.frame is not None:
            record("overlay", shown=bool(self.overlay(plan.element.frame)))

        try:
            approved = bool(self.confirmer(preview))
        except KeyboardInterrupt:
            outcome["status"] = "cancelled"
            outcome["reason"] = "interrupted at confirmation"
            record("confirm", approved=False, interrupted=True)
            return outcome
        record("confirm", approved=approved)
        if not approved:
            return refuse("approval_denied", "user declined the action")

        try:
            fresh = self.snapshot_provider()
            recheck_plan(plan, fresh)
        except ExecutionRefusal as refusal:
            return refuse(refusal.reason, refusal.detail)
        except AxUnavailable as exc:
            return refuse("snapshot_failed", str(exc))
        record("recheck", ok=True)

        # Unreachable without `approved` above; tests assert a fake port sees
        # zero perform calls on every refusal path.
        try:
            performed = self.port.perform(plan.spec)
        except ExecutionRefusal as refusal:
            return refuse(refusal.reason or "perform_failed", refusal.detail)
        self.performed_actions += 1
        outcome["performed"] = True
        record(
            "perform",
            action=plan.spec.get("action"),
            method=performed.get("method"),
            key_events=performed.get("key_events", 0),
        )

        try:
            observed = self.snapshot_provider()
            observed_window = window_from_snapshot(observed, title=self.window_title)
            passed = bool(task.verify(observed_window.elements))
        except Exception as exc:  # noqa: BLE001 - observation failures are verify failures
            return refuse("verify_failed", f"post-action observation failed: {exc}")
        outcome["verified"] = passed
        record("verify", passed=passed)
        if not passed:
            return refuse("verify_failed", "state predicate not satisfied after the action")
        outcome["status"] = "done"
        outcome["reason"] = "verified"
        return outcome


def interactive_confirmer(preview_text: str) -> bool:
    """Ask the user; EOF declines, Ctrl+C propagates as a cancellation."""
    print(f"  preview: {preview_text}")
    try:
        answer = input("  execute? [y/N] ")
    except EOFError:
        print("  (no input available; treating as a decline)")
        return False
    return answer.strip().lower() in ("y", "yes")


def _print_task_outcome(outcome: dict) -> None:
    print(f"\n=== {outcome['task_id']}: {outcome['status'].upper()} ({outcome['reason']})")
    for index, event in enumerate(outcome["events"]):
        detail = {key: value for key, value in event.items() if key != "type"}
        print(f"  {index:2d} {event['type']:>10s} {json.dumps(detail, sort_keys=True)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vision_assistant.supervised_cli",
        description="M013 supervised executor (practice window only)",
    )
    parser.add_argument("--app", default=DEFAULT_APP, help="running application name")
    parser.add_argument("--window", default=DEFAULT_WINDOW, help="window title")
    parser.add_argument("--tasks", default=None, help="comma-separated frozen task ids")
    parser.add_argument("--intent", default=None, help="scripted single intent (JSON)")
    parser.add_argument(
        "--verify",
        default=None,
        help="optional expectation for --intent: element_id=expected-substring",
    )
    parser.add_argument("--propose", choices=("model", "scripted"), default=None)
    parser.add_argument("--pin-dir", type=Path, default=DEFAULT_PIN_DIR)
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--overlay-ms", type=int, default=1200)
    parser.add_argument("--no-overlay", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    scripted = args.intent is not None
    if scripted and args.propose == "model":
        print(json.dumps({"status": "failed", "reason": "--intent is scripted; drop --propose model"}))
        return 1
    mode = "scripted" if scripted else (args.propose or "model")

    record: list[str] = []
    adapter = None
    if mode == "model":
        pin_path = args.pin_dir / "pin.json"
        if not pin_path.exists():
            print(json.dumps({"status": "failed", "reason": f"no pin at {pin_path}"}))
            return 1
        from .runtime_llamaserver import LlamaServerAdapter

        pin = json.loads(pin_path.read_text(encoding="utf-8"))
        model = next(item for item in pin["files"] if item["role"] == "model")
        mmproj = next(item for item in pin["files"] if item["role"] == "mmproj")
        adapter = LlamaServerAdapter(
            args.pin_dir / model["name"],
            args.pin_dir / mmproj["name"],
            ctx_size=args.ctx_size,
            jinja=True,
            chat_template_kwargs={"enable_thinking": False},
            log_path=REPO_ROOT / "runs" / "m013-server.log",
        )
        base_proposer = model_proposer(adapter, record=record)

        def propose(task: PracticeTask, window: AxWindow):
            from .pixels import mostly_black

            png_bytes = None
            capture_state = "placeholder"
            if window.cg_window_id is not None:
                try:
                    candidate = capture_window_png(window.cg_window_id)
                except AxUnavailable:
                    candidate = None
                if candidate is not None:
                    try:
                        if mostly_black(candidate):
                            capture_state = "black"
                        else:
                            capture_state = "ok"
                            png_bytes = candidate
                    except Exception:  # noqa: BLE001 - undecodable capture
                        capture_state = "unreadable"
            propose.last_meta = {"capture": capture_state}
            return base_proposer(task.instruction, window, png_bytes or _placeholder_png())

        propose.last_meta = None
        proposer = propose
        tasks = tuple(
            task
            for task in FROZEN_TASKS
            if args.tasks is None or task.task_id in {t.strip() for t in args.tasks.split(",")}
        )
        if args.tasks is not None:
            missing = {t.strip() for t in args.tasks.split(",")} - {task.task_id for task in tasks}
            if missing:
                print(json.dumps({"status": "failed", "reason": f"unknown tasks {sorted(missing)}"}))
                return 1
    else:
        try:
            payload = json.loads(args.intent)
        except json.JSONDecodeError as exc:
            print(json.dumps({"status": "failed", "reason": f"invalid --intent JSON: {exc}"}))
            return 1

        def verify(elements: tuple) -> bool:
            if not args.verify:
                return True
            identifier, _, expected = args.verify.partition("=")
            value = _element_value(elements, identifier) or ""
            return expected in value

        tasks = (
            PracticeTask(
                "scripted",
                f"scripted intent: {payload.get('kind', '?')}",
                verify,
            ),
        )
        proposer = lambda task, window: payload  # noqa: E731 - trivial injection

    vision = AxVisionAdapter()
    port = AxActionPort()
    overlay = None
    if not args.no_overlay:
        overlay = lambda region: port.overlay(region, ms=args.overlay_ms)  # noqa: E731

    runner = SupervisedRunner(
        snapshot_provider=lambda: vision.snapshot(app_name=args.app),
        port=port,
        confirmer=interactive_confirmer,
        overlay=overlay,
        window_title=args.window,
    )

    started = time.monotonic()
    try:
        if adapter is not None:
            adapter.start()
        result = runner.run(tasks, proposer)
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled"}))
        return 130
    finally:
        if adapter is not None:
            adapter.stop()

    result["total_ms"] = round((time.monotonic() - started) * 1000.0, 3)
    result["raw_answers"] = record

    for task in tasks:
        _print_task_outcome(result["tasks"][task.task_id])

    out_path = args.out or (REPO_ROOT / "runs" / "m013" / f"session-{result['run_id']}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    summary = {
        "tasks": {task_id: outcome["status"] for task_id, outcome in result["tasks"].items()},
        "all_done": result["all_done"],
        "performed_actions": result["performed_actions"],
        "unapproved_actions": result["unapproved_actions"],
        "refusals": result["refusals"],
        "total_ms": result["total_ms"],
        "run_id": result["run_id"],
    }
    print(f"\nsummary: {json.dumps(summary, sort_keys=True)}")
    print(f"result: {out_path}")

    if any(outcome["status"] == "cancelled" for outcome in result["tasks"].values()):
        print(json.dumps({"status": "cancelled", "run_id": result["run_id"]}))
        return 130
    return 0 if result["all_done"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
