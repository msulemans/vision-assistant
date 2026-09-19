"""M014 bounded task agent: multi-step goals under hard budgets, with
recovery, user-takeover detection, and explicit blocked/finished states.

One task = one frozen goal. The agent pursues it as a sequence of separately
proposed, previewed, confirmed, freshly re-checked, performed, and verified
steps — each step re-derived from a fresh read-only observation, never
executed blind from an up-front multi-step plan.

Hard bounds (defaults; the CLI can only lower them for demos):

- max 8 action steps per task,
- max 120 s wall clock per task (prompt waits included),
- max 2 stale-frame recoveries per step.

Safety semantics (frozen in VISION_STATE):

- Scope: one window of one app. Any additional window at any observation —
  dialog, sheet, alert — blocks the task with ``unexpected_dialog`` before
  any further action.
- Goal lock: every proposal must address an element on the task's frozen
  allowlist; anything else blocks with ``off_goal_denied``. Screen text is
  data, never instructions: adversarial markers are flagged in the
  transcript, and a proposal that targets flagged text blocks with
  ``injection_suspected``.
- User takeover: the agent yields (``user_takeover``) when the target app
  becomes frontmost between steps, or when a post-action observation shows
  state changes beyond the agent's own action. It never fights for focus.
- Permission: trust sampled at task start; losing it mid-run blocks with
  ``permission_changed``.
- Stale frames recover (bounded re-observation, re-planning, and a fresh
  confirmation); exhaustion blocks with ``recovery_failed``. Everything
  else is terminal.

This module contains no action APIs itself (source-scanned): every posted
action goes through the injected action port.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .ax_vision import AxSnapshot, AxUnavailable, AxWindow
from .executor import ExecutionRefusal, plan_action, recheck_plan, window_from_snapshot
from .intents import ActionPolicy, IntentSchemaError, parse_intent

DEFAULT_MAX_STEPS = 8
DEFAULT_MAX_SECONDS = 120.0
DEFAULT_MAX_RECOVERIES = 2
RECOVERABLE_REFUSALS = frozenset({"stale_frame"})

# Adversarial screen-text markers (defense in depth next to the goal lock,
# policy, and confirmation). Matching is case-insensitive substring.
INJECTION_MARKERS = (
    "ignore previous",
    "ignore above",
    "ignore all previous",
    "disregard",
    "new instructions",
    "system:",
    "assistant:",
    "instead, click",
    "instead click",
)

MUTATING_KINDS = ("click_element", "type_text", "press_key")


def _element_value(elements, identifier: str) -> str | None:
    for element in elements:
        if element.identifier == identifier:
            return element.value
    return None


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    goal: str
    allowed_identifiers: frozenset[str]
    verify: Callable[[tuple], bool]


def _multi_verify(elements) -> bool:
    return _element_value(elements, "app:notify-toggle") == "1" and "hello" in (
        _element_value(elements, "app:search") or ""
    )


def _sync_hello_verify(elements) -> bool:
    return _element_value(elements, "app:sync-toggle") == "1" and "hello" in (
        _element_value(elements, "app:search") or ""
    )


AGENT_TASKS: tuple[AgentTask, ...] = (
    AgentTask(
        "enable-sync",
        "Turn on the Sync checkbox.",
        frozenset({"app:sync-toggle"}),
        lambda elements: _element_value(elements, "app:sync-toggle") == "1",
    ),
    AgentTask(
        "multi-enable",
        "Turn on the Notifications checkbox AND type the word hello into the Search field.",
        frozenset({"app:notify-toggle", "app:search"}),
        _multi_verify,
    ),
    AgentTask(
        "sync-and-hello",
        "Turn on the Sync checkbox AND type the word hello into the Search field.",
        frozenset({"app:sync-toggle", "app:search"}),
        _sync_hello_verify,
    ),
)


def injection_flags(window: AxWindow) -> list[dict]:
    """Scan observed screen text for adversarial markers (data, not action)."""
    flags: list[dict] = []

    def scan(text: str | None, source: str, identifier: str | None) -> None:
        if not text:
            return
        lowered = text.lower()
        for marker in INJECTION_MARKERS:
            if marker in lowered:
                flags.append(
                    {
                        "source": source,
                        "identifier": identifier,
                        "marker": marker,
                        "text": text[:160],
                    }
                )
                break

    scan(window.title, "window_title", None)
    for element in window.elements:
        identifier = element.identifier
        scan(element.title, f"title:{identifier or element.path}", identifier)
        scan(element.description, f"description:{identifier or element.path}", identifier)
        scan(element.value, f"value:{identifier or element.path}", identifier)
    return flags


def element_values(window: AxWindow) -> dict[str, str | None]:
    return {
        element.identifier: element.value
        for element in window.elements
        if element.identifier
    }


def unexplained_changes(
    before: dict[str, str | None],
    after: dict[str, str | None],
    *,
    acted_identifier: str | None,
) -> list[dict]:
    """State changes that the agent's own action cannot explain."""
    changes = []
    for identifier in sorted(set(before) | set(after)):
        if identifier == acted_identifier:
            continue
        if before.get(identifier) != after.get(identifier):
            changes.append(
                {
                    "identifier": identifier,
                    "before": before.get(identifier),
                    "after": after.get(identifier),
                }
            )
    return changes


def foreign_windows(snapshot: AxSnapshot, *, scoped_title: str | None) -> list[dict]:
    """Windows other than the scoped one — dialogs, sheets, alerts."""
    return [
        {"title": window.title, "subrole": window.subrole}
        for window in snapshot.windows
        if window.title != scoped_title
    ]


def addressed_identifiers(intent) -> set[str]:
    if intent.kind in ("click_element", "type_text"):
        element_id = intent.params.get("element_id")
        if element_id:
            return {element_id}
    return set()


class BoundedAgent:
    """Runs frozen-goal tasks stepwise with budgets, recovery, and takeover."""

    def __init__(
        self,
        *,
        snapshot_provider: Callable[[], AxSnapshot],
        port,
        confirmer: Callable[[str], bool],
        overlay: Callable[[tuple], bool] | None = None,
        frontmost_provider: Callable[[], dict] | None = None,
        window_title: str = "Practice App",
        policy: ActionPolicy | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_seconds: float = DEFAULT_MAX_SECONDS,
        max_recoveries: int = DEFAULT_MAX_RECOVERIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.port = port
        self.confirmer = confirmer
        self.overlay = overlay
        self.frontmost_provider = frontmost_provider
        self.window_title = window_title
        self.policy = policy or ActionPolicy()
        self.max_steps = int(max_steps)
        self.max_seconds = float(max_seconds)
        self.max_recoveries = int(max_recoveries)
        self.clock = clock
        self.performed_actions = 0
        self.unapproved_actions = 0
        self.trusted_at_start: bool | None = None

    # ---------------------------------------------------------------- helpers

    def _permission_label(self) -> str:
        return "permission_changed" if self.trusted_at_start is True else "permission_required"

    def _capture(self) -> tuple[AxSnapshot, AxWindow]:
        """One fresh observation; raises like the underlying layers."""
        snapshot = self.snapshot_provider()
        window = window_from_snapshot(snapshot, title=self.window_title)
        return snapshot, window

    def _anomaly(self, snapshot: AxSnapshot, window: AxWindow, *, focus_baseline) -> tuple[str, str] | None:
        foreign = foreign_windows(snapshot, scoped_title=self.window_title)
        if foreign:
            return (
                "unexpected_dialog",
                f"extra window(s) present: {json.dumps(foreign, sort_keys=True)}",
            )
        if focus_baseline and window.focused is not True:
            return ("focus_changed", "scoped window lost in-app focus (focus moved while scoped)")
        return None

    def _sample_frontmost(self, state: dict) -> tuple[dict | None, bool]:
        """Record the frontmost app; report a transition into the target app.

        ``state`` carries ``prev_pid`` across samples within one task.
        """
        current: dict | None = None
        if self.frontmost_provider is not None:
            try:
                current = self.frontmost_provider()
            except Exception:  # noqa: BLE001 - best effort, never blocks
                current = None
        takeover = False
        if current is not None and isinstance(current.get("pid"), int):
            pid = current["pid"]
            target = state.get("target_pid")
            prev = state.get("prev_pid")
            if target is not None and pid == target and prev is not None and prev != target:
                takeover = True
            state["prev_pid"] = pid
        return current, takeover

    # ---------------------------------------------------------------- driving

    def run(self, tasks: tuple[AgentTask, ...], proposer) -> dict:
        run_id = f"m014-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        check = getattr(self.port, "check", None)
        if callable(check):
            try:
                self.trusted_at_start = bool(check().get("trusted"))
            except Exception:  # noqa: BLE001 - trust stays unknown
                self.trusted_at_start = None
        outcomes = {task.task_id: self.run_task(task, proposer) for task in tasks}
        terminals = {task_id: outcome["terminal"] for task_id, outcome in outcomes.items()}
        return {
            "run_id": run_id,
            "window_title": self.window_title,
            "trusted_at_start": self.trusted_at_start,
            "tasks": outcomes,
            "terminals": terminals,
            "all_finished": all(terminal == "finished" for terminal in terminals.values()),
            "performed_actions": self.performed_actions,
            "unapproved_actions": self.unapproved_actions,
        }

    def run_task(self, task: AgentTask, proposer) -> dict:
        started = self.clock()
        events: list[dict] = []
        history: list[str] = []
        frontmost_state: dict = {}
        recoveries_used = 0
        outcome: dict = {
            "task_id": task.task_id,
            "goal": task.goal,
            "status": "unknown",
            "reason": "",
            "terminal": "",
            "steps_used": 0,
            "max_steps": self.max_steps,
            "elapsed_ms": None,
            "max_seconds": self.max_seconds,
            "recoveries_used": 0,
            "max_recoveries": self.max_recoveries,
            "performed": [],
            "injection_flags": [],
            "events": events,
        }

        def record(event_type: str, **payload) -> None:
            events.append(
                {
                    "type": event_type,
                    "at_ms": round((self.clock() - started) * 1000.0, 1),
                    **payload,
                }
            )

        def block(status: str, detail: str = "") -> dict:
            outcome["status"] = status
            outcome["reason"] = detail
            outcome["terminal"] = f"blocked:{status}"
            outcome["recoveries_used"] = recoveries_used
            outcome["elapsed_ms"] = round((self.clock() - started) * 1000.0, 1)
            record("blocked", status=status, detail=detail)
            return outcome

        def complete(detail: str) -> dict:
            outcome["status"] = "finished"
            outcome["reason"] = detail
            outcome["terminal"] = "finished"
            outcome["recoveries_used"] = recoveries_used
            outcome["elapsed_ms"] = round((self.clock() - started) * 1000.0, 1)
            record("finished", detail=detail)
            return outcome

        def cancel(detail: str) -> dict:
            outcome["status"] = "cancelled"
            outcome["reason"] = detail
            outcome["terminal"] = "cancelled"
            outcome["recoveries_used"] = recoveries_used
            outcome["elapsed_ms"] = round((self.clock() - started) * 1000.0, 1)
            return outcome

        def observe_event(snapshot: AxSnapshot, window: AxWindow, *, tag: str) -> list[dict]:
            flags = injection_flags(window)
            record(
                "observe",
                tag=tag,
                window_frame=list(window.frame) if window.frame else None,
                windows=[
                    {"title": w.title, "subrole": w.subrole, "focused": w.focused}
                    for w in snapshot.windows
                ],
                values=element_values(window),
                injection_flags=flags,
            )
            seen = {
                (flag["source"], flag["marker"], flag["text"])
                for flag in outcome["injection_flags"]
            }
            for flag in flags:
                key = (flag["source"], flag["marker"], flag["text"])
                if key not in seen:
                    outcome["injection_flags"].append(flag)
                    seen.add(key)
            return flags

        # ---- first observation -------------------------------------------------
        try:
            snapshot, window = self._capture()
        except ExecutionRefusal as refusal:
            return block(refusal.reason, refusal.detail)
        except AxUnavailable as exc:
            status = self._permission_label() if exc.reason == "permission" else "snapshot_failed"
            return block(status, str(exc))
        anomaly = self._anomaly(snapshot, window, focus_baseline=None)
        if anomaly is not None:
            return block(*anomaly)
        live_flags = observe_event(snapshot, window, tag="start")
        focus_baseline = window.focused
        frontmost_state["target_pid"] = snapshot.pid
        self._sample_frontmost(frontmost_state)  # baseline sample
        values_before = element_values(window)

        if task.verify(window.elements):
            outcome["steps_used"] = 0
            return complete("state already satisfies the goal")

        # ---- bounded step loop -------------------------------------------------
        while True:
            elapsed = self.clock() - started
            if outcome["steps_used"] >= self.max_steps:
                return block(
                    "budget_exceeded",
                    f"step budget exhausted ({outcome['steps_used']}/{self.max_steps} actions)",
                )
            if elapsed >= self.max_seconds:
                return block(
                    "budget_exceeded",
                    f"time budget exhausted ({round(elapsed * 1000)} ms of {round(self.max_seconds * 1000)} ms)",
                )

            front, takeover = self._sample_frontmost(frontmost_state)
            if takeover:
                record("takeover", where="loop-top", frontmost=front)
                return block("user_takeover", "the target app became frontmost between steps")

            try:
                payload = proposer(task, window, history)
            except Exception as exc:  # noqa: BLE001 - proposer failures block the task
                return block("no_actionable_proposal", f"proposer failed: {exc}")
            if payload is None:
                return block("no_actionable_proposal", "no parseable proposal")
            meta = getattr(proposer, "last_meta", None)
            if isinstance(meta, dict):
                record("propose", payload=payload, **meta)
            else:
                record("propose", payload=payload)

            kind = payload.get("kind") if isinstance(payload, dict) else None
            if kind == "finish":
                if task.verify(window.elements):
                    return complete("model reported finish and the goal verifies")
                return block(
                    "finish_unverified",
                    "model proposed finish but the goal state does not hold",
                )
            if kind == "cancel":
                return block("no_actionable_proposal", "model proposed cancel")

            try:
                intent = parse_intent(payload)
            except IntentSchemaError as exc:
                return block("schema_rejected", str(exc))
            record("intent", kind=intent.kind, description=intent.describe())

            # ---- goal lock + injection review ---------------------------------
            flagged_ids = {flag["identifier"] for flag in live_flags if flag["identifier"]}
            targets = addressed_identifiers(intent)
            if targets & flagged_ids:
                record("injection", verdict="targets flagged screen text", flags=live_flags)
                return block(
                    "injection_suspected",
                    f"proposal targets element carrying adversarial text: {sorted(targets & flagged_ids)}",
                )
            if intent.kind == "press_key":
                return block(
                    "unaddressed",
                    "press_key has no element identity; the bounded agent only posts element-addressed actions",
                )
            if intent.kind in ("click_element", "type_text") and not targets:
                return block("unaddressed", f"{intent.kind} requires an element_id in agent mode")
            if targets and not targets <= task.allowed_identifiers:
                return block(
                    "off_goal_denied",
                    f"{sorted(targets)} is outside the goal allowlist {sorted(task.allowed_identifiers)}",
                )
            if live_flags:
                record("injection", verdict="flagged screen text ignored; action stays on goal", flags=live_flags)

            decision = self.policy.review(intent, intent_count=outcome["steps_used"])
            record("policy", verdict=decision.verdict, reasons=list(decision.reasons))
            if decision.verdict == "denied":
                return block("policy_denied", "; ".join(decision.reasons))
            if decision.verdict != "needs_confirmation":
                return block("no_actionable_proposal", f"{intent.kind} performs no host action")

            # ---- attempt loop: plan → preflight → confirm → recheck → perform --
            attempts = 0
            while True:
                try:
                    plan = plan_action(intent, snapshot, window_title=self.window_title)
                except ExecutionRefusal as refusal:
                    return block(refusal.reason, refusal.detail)
                identity = None
                if plan.element is not None:
                    identity = {
                        "role": plan.element.role,
                        "name": plan.element.display_name,
                        "identifier": plan.element.identifier,
                        "frame": list(plan.element.frame) if plan.element.frame else None,
                    }
                record(
                    "plan",
                    identity=identity,
                    spec=plan.spec,
                    recovery_attempt=attempts,
                )

                try:
                    self.port.plan(plan.spec)
                    record("preflight", ok=True)
                except ExecutionRefusal as refusal:
                    if refusal.reason == "permission":
                        return block(self._permission_label(), refusal.detail or refusal.reason)
                    stale = refusal.reason in RECOVERABLE_REFUSALS
                    if not stale or attempts >= self.max_recoveries:
                        if stale:
                            return block(
                                "recovery_failed",
                                f"{refusal.reason} persisted after {attempts} recovery attempt(s)",
                            )
                        return block(
                            refusal.reason,
                            f"preflight refused: {refusal.detail or refusal.reason}",
                        )
                    attempts += 1
                    recoveries_used += 1
                    record(
                        "recover",
                        stage="preflight",
                        reason=refusal.reason,
                        detail=refusal.detail,
                        attempt=attempts,
                    )
                    try:
                        snapshot, window = self._capture()
                    except ExecutionRefusal as inner:
                        return block(inner.reason, inner.detail)
                    except AxUnavailable as exc:
                        status = (
                            self._permission_label()
                            if exc.reason == "permission"
                            else "snapshot_failed"
                        )
                        return block(status, str(exc))
                    anomaly = self._anomaly(snapshot, window, focus_baseline=focus_baseline)
                    if anomaly is not None:
                        return block(*anomaly)
                    live_flags = observe_event(snapshot, window, tag="recovery")
                    continue

                preview = plan.description
                if identity and identity["frame"]:
                    preview += f" | region {tuple(round(value) for value in identity['frame'])}"
                record("preview", text=preview)
                if (
                    self.overlay is not None
                    and plan.element is not None
                    and plan.element.frame is not None
                ):
                    record("overlay", shown=bool(self.overlay(plan.element.frame)))

                try:
                    approved = bool(self.confirmer(preview))
                except KeyboardInterrupt:
                    record("confirm", approved=False, interrupted=True)
                    return cancel("interrupted at confirmation")
                record("confirm", approved=approved)
                if not approved:
                    return block("approval_denied", "user declined the action")

                front, takeover = self._sample_frontmost(frontmost_state)
                if takeover:
                    record("takeover", where="post-confirm", frontmost=front)
                    return block(
                        "user_takeover",
                        "the target app became frontmost just before posting; nothing was performed",
                    )

                try:
                    fresh = self.snapshot_provider()
                    fresh_window = recheck_plan(plan, fresh)
                    record("recheck", ok=True)
                    anomaly = self._anomaly(fresh, fresh_window, focus_baseline=focus_baseline)
                    if anomaly is not None:
                        return block(*anomaly)
                except ExecutionRefusal as refusal:
                    if refusal.reason == "permission":
                        return block(self._permission_label(), refusal.detail or refusal.reason)
                    stale = refusal.reason in RECOVERABLE_REFUSALS
                    if not stale or attempts >= self.max_recoveries:
                        if stale:
                            return block(
                                "recovery_failed",
                                f"{refusal.reason} persisted after {attempts} recovery attempt(s)",
                            )
                        return block(refusal.reason, refusal.detail)
                    attempts += 1
                    recoveries_used += 1
                    record(
                        "recover",
                        stage="recheck",
                        reason=refusal.reason,
                        detail=refusal.detail,
                        attempt=attempts,
                    )
                    snapshot = fresh
                    window = window_from_snapshot(fresh, title=self.window_title)
                    anomaly = self._anomaly(fresh, window, focus_baseline=focus_baseline)
                    if anomaly is not None:
                        return block(*anomaly)
                    live_flags = observe_event(fresh, window, tag="recovery")
                    continue
                except AxUnavailable as exc:
                    status = (
                        self._permission_label() if exc.reason == "permission" else "snapshot_failed"
                    )
                    return block(status, str(exc))

                try:
                    performed = self.port.perform(plan.spec)
                except ExecutionRefusal as refusal:
                    if refusal.reason == "permission":
                        return block(self._permission_label(), refusal.detail or refusal.reason)
                    return block(refusal.reason or "perform_failed", refusal.detail)

                # Approved and posted: this is the only place a step is consumed.
                self.performed_actions += 1
                outcome["steps_used"] += 1
                acted = plan.element.identifier if plan.element is not None else None
                record(
                    "perform",
                    action=plan.spec.get("action"),
                    method=performed.get("method"),
                    key_events=performed.get("key_events", 0),
                    identifier=acted,
                )
                outcome["performed"].append(
                    {
                        "kind": plan.kind,
                        "identifier": acted,
                        "action": plan.spec.get("action"),
                        "method": performed.get("method"),
                    }
                )
                history.append(f"step {outcome['steps_used']}: {plan.description}")

                try:
                    snapshot, window = self._capture()
                except ExecutionRefusal as refusal:
                    return block(refusal.reason, f"post-action observation failed: {refusal.detail}")
                except AxUnavailable as exc:
                    status = (
                        self._permission_label() if exc.reason == "permission" else "snapshot_failed"
                    )
                    return block(status, str(exc))
                anomaly = self._anomaly(snapshot, window, focus_baseline=focus_baseline)
                if anomaly is not None:
                    return block(*anomaly)
                live_flags = observe_event(snapshot, window, tag="post-perform")

                changes = unexplained_changes(
                    values_before, element_values(window), acted_identifier=acted
                )
                record("state_diff", acted_identifier=acted, unexplained=changes)
                if changes:
                    return block(
                        "user_takeover",
                        f"state changed outside the agent's own action: {json.dumps(changes, sort_keys=True)}",
                    )
                values_before = element_values(window)

                passed = bool(task.verify(window.elements))
                record("verify", passed=passed, steps_used=outcome["steps_used"])
                if passed:
                    outcome["recoveries_used"] = recoveries_used
                    return complete(f"goal verified after {outcome['steps_used']} step(s)")
                break  # next step; loop re-checks budgets, takeover, and proposes

        # Unreachable: every exit path returns from inside the loops.


def summarize_for_prompt(task: AgentTask, window: AxWindow, history: list[str], *, line_limit: int = 200) -> str:
    """The frozen element list + goal + history block for the model prompt."""
    lines = []
    for element in window.elements:
        if not element.identifier:
            continue
        value = "(secure)" if element.secure else (element.value or "")
        lines.append(f"- {element.identifier} | {element.role} | {element.display_name} | value={value}")
    element_block = "\n".join(lines[:line_limit]) or "(no identified elements)"
    history_block = "\n".join(history) if history else "(no steps performed yet)"
    return (
        f"GOAL (frozen): {task.goal}\n"
        f"Allowed element identifiers: {sorted(task.allowed_identifiers)}\n"
        f"Steps already performed:\n{history_block}\n"
        f"Current elements (authoritative):\n{element_block}"
    )
