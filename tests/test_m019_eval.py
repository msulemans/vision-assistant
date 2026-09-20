"""M019D focused tests: the frozen 20-task evaluation set.

Deterministic — no model, no browser. Pins the manifest hash, the set
composition (18 productive + 2 refusals), the authoring rules, and the
deterministic freeze checks (intended states pass, mutations rejected, no
initially satisfied task).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from vision_assistant import browser_fixtures as fixtures
from vision_assistant import browser_targets as bt
from vision_assistant import browser_tasks as tasks
from vision_assistant import m019_eval as evaluation
from vision_assistant import m019_tasks as dev

REPO_ROOT = Path(__file__).resolve().parents[1]

FROZEN_SHA256 = ("9d09438da2f4433ac1a3997fab229b937c47dd7e077eda8fe2fa645cde199632")


class FreezeManifestTest(unittest.TestCase):
    def test_manifest_hash_is_pinned(self) -> None:
        self.assertEqual(evaluation.manifest_sha256(), FROZEN_SHA256)

    def test_task_composition(self) -> None:
        tasks_ = evaluation.EVAL_TASKS
        self.assertEqual(len(tasks_), 20)
        self.assertEqual([t.spec.id for t in tasks_],
                         ["e{:02d}".format(i) for i in range(1, 21)])
        productive = [t for t in tasks_ if not t.spec.refusal]
        refusals = [t for t in tasks_ if t.spec.refusal]
        self.assertEqual(len(productive), 18)
        self.assertEqual(len(refusals), 2)
        self.assertEqual([t.spec.id for t in refusals], ["e19", "e20"])
        modes = {}
        for task in tasks_:
            modes[task.spec.mode] = modes.get(task.spec.mode, 0) + 1
        self.assertEqual(modes, {"answer": 5, "navigate": 6, "form": 9})

    def test_ids_are_fresh_against_the_dev_set(self) -> None:
        eval_ids = {t.spec.id for t in evaluation.EVAL_TASKS}
        dev_ids = {t.spec.id for t in dev.DEV_TASKS}
        self.assertEqual(eval_ids & dev_ids, set())
        eval_goals = {t.spec.goal for t in evaluation.EVAL_TASKS}
        dev_goals = {t.spec.goal for t in dev.DEV_TASKS}
        self.assertEqual(eval_goals & dev_goals, set())

    def test_authoring_rules(self) -> None:
        for task in evaluation.EVAL_TASKS:
            if task.spec.refusal:
                self.assertEqual(task.spec.expected, {})
                self.assertEqual(task.spec.authorized_saves, ())
                self.assertIn("blocked:*", task.expected_classes)
            else:
                self.assertTrue(task.spec.expected, task.spec.id)
                self.assertEqual(task.expected_classes, ("finished",))
            if task.spec.mode == "form" and not task.spec.refusal:
                self.assertTrue(task.save_label, task.spec.id)

    def test_answer_tasks_have_schemas(self) -> None:
        for task in evaluation.EVAL_TASKS:
            if task.spec.mode == "answer":
                self.assertTrue(task.spec.answer_schema, task.spec.id)
                self.assertTrue(task.spec.answer_schema["required"])

    def test_form_tasks_authorize_exactly_the_save_button(self) -> None:
        entries = (
            bt.TargetEntry("t1", "text_input", "(no label)",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t2", "button", "Save",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t3", "button", "Reset to defaults",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t4", "link", "Cancel",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t5", "button", "Save draft",
                           (0.0, 0.0, 10.0, 10.0), True, False),
        )
        saves = [t for t in evaluation.EVAL_TASKS
                 if t.spec.mode == "form" and not t.spec.refusal]
        self.assertTrue(saves)
        for task in saves:
            refs = tuple(task.spec.authorized_saves(entries))
            wanted = "ui:5" if task.save_label == "Save draft" else "ui:2"
            self.assertEqual(refs, (wanted,), task.spec.id)


class FreezeChecksTest(unittest.TestCase):
    def test_run_eval_checks_pass(self) -> None:
        checks = evaluation.run_eval_checks()
        self.assertTrue(checks["ok"], checks["problems"])
        self.assertEqual(checks["positive_pass"], 20)
        self.assertEqual(checks["initially_satisfied"], 0)
        self.assertEqual(checks["mutations_total"], checks["mutations_rejected"])
        self.assertEqual(checks["manifest_sha256"], FROZEN_SHA256)

    def test_no_task_is_initially_satisfied(self) -> None:
        for task in evaluation.EVAL_TASKS:
            verdict = tasks.verify_typed_task(task.spec,
                                              evaluation.startup_state(task))
            self.assertFalse(verdict["ok"], task.spec.id)

    def test_answer_facts_match_the_fixtures(self) -> None:
        answers = {task.spec.id: task.spec.expected.get("answer")
                   for task in evaluation.EVAL_TASKS}
        self.assertEqual(answers["e01"],
                         {"title": fixtures.story("dev", "d01")["title"],
                          "points": fixtures.story("dev", "d01")["points"]})
        self.assertEqual(answers["e04"]["title"],
                         fixtures.search("dev", q="robotics")["stories"][0]["title"])
        self.assertEqual(answers["e03"]["title"],
                         fixtures.page_stories("dev", 2)[0]["title"])

    def test_cli_exposes_check_only(self) -> None:
        source = (REPO_ROOT / "src" / "vision_assistant" /
                  "browser_cli.py").read_text(encoding="utf-8")
        self.assertIn("--check-only", source)
        self.assertIn("run_eval_checks", source)


if __name__ == "__main__":
    unittest.main()
