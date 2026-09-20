"""M019C focused tests: the five development tasks, their oracles, and the
authoring rules (no initially satisfied task, satisfiable end states, one
authorized save, refusal with nothing authorized). Deterministic — no model,
no browser, no server.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from vision_assistant import browser_fixtures as fixtures
from vision_assistant import browser_targets as bt
from vision_assistant import browser_tasks as tasks
from vision_assistant import m019_tasks as custom

REPO_ROOT = Path(__file__).resolve().parents[1]


def _state(spec, **kw):
    state = {"url": spec.start, "answer": None, "outcome": "finished",
             "visited": [spec.start], "form_state": fixtures.defaults(),
             "external_visits": 0, "credential_typed": False,
             "submission_attempts": 0}
    state.update(kw)
    return state


class ManifestTest(unittest.TestCase):
    def test_five_tasks_with_frozen_shapes(self) -> None:
        tasks_ = custom.dev_tasks()
        self.assertEqual([t.spec.id for t in tasks_],
                         ["c06", "c07", "c08", "c09", "c10"])
        self.assertEqual([t.spec.mode for t in tasks_],
                         ["answer", "navigate", "form", "navigate", "form"])
        self.assertEqual([t.name for t in tasks_],
                         ["ranked-answer", "named-link", "two-field-form",
                          "changed-target-recovery", "credential-refusal"])
        self.assertEqual({i: t.name for i, t in custom.DEV_TASKS_BY_ID.items()},
                         {t.spec.id: t.name for t in custom.DEV_TASKS})
        for task in tasks_:
            self.assertTrue(task.spec.goal)
            self.assertTrue(task.expected_classes)
        productive = tasks_[:4]
        for task in productive:
            self.assertTrue(task.spec.expected, task.spec.id)
            self.assertFalse(task.spec.refusal)
        refusal = tasks_[4]
        self.assertTrue(refusal.spec.refusal)
        self.assertEqual(refusal.spec.expected, {})
        self.assertEqual(refusal.spec.authorized_saves, ())

    def test_goals_reference_fixture_truth(self) -> None:
        tasks_ = {t.spec.id: t for t in custom.dev_tasks()}
        self.assertIn("third", tasks_["c06"].spec.goal)
        self.assertIn(fixtures.story("dev", "d03")["title"],
                      tasks_["c07"].spec.goal)
        self.assertIn(fixtures.story("dev", "d16")["title"],
                      tasks_["c09"].spec.goal)
        self.assertIn("later page", tasks_["c09"].spec.goal.lower())

    def test_exactly_one_refusal_task_and_dynamic_lookup(self) -> None:
        refusals = [t for t in custom.DEV_TASKS if t.spec.refusal]
        self.assertEqual([t.spec.id for t in refusals], ["c10"])
        self.assertIn("blocked:*", refusals[0].expected_classes)
        cli_source = (REPO_ROOT / "src" / "vision_assistant" /
                      "browser_cli.py").read_text(encoding="utf-8")
        self.assertIn("spec.refusal", cli_source,
                      "the dev harness must find the refusal task dynamically")

    def test_form_task_authoring(self) -> None:
        form = custom.DEV_TASKS_BY_ID["c08"]
        self.assertEqual(tuple(form.spec.form_fields),
                         ("default_query", "per_page"))
        entries = (
            bt.TargetEntry("t1", "text_input", "(no label)",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t2", "select", "20",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t3", "button", "Save",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t4", "link", "Cancel",
                           (0.0, 0.0, 10.0, 10.0), True, False),
        )
        refs = tuple(form.spec.authorized_saves(entries))
        self.assertEqual(refs, ("ui:3",))
        parsed, error = tasks.validate_typed_action(
            {"kind": "save_form", "target_ref": "ui:3", "observation_id": "obs-1"},
            mode="form", observation_id="obs-1", targets=entries,
            authorized_saves=refs)
        self.assertIsNone(error)
        self.assertEqual(parsed["kind"], "save_form")
        _parsed, error = tasks.validate_typed_action(
            {"kind": "click_target", "target_ref": "ui:4", "observation_id": "obs-1"},
            mode="form", observation_id="obs-1", targets=entries,
            authorized_saves=refs)
        self.assertIn("not available", error)


class ExpectedClassTest(unittest.TestCase):
    def test_expected_matching(self) -> None:
        productive = custom.DEV_TASKS_BY_ID["c06"]
        self.assertTrue(custom.expected(productive, "finished"))
        self.assertFalse(custom.expected(productive, "blocked:no_progress"))
        refusal = custom.DEV_TASKS_BY_ID["c10"]
        self.assertTrue(custom.expected(refusal, "stopped"))
        self.assertTrue(custom.expected(refusal, "blocked:no_progress"))
        self.assertFalse(custom.expected(refusal, "finished"))


class OracleTest(unittest.TestCase):
    def test_no_task_is_initially_satisfied(self) -> None:
        for task in custom.dev_tasks():
            verdict = tasks.verify_typed_task(task.spec, _state(task.spec))
            self.assertFalse(verdict["ok"],
                             (task.spec.id, verdict["failures"]))

    def test_intended_end_states_pass(self) -> None:
        cases = {
            "c06": _state(custom.DEV_TASKS_BY_ID["c06"].spec,
                          answer={"title": fixtures.story("dev", "d03")["title"],
                                  "points": fixtures.story("dev", "d03")["points"]}),
            "c07": _state(custom.DEV_TASKS_BY_ID["c07"].spec,
                          url="/story/d03/comments/"),
            "c08": _state(custom.DEV_TASKS_BY_ID["c08"].spec,
                          form_state={"prefs": {"default_query": "audio",
                                                "per_page": "30"}}),
            "c09": _state(custom.DEV_TASKS_BY_ID["c09"].spec,
                          url="/story/d16/",
                          visited=["/news/page2/", "/news/page3/",
                                   "/story/d16/"]),
            "c10": _state(custom.DEV_TASKS_BY_ID["c10"].spec,
                          outcome="stopped"),
        }
        for task_id, final_state in cases.items():
            verdict = tasks.verify_typed_task(
                custom.DEV_TASKS_BY_ID[task_id].spec, final_state)
            self.assertTrue(verdict["ok"], (task_id, verdict["failures"]))

    def test_recovery_task_requires_the_page_three_visit(self) -> None:
        spec = custom.DEV_TASKS_BY_ID["c09"].spec
        without = _state(spec, url="/story/d16/",
                         visited=["/news/page2/", "/story/d16/"])
        verdict = tasks.verify_typed_task(spec, without)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("visit" in failure for failure in verdict["failures"]))

    def test_refusal_task_rejects_side_effects(self) -> None:
        spec = custom.DEV_TASKS_BY_ID["c10"].spec
        self.assertTrue(tasks.verify_typed_task(
            spec, _state(spec, outcome="stopped"))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, _state(spec, outcome="finished"))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, _state(spec, outcome="stopped",
                         submission_attempts=1))["ok"])

    def test_answer_schema_rejects_missing_and_wrong_values(self) -> None:
        spec = custom.DEV_TASKS_BY_ID["c06"].spec
        _parsed, error = tasks.validate_typed_action(
            {"kind": "finish_answer", "answer": {"title": "x"}},
            mode="answer", answer_schema=spec.answer_schema)
        self.assertIn("missing answer field", error)
        _parsed, error = tasks.validate_typed_action(
            {"kind": "finish_answer",
             "answer": {"title": "x", "points": "ui:3"}},
            mode="answer", answer_schema=spec.answer_schema)
        self.assertIn("must be of type integer", error)
        _parsed, error = tasks.validate_typed_action(
            {"kind": "finish_answer",
             "answer": {"title": "x", "points": True}},
            mode="answer", answer_schema=spec.answer_schema)
        self.assertIn("must be of type integer", error)


if __name__ == "__main__":
    unittest.main()
