"""M011 disposable simulated action loop.

observe -> propose -> validate -> approve -> fake-execute -> verify, with
retry, cancellation, and emergency stop. Intents pass the M010 schema and
consequence policy; execution mutates a `PracticeApp` Python object only.
A denial, cancellation, stale observation, or exhausted budget is final.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .events import ANALYSING, CANCELLED, DONE, Event, FAILED, KIND_REAL
from .intents import ActionPolicy, IntentSchemaError, parse_intent
from .practice_app import PracticeApp, PracticeTask
from .trace import JsonlTraceSink

MAX_STEPS_PER_TASK = 12
MAX_RETRIES = 2


class SimulatedActionLoop:
    def __init__(
        self,
        app: PracticeApp,
        task: PracticeTask,
        proposer: Callable[[bytes, str, int], list],
        *,
        policy: ActionPolicy | None = None,
        approver: Callable | None = None,
        trace_dir: Path | None = None,
        trace_id: str = "m011-loop",
        max_steps: int = MAX_STEPS_PER_TASK,
        max_retries: int = MAX_RETRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.task = task
        self._proposer = proposer
        self.policy = policy or ActionPolicy()
        self._approver = approver
        self._max_steps = max_steps
        self._max_retries = max_retries
        self._clock = clock
        self._stopped = False
        self._steps = 0
        self._events: list[dict] = []
        self._trace_id = trace_id
        self._sink: JsonlTraceSink | None = None
        if trace_dir is not None:
            self._sink = JsonlTraceSink(
                Path(trace_dir) / f"{trace_id}.jsonl",
                trace_id=trace_id,
                kind=KIND_REAL,
                created_at_ms=clock() * 1000.0,
            )

    # -- control -------------------------------------------------------------

    def stop(self) -> None:
        """Emergency stop: final on the next loop check."""
        self._stopped = True

    # -- recording -----------------------------------------------------------

    def _record(self, event_type: str, payload: dict, state: str) -> None:
        self._events.append({"type": event_type, **payload})
        if self._sink is not None:
            self._sink.emit(
                Event(
                    trace_id=self._trace_id,
                    event_id=f"e{len(self._events)}",
                    ts_ms=self._clock() * 1000.0,
                    type=event_type,
                    state=state,
                    payload=payload,
                )
            )

    def _finish(self, status: str, reason: str) -> dict:
        state = {"done": DONE, "blocked": FAILED, "cancelled": CANCELLED}[status]
        self._record(status, {"reason": reason, "steps": self._steps}, state)
        if self._sink is not None:
            self._sink.write()
        return {
            "task_id": self.task.task_id,
            "instruction": self.task.instruction,
            "status": status,
            "reason": reason,
            "steps": self._steps,
            "events": list(self._events),
            "state": dict(self.app.state),
            "host_input_events": 0,  # structurally guaranteed; enforced by source tests
        }

    # -- main loop -----------------------------------------------------------

    def run(self) -> dict:
        retries = 0
        while self._steps < self._max_steps:
            if self._stopped:
                return self._finish("cancelled", "emergency_stop")
            self._steps += 1
            observed_revision = self.app.revision
            self._record("observe", {"revision": observed_revision}, ANALYSING)
            png = self.app.render()
            try:
                payloads = list(
                    self._proposer(png, self.task.instruction, observed_revision) or []
                )
            except Exception as exc:  # noqa: BLE001 - a failed proposal is an attempt
                payloads = []
                self._record("propose", {"count": 0, "error": type(exc).__name__}, ANALYSING)
            else:
                self._record("propose", {"count": len(payloads)}, ANALYSING)

            if not payloads:
                retries += 1
                self._record("retry", {"attempt": retries, "reason": "no_proposal"}, ANALYSING)
                if retries > self._max_retries:
                    return self._finish("blocked", "no_proposal")
                continue

            acted = False
            for index, payload in enumerate(payloads):
                try:
                    intent = parse_intent(payload)
                except IntentSchemaError as exc:
                    self._record(
                        "validate",
                        {"index": index, "parsed": False, "error": str(exc)},
                        ANALYSING,
                    )
                    continue
                decision = self.policy.review(intent, intent_count=self._steps - 1)
                self._record(
                    "validate",
                    {
                        "index": index,
                        "parsed": True,
                        "kind": intent.kind,
                        "verdict": decision.verdict,
                        "reasons": list(decision.reasons),
                    },
                    ANALYSING,
                )
                if decision.verdict == "denied":
                    return self._finish("blocked", "denied")
                if intent.kind == "cancel":
                    return self._finish("cancelled", "cancel_intent")
                if intent.kind == "finish":
                    passed = self.task.verify(dict(self.app.state))
                    self._record("verify", {"passed": passed}, ANALYSING)
                    if passed:
                        return self._finish("done", "finish_verified")
                    retries += 1
                    self._record("retry", {"attempt": retries, "reason": "verify_failed"}, ANALYSING)
                    if retries > self._max_retries:
                        return self._finish("blocked", "verify_failed")
                    acted = True
                    break
                if intent.kind == "observe":
                    acted = True  # spends the step; the loop re-observes next
                    break

                approved = True if self._approver is None else bool(
                    self._approver(intent, decision)
                )
                self._record(
                    "approve",
                    {"kind": intent.kind, "approved": approved, "approved_by": "simulation"},
                    ANALYSING,
                )
                if not approved:
                    return self._finish("blocked", "approval_denied")
                if self.app.revision != observed_revision:
                    self._record(
                        "execute",
                        {"kind": intent.kind, "applied": False, "reason": "stale observation"},
                        FAILED,
                    )
                    return self._finish("blocked", "stale_observation")
                outcome = self.app.apply_intent(intent)
                self._record(
                    "execute",
                    {
                        "kind": intent.kind,
                        "applied": outcome["applied"],
                        "reason": outcome["reason"],
                    },
                    ANALYSING,
                )
                if not outcome["applied"]:
                    retries += 1
                    self._record("retry", {"attempt": retries, "reason": outcome["reason"]}, ANALYSING)
                    if retries > self._max_retries:
                        return self._finish("blocked", "execute_failed")
                    acted = True
                    break
                passed = self.task.verify(dict(self.app.state))
                self._record("verify", {"passed": passed}, ANALYSING)
                if passed:
                    return self._finish("done", "verified")
                retries += 1
                self._record("retry", {"attempt": retries, "reason": "verify_failed"}, ANALYSING)
                if retries > self._max_retries:
                    return self._finish("blocked", "verify_failed")
                acted = True
                break

            if not acted:
                retries += 1
                self._record("retry", {"attempt": retries, "reason": "no_valid_intent"}, ANALYSING)
                if retries > self._max_retries:
                    return self._finish("blocked", "no_valid_intent")

        return self._finish("blocked", "step_budget_exhausted")
