"""M019B focused tests: scenario metadata, prompt parsing, script validity.

All deterministic — no browser, no server, no model. The live scripted gate
itself is executed by ``browser_cli m019-scripted``; these tests prove that
every scripted step is structurally valid for its declared mode, that the
fixture pages contain the labels the finders rely on, and that the oracles
are satisfiable by the intended end states.
"""

from __future__ import annotations

import unittest
from unittest import mock

from vision_assistant import browser_agent as agent
from vision_assistant import browser_fixtures as fixtures
from vision_assistant import browser_targets as bt
from vision_assistant import browser_tasks as tasks
from vision_assistant import m019_scripted as scripted
from vision_assistant.browser_session import TargetList

OBS = "obs-7"


def _entries(*specs):
    entries = []
    for index, (role, label) in enumerate(specs, start=1):
        entries.append(bt.TargetEntry("t{}".format(index), role, label,
                                      (10.0, float(index) * 30.0, 200.0, 24.0),
                                      True, False))
    return tuple(entries)


def _prompt_for(scenario, entries) -> str:
    block = bt.render_typed_target_block(entries, 1280, 720, 2560, 1440, 2.0)
    return agent.build_typed_prompt(
        scenario.spec.goal, scenario.spec.mode, 1280, 720, 1280, 720, OBS,
        block, [])


def _proposal_from(action: dict) -> dict:
    """Mirror the agent's raw-action → proposal translation."""

    proposal = {"kind": action.get("action")}
    for key in ("target_ref", "observation_id", "text", "option", "value",
                "answer", "reason", "direction", "amount", "seconds",
                "expected_change"):
        if key in action:
            proposal[key] = action[key]
    return proposal


def _validate(scenario, entries, action):
    authorized = ()
    if callable(scenario.spec.authorized_saves):
        authorized = tuple(scenario.spec.authorized_saves(entries))
    else:
        authorized = tuple(scenario.spec.authorized_saves)
    return tasks.validate_typed_action(
        _proposal_from(action), mode=scenario.spec.mode, observation_id=OBS,
        targets=entries, authorized_saves=authorized,
        answer_schema=getattr(scenario.spec, "answer_schema", None))


class ScenarioMetadataTest(unittest.TestCase):
    def test_six_scenarios_with_frozen_shapes(self) -> None:
        scenarios = scripted.scenarios()
        self.assertEqual(
            [s.name for s in scenarios],
            ["answer", "navigate", "form", "moving-target",
             "credential-refusal", "external-submit-refusal"])
        productive = scenarios[:4]
        refusals = scenarios[4:]
        for scenario in productive:
            self.assertEqual(scenario.expect_outcome, ("finished",))
            self.assertTrue(scenario.expect_oracle_ok)
            self.assertTrue(scenario.spec.expected)
            self.assertFalse(scenario.spec.refusal)
        for scenario in refusals:
            self.assertEqual(scenario.expect_outcome, ("stopped",))
            self.assertTrue(scenario.spec.refusal)
            self.assertTrue(scenario.required_refusals)
            self.assertFalse(scenario.spec.expected)
        for scenario in scenarios:
            self.assertTrue(scenario.script)
            for step in scenario.script:
                self.assertTrue(callable(step), scenario.name)
            self.assertIn(scenario.spec.mode, tasks.TYPED_MODES)

    def test_intended_end_states_satisfy_the_oracles(self) -> None:
        def state(**kw):
            base = {"url": "", "answer": None, "outcome": "finished",
                    "visited": [], "external_visits": 0, "credential_typed": False,
                    "submission_attempts": 0}
            base.update(kw)
            return base

        checks = (
            ("answer", state(answer={"title": fixtures.story("dev", "d01")["title"],
                                     "code": fixtures.story_code("dev", "d01")})),
            ("navigate", state(url="/story/d03/")),
            ("form", state(form_state={"prefs": {"per_page": "30"}})),
            ("moving-target", state(url="/story/d05/")),
            ("credential-refusal", state(outcome="stopped")),
            ("external-submit-refusal", state(outcome="stopped")),
        )
        by_name = {s.name: s for s in scripted.scenarios()}
        for name, final_state in checks:
            verdict = tasks.verify_typed_task(by_name[name].spec, final_state)
            self.assertTrue(verdict["ok"], (name, verdict["failures"]))


class PromptParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = _entries(("link", "Story one"), ("button", "Save"),
                                ("select", "20"))
        self.prompt = _prompt_for(scripted.scenarios()[0], self.entries)

    def test_observation_id_round_trips(self) -> None:
        self.assertEqual(scripted.observation_id_from(self.prompt), OBS)

    def test_find_target_and_ref(self) -> None:
        entry = scripted.find_target(self.prompt, role="button", label="Save")
        self.assertEqual(entry["target_ref"], "ui:2")
        self.assertEqual(
            scripted.find_ref(self.prompt, role="select", label="20"), "ui:3")
        self.assertEqual(
            scripted.find_ref(self.prompt, role="link", contains="Story"), "ui:1")
        self.assertEqual(scripted.find_ref(self.prompt, label="nope"), "")
        self.assertIsNone(scripted.find_target(self.prompt, role="textarea"))

    def test_unescaped_prompt_lines_do_not_break_parsing(self) -> None:
        good_lines = [line for line in self.prompt.splitlines()
                      if line.strip().startswith("{")]
        self.assertTrue(good_lines)
        self.assertEqual(len(scripted.target_entries(self.prompt)), 3)


class FixtureLabelTest(unittest.TestCase):
    """The labels the scenario finders rely on must exist in the fixtures."""

    def test_form_page_labels(self) -> None:
        page = fixtures.render_prefs_page("dev", fixtures.defaults())
        self.assertIn('name="per_page"', page)
        self.assertIn(">Save<", page)
        self.assertIn(">20<", page)

    def test_login_and_checkout_labels(self) -> None:
        login = fixtures.render_login_page("dev")
        self.assertIn("Sign in", login)
        self.assertIn('type="password"', login)
        checkout = fixtures.render_checkout_page("dev")
        self.assertIn("Send receipt externally", checkout)

    def test_layout_and_story_targets(self) -> None:
        self.assertIn("rank-5", fixtures.render_layout_page("dev"))
        self.assertTrue(fixtures.story("dev", "d03")["title"])
        self.assertTrue(fixtures.story_code("dev", "d01").startswith("SC-"))

    def test_no_story_title_false_positives_against_submit_markers(self) -> None:
        for instance in fixtures.instances():
            for item in fixtures.stories(instance):
                info = bt.classify_control("link", item["title"])
                self.assertFalse(
                    info["submit_like"],
                    (instance, item["sid"], item["title"]))
                self.assertFalse(info["credential"],
                                 (instance, item["sid"], item["title"]))

    def test_checkout_button_is_submit_like(self) -> None:
        info = bt.classify_control("button", "Send receipt externally")
        self.assertTrue(info["submit_like"])
        self.assertFalse(info["credential"])
        self.assertTrue(
            bt.classify_control("button", "Sign in")["submit_like"])


class ScriptValidityTest(unittest.TestCase):
    """Every scripted step is checked against the real M019 validator."""

    def _run_script(self, scenario, entries, expect_errors):
        prompt = _prompt_for(scenario, entries)
        with mock.patch.object(scripted.time, "sleep", lambda _s: None):
            actions = [step(prompt) for step in scenario.script]
        results = []
        for index, action in enumerate(actions):
            parsed, error = _validate(scenario, entries, action)
            results.append((action["action"], parsed, error))
        return results

    def test_answer_script(self) -> None:
        title = fixtures.story("dev", "d01")["title"]
        scenario = scripted.scenarios()[0]
        entries = _entries(("link", title))
        results = self._run_script(scenario, entries, None)
        self.assertEqual(results[0][0], "click_target")
        self.assertIn("not available", results[0][2])
        self.assertEqual(results[1][0], "finish_answer")
        self.assertIsNone(results[1][2])

    def test_navigate_script(self) -> None:
        title = fixtures.story("dev", "d03")["title"]
        scenario = scripted.scenarios()[1]
        entries = _entries(("link", title), ("link", "page2"))
        results = self._run_script(scenario, entries, None)
        self.assertIsNone(results[0][2])
        self.assertEqual(results[0][1]["target_ref"], "ui:1")

    def test_form_script(self) -> None:
        scenario = scripted.scenarios()[2]
        entries = _entries(("select", "20"), ("button", "Save"))
        results = self._run_script(scenario, entries, None)
        self.assertEqual(results[0][0], "select_option")
        self.assertIsNone(results[0][2])
        self.assertEqual(results[0][1]["option"], "30")
        self.assertEqual(results[1][0], "save_form")
        self.assertIsNone(results[1][2])
        self.assertEqual(results[1][1]["target_ref"], "ui:2")

    def test_moved_script(self) -> None:
        scenario = scripted.scenarios()[3]
        entries = _entries(("link", "Continue to rank-5 story"))
        results = self._run_script(scenario, entries, None)
        self.assertEqual(results[0][0], "click_target")
        self.assertIn("stale observation", results[0][2])
        self.assertEqual(results[0][1], None)
        self.assertIsNone(results[1][2])
        self.assertEqual(results[1][1]["target_ref"], "ui:1")

    def test_credential_script_is_denied(self) -> None:
        scenario = scripted.scenarios()[4]
        entries = _entries(("text_input", "(no label)"), ("button", "Sign in"))
        results = self._run_script(scenario, entries, None)
        self.assertEqual(results[0][0], "save_form")
        self.assertIn("refused_unauthorized_save", results[0][2])
        self.assertEqual(results[1][0], "stop")

    def test_external_submit_script_is_denied(self) -> None:
        scenario = scripted.scenarios()[5]
        entries = _entries(("text_input", "(no label)"),
                           ("button", "Send receipt externally"))
        results = self._run_script(scenario, entries, None)
        self.assertEqual(results[0][0], "save_form")
        self.assertIn("refused_unauthorized_save", results[0][2])
        self.assertEqual(results[1][0], "stop")


if __name__ == "__main__":
    unittest.main()
