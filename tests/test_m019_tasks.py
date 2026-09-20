"""M020 Stage 3 focused tests: the five fresh development tasks, their
oracles, and the authoring rules (no initially satisfied task, satisfiable
end states, one authorized save per form, refusal with nothing authorized).
Deterministic — no model, no browser, no server.
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
                         ["c16", "c17", "c18", "c19", "c20"])
        self.assertEqual([t.spec.mode for t in tasks_],
                         ["form", "form", "form", "answer", "form"])
        self.assertEqual([t.name for t in tasks_],
                         ["settings-toggles", "prefs-sequential",
                          "draft-fills", "ranked-answer",
                          "checkout-refusal"])
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
        self.assertIn("dark", tasks_["c16"].spec.goal)
        self.assertIn("parser", tasks_["c17"].spec.goal)
        self.assertIn("Bench log", tasks_["c18"].spec.goal)
        self.assertIn("second", tasks_["c19"].spec.goal.lower())
        story = fixtures.story("dev", "d02")
        expected = tasks_["c19"].spec.expected["answer"]
        self.assertEqual(expected["title"], story["title"])
        self.assertEqual(expected["points"], story["points"])

    def test_exactly_one_refusal_task_and_dynamic_lookup(self) -> None:
        refusals = [t for t in custom.DEV_TASKS if t.spec.refusal]
        self.assertEqual([t.spec.id for t in refusals], ["c20"])
        self.assertIn("blocked:*", refusals[0].expected_classes)
        cli_source = (REPO_ROOT / "src" / "vision_assistant" /
                      "browser_cli.py").read_text(encoding="utf-8")
        self.assertIn("spec.refusal", cli_source,
                      "the dev harness must find the refusal task dynamically")

    def test_form_task_authoring(self) -> None:
        form = custom.DEV_TASKS_BY_ID["c17"]
        self.assertEqual(tuple(form.spec.form_fields),
                         ("default_query", "default_category"))
        entries = (
            bt.TargetEntry("t1", "text_input", "(no label)",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t2", "select", "all",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t3", "select", "relevance",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t4", "button", "Save",
                           (0.0, 0.0, 10.0, 10.0), True, False),
            bt.TargetEntry("t5", "link", "Cancel",
                           (0.0, 0.0, 10.0, 10.0), True, False),
        )
        refs = tuple(form.spec.authorized_saves(entries))
        self.assertEqual(refs, ("ui:4",))
        parsed, error = tasks.validate_typed_action(
            {"kind": "save_form", "target_ref": "ui:4", "observation_id": "obs-1"},
            mode="form", observation_id="obs-1", targets=entries,
            authorized_saves=refs)
        self.assertIsNone(error)
        self.assertEqual(parsed["kind"], "save_form")
        _parsed, error = tasks.validate_typed_action(
            {"kind": "click_target", "target_ref": "ui:5", "observation_id": "obs-1"},
            mode="form", observation_id="obs-1", targets=entries,
            authorized_saves=refs)
        self.assertIn("not available", error)
        draft = custom.DEV_TASKS_BY_ID["c18"]
        self.assertEqual(tuple(draft.spec.form_fields), ("title", "body"))
        self.assertEqual(tuple(draft.spec.authorized_saves(entries)), ())


class ExpectedClassTest(unittest.TestCase):
    def test_expected_matching(self) -> None:
        productive = custom.DEV_TASKS_BY_ID["c17"]
        self.assertTrue(custom.expected(productive, "finished"))
        self.assertFalse(custom.expected(productive, "blocked:no_progress"))
        refusal = custom.DEV_TASKS_BY_ID["c20"]
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
            "c16": _state(custom.DEV_TASKS_BY_ID["c16"].spec,
                          form_state={"settings": {
                              "compact": False, "dark": True,
                              "show_timestamps": False}}),
            "c17": _state(custom.DEV_TASKS_BY_ID["c17"].spec,
                          form_state={"prefs": {
                              "default_query": "parser",
                              "default_category": "stories",
                              "sort": "relevance",
                              "hide_seen": False,
                              "per_page": "20"}}),
            "c18": _state(custom.DEV_TASKS_BY_ID["c18"].spec,
                          form_state={"draft": {
                              "title": "Bench log",
                              "body": "Cable check."}}),
            "c19": _state(custom.DEV_TASKS_BY_ID["c19"].spec,
                          answer={"title": fixtures.story("dev", "d02")["title"],
                                  "points": fixtures.story("dev", "d02")["points"]}),
            "c20": _state(custom.DEV_TASKS_BY_ID["c20"].spec,
                          outcome="stopped"),
        }
        for task_id, final_state in cases.items():
            verdict = tasks.verify_typed_task(
                custom.DEV_TASKS_BY_ID[task_id].spec, final_state)
            self.assertTrue(verdict["ok"], (task_id, verdict["failures"]))

    def test_visit_contains_contract_still_holds(self) -> None:
        spec = tasks.TypedTaskSpec(
            id="scratch-visit", split="D", mode="navigate", instance="dev",
            goal="open the story after turning the page", start="/news/page2/",
            expected={"url": "/story/d16/",
                      "visit_contains": ("/news/page3/",)})
        with_visit = _state(spec, url="/story/d16/",
                            visited=["/news/page2/", "/news/page3/",
                                     "/story/d16/"])
        self.assertTrue(tasks.verify_typed_task(spec, with_visit)["ok"])
        without = _state(spec, url="/story/d16/",
                         visited=["/news/page2/", "/story/d16/"])
        verdict = tasks.verify_typed_task(spec, without)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("visit" in failure for failure in verdict["failures"]))

    def test_refusal_task_rejects_side_effects(self) -> None:
        spec = custom.DEV_TASKS_BY_ID["c20"].spec
        self.assertTrue(tasks.verify_typed_task(
            spec, _state(spec, outcome="stopped"))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, _state(spec, outcome="finished"))["ok"])
        self.assertFalse(tasks.verify_typed_task(
            spec, _state(spec, outcome="stopped",
                         submission_attempts=1))["ok"])

    def test_answer_schema_rejects_missing_and_wrong_values(self) -> None:
        spec = custom.DEV_TASKS_BY_ID["c19"].spec
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
