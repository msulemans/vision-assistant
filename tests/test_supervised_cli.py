from __future__ import annotations

import unittest

from vision_assistant.ax_vision import AxElement, AxSnapshot, AxWindow
from vision_assistant.executor import ExecutionRefusal
from vision_assistant.supervised_cli import PracticeTask, SupervisedRunner


def _element(
    identifier: str,
    value: str | None,
    *,
    frame: tuple[float, float, float, float] = (200.0, 380.0, 20.0, 20.0),
    role: str = "AXCheckBox",
    title: str = "Sync",
) -> AxElement:
    return AxElement(
        role=role,
        subrole=None,
        title=title,
        description=None,
        value=value,
        identifier=identifier,
        frame=frame,
        enabled=True,
        focused=None,
        secure=False,
        depth=0,
        path=f"w0/{identifier}",
    )


def _snapshot(elements: tuple[AxElement, ...], *, title: str = "Practice App") -> AxSnapshot:
    window = AxWindow(
        title=title,
        frame=(100.0, 100.0, 480.0, 300.0),
        focused=True,
        cg_window_id=1,
        elements=elements,
    )
    return AxSnapshot(app="Practice App", pid=1, windows=(window,))


def _value(elements: tuple[AxElement, ...], identifier: str) -> str | None:
    for element in elements:
        if element.identifier == identifier:
            return element.value
    return None


class _Provider:
    def __init__(self, snapshots: list[AxSnapshot]) -> None:
        self._snapshots = list(snapshots)
        self.calls = 0

    def __call__(self) -> AxSnapshot:
        self.calls += 1
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]


class _Port:
    def __init__(self, plan_refusal: str | None = None) -> None:
        self.plans: list[dict] = []
        self.performs: list[dict] = []
        self.plan_refusal = plan_refusal

    def plan(self, spec: dict) -> dict:
        self.plans.append(spec)
        if self.plan_refusal:
            raise ExecutionRefusal(self.plan_refusal)
        return {"planned": True}

    def perform(self, spec: dict) -> dict:
        self.performs.append(spec)
        return {"performed": True, "key_events": 0}


SYNC_TASK = PracticeTask(
    "enable-sync",
    "Turn on the Sync checkbox.",
    lambda elements: _value(elements, "app:sync-toggle") == "1",
)
CLICK_SYNC = {"kind": "click_element", "element_id": "app:sync-toggle"}


class SupervisedRunnerTest(unittest.TestCase):
    def _run(
        self,
        snapshots: list[AxSnapshot],
        payload,
        *,
        confirmed: bool = True,
        plan_refusal: str | None = None,
    ):
        provider = _Provider(snapshots)
        port = _Port(plan_refusal=plan_refusal)
        overlays: list[tuple] = []
        previews: list[str] = []

        def confirmer(preview_text: str) -> bool:
            previews.append(preview_text)
            if confirmed == "interrupt":
                raise KeyboardInterrupt
            return bool(confirmed)

        runner = SupervisedRunner(
            snapshot_provider=provider,
            port=port,
            confirmer=confirmer,
            overlay=lambda region: overlays.append(region) or True,
        )
        proposer = lambda task, window: payload  # noqa: E731
        result = runner.run((SYNC_TASK,), proposer)
        return result, result["tasks"]["enable-sync"], provider, port, overlays, previews

    def test_happy_path_performs_once_and_verifies(self) -> None:
        before = _snapshot((_element("app:sync-toggle", "0"),))
        recheck = _snapshot((_element("app:sync-toggle", "0"),))
        after = _snapshot((_element("app:sync-toggle", "1"),))
        result, outcome, provider, port, overlays, previews = self._run(
            [before, recheck, after], CLICK_SYNC
        )
        self.assertEqual(outcome["status"], "done")
        self.assertTrue(outcome["verified"])
        self.assertEqual(len(port.performs), 1)
        self.assertEqual(port.performs[0]["element"], {"identifier": "app:sync-toggle"})
        self.assertEqual(result["performed_actions"], 1)
        self.assertEqual(result["unapproved_actions"], 0)
        self.assertTrue(result["all_done"])
        self.assertEqual(overlays, [(200.0, 380.0, 20.0, 20.0)])
        self.assertEqual(provider.calls, 3)
        self.assertEqual(len(previews), 1)

    def test_declined_confirmation_performs_nothing(self) -> None:
        snapshot = _snapshot((_element("app:sync-toggle", "0"),))
        result, outcome, provider, port, _, _ = self._run([snapshot], CLICK_SYNC, confirmed=False)
        self.assertEqual(outcome["status"], "approval_denied")
        self.assertEqual(len(port.plans), 1)  # preflight runs before the question
        self.assertEqual(port.performs, [])
        self.assertEqual(result["performed_actions"], 0)

    def test_policy_denied_secret_target_performs_nothing(self) -> None:
        snapshot = _snapshot((_element("app:sync-toggle", "0"),))
        payload = {"kind": "type_text", "field": "Password", "text": "hunter2"}
        _, outcome, _, port, overlays, previews = self._run([snapshot], payload)
        self.assertEqual(outcome["status"], "policy_denied")
        self.assertEqual(port.performs, [])
        self.assertEqual(port.plans, [])
        self.assertEqual(overlays, [])
        self.assertEqual(previews, [])

    def test_schema_rejected_performs_nothing(self) -> None:
        snapshot = _snapshot((_element("app:sync-toggle", "0"),))
        _, outcome, _, port, _, _ = self._run([snapshot], {"kind": "click_element"})
        self.assertEqual(outcome["status"], "schema_rejected")
        self.assertEqual(port.performs, [])

    def test_unknown_element_refuses_not_found(self) -> None:
        snapshot = _snapshot((_element("app:sync-toggle", "0"),))
        _, outcome, _, port, _, _ = self._run(
            [snapshot], {"kind": "click_element", "element_id": "app:ghost"}
        )
        self.assertEqual(outcome["status"], "not_found")
        self.assertEqual(port.performs, [])
        self.assertEqual(port.plans, [])

    def test_preflight_refusal_blocks_before_confirmation(self) -> None:
        snapshot = _snapshot((_element("app:sync-toggle", "0"),))
        _, outcome, _, port, _, previews = self._run(
            [snapshot], CLICK_SYNC, plan_refusal="disabled_element"
        )
        self.assertEqual(outcome["status"], "disabled_element")
        self.assertEqual(port.performs, [])
        self.assertEqual(previews, [])

    def test_stale_frame_refusal_after_confirmation(self) -> None:
        before = _snapshot((_element("app:sync-toggle", "0"),))
        moved = _snapshot((_element("app:sync-toggle", "0", frame=(260.0, 420.0, 20.0, 20.0)),))
        _, outcome, _, port, _, _ = self._run([before, moved], CLICK_SYNC)
        self.assertEqual(outcome["status"], "stale_frame")
        self.assertEqual(port.performs, [])

    def test_verify_failure_is_final_and_recorded(self) -> None:
        before = _snapshot((_element("app:sync-toggle", "0"),))
        recheck = _snapshot((_element("app:sync-toggle", "0"),))
        after = _snapshot((_element("app:sync-toggle", "0"),))
        result, outcome, _, port, _, _ = self._run([before, recheck, after], CLICK_SYNC)
        self.assertEqual(outcome["status"], "verify_failed")
        self.assertEqual(len(port.performs), 1)
        self.assertEqual(result["performed_actions"], 1)

    def test_cancelled_at_confirmation_performs_nothing(self) -> None:
        snapshot = _snapshot((_element("app:sync-toggle", "0"),))
        result, outcome, _, port, _, _ = self._run([snapshot], CLICK_SYNC, confirmed="interrupt")
        self.assertEqual(outcome["status"], "cancelled")
        self.assertEqual(port.performs, [])
        self.assertEqual(result["refusals"].get("cancelled"), 1)

    def test_window_missing_refuses(self) -> None:
        empty = AxSnapshot(app="Practice App", pid=1, windows=())
        _, outcome, _, port, _, _ = self._run([empty], CLICK_SYNC)
        self.assertEqual(outcome["status"], "window_missing")
        self.assertEqual(port.performs, [])

    def test_no_proposal_blocks_the_task(self) -> None:
        snapshot = _snapshot((_element("app:sync-toggle", "0"),))
        _, outcome, _, port, _, _ = self._run([snapshot], None)
        self.assertEqual(outcome["status"], "no_actionable_proposal")
        self.assertEqual(port.performs, [])


if __name__ == "__main__":
    unittest.main()
