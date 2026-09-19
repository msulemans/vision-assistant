from __future__ import annotations

import unittest

from vision_assistant.conversation_eval import TASKS, Check, check_passes


class CheckPassesTest(unittest.TestCase):
    def test_contains_all(self) -> None:
        ok, _ = check_passes(
            Check(kind="contains_all", needles=("87", "charging")),
            ("The power is at 87% and the device is charging.",),
        )
        self.assertTrue(ok)
        ok, reason = check_passes(
            Check(kind="contains_all", needles=("87",)), ("No percentage is visible.",)
        )
        self.assertFalse(ok)
        self.assertIn("missing", reason)

    def test_corrects_passes_when_wrong_premise_is_negated(self) -> None:
        ok, _ = check_passes(
            Check(kind="corrects", wrong="12", right_terms=("87",)),
            ("No, the screen shows 87%, not 12%.",),
        )
        self.assertTrue(ok)

    def test_corrects_fails_on_affirmed_wrong_premise(self) -> None:
        ok, reason = check_passes(
            Check(kind="corrects", wrong="12", right_terms=("87",)),
            ("Yes: 12% is shown as the overall figure of 87.",),
        )
        self.assertFalse(ok)
        self.assertIn("affirmed", reason)

    def test_corrects_requires_the_true_value(self) -> None:
        ok, reason = check_passes(
            Check(kind="corrects", wrong="12", right_terms=("87",)), ("That is incorrect.",)
        )
        self.assertFalse(ok)
        self.assertIn("true value", reason)

    def test_empty_answer_fails(self) -> None:
        ok, reason = check_passes(Check(kind="contains_all", needles=("x",)), ())
        self.assertFalse(ok)
        self.assertEqual(reason, "empty answer")


class TaskSetTest(unittest.TestCase):
    def test_task_ids_unique_and_kinds_frozen(self) -> None:
        ids = [task.task_id for task in TASKS]
        self.assertEqual(len(ids), len(set(ids)))
        kinds = [task.kind for task in TASKS]
        self.assertEqual(kinds.count("reference"), 3)
        self.assertEqual(kinds.count("correction"), 3)

    def test_tasks_are_frozen_to_held_out_cases(self) -> None:
        for task in TASKS:
            with self.subTest(task=task.task_id):
                self.assertTrue(task.case_id.startswith("m004-"))
                self.assertTrue(task.follow_up)


if __name__ == "__main__":
    unittest.main()
