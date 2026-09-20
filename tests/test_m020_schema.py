"""M020 exact-shape contract: per-action schema branches + fallback policy.

The M019D diagnosis (docs/NEXT_EXPERIMENT_OPTIONS.md) showed the union
schema let the decoder append cross-talk fields that strict validation then
refused. These tests pin the exact per-action branches, the validator
mirror, and the schema/fallback instrumentation.
"""

from __future__ import annotations

import types
import unittest

from vision_assistant import browser_agent as agent
from vision_assistant import browser_tasks as tasks

_EXPECTED_REQUIRED = {
    "click_target": {"target_ref", "observation_id"},
    "fill_field": {"target_ref", "text", "observation_id"},
    "select_option": {"target_ref", "option", "observation_id"},
    "set_toggle": {"target_ref", "value", "observation_id"},
    "save_form": {"target_ref", "observation_id"},
    "scroll": {"direction", "amount"},
    "back": set(),
    "wait": set(),
    "finish_answer": {"answer"},
    "finish": set(),
    "stop": set(),
}

_EXPECTED_OPTIONAL = {
    "click_target": {"expected_change"},
    "wait": {"seconds"},
    "stop": {"reason"},
}


def _branches(mode: str):
    return agent.typed_action_schema(mode)["oneOf"]


class ExactBranchTest(unittest.TestCase):
    def test_each_mode_has_one_branch_per_capability_in_order(self) -> None:
        for mode in tasks.TYPED_MODES:
            actions = [branch["properties"]["action"]["enum"][0]
                       for branch in _branches(mode)]
            self.assertEqual(actions, list(tasks.MODE_CAPABILITIES[mode]))

    def test_branch_required_fields_mirror_the_validator_contract(self) -> None:
        for mode in tasks.TYPED_MODES:
            for branch in _branches(mode):
                action = branch["properties"]["action"]["enum"][0]
                required = set(branch["required"]) - {"action"}
                self.assertEqual(required, _EXPECTED_REQUIRED[action], action)
                self.assertEqual(required,
                                 set(tasks._TYPED_KIND_FIELDS[action]),
                                 "drift vs validator: " + action)

    def test_branch_properties_are_exact_and_extras_forbidden(self) -> None:
        for mode in tasks.TYPED_MODES:
            for branch in _branches(mode):
                action = branch["properties"]["action"]["enum"][0]
                self.assertEqual(branch["type"], "object")
                self.assertIs(branch["additionalProperties"], False)
                self.assertEqual(
                    set(branch["properties"]),
                    {"action"} | _EXPECTED_REQUIRED[action]
                    | _EXPECTED_OPTIONAL.get(action, set()), action)
                self.assertIn("action", branch["required"])

    def test_cross_talk_fields_from_the_measured_failure_are_gone(self) -> None:
        banned = {
            "fill_field": {"option", "value", "reason", "amount",
                           "expected_change", "direction", "seconds"},
            "select_option": {"text", "value", "reason", "amount",
                              "expected_change", "direction", "seconds"},
            "set_toggle": {"text", "option", "reason", "amount",
                           "expected_change", "direction", "seconds"},
            "save_form": {"text", "option", "value", "reason", "amount",
                          "expected_change", "direction", "seconds"},
        }
        for mode in tasks.TYPED_MODES:
            for branch in _branches(mode):
                action = branch["properties"]["action"]["enum"][0]
                for field in banned.get(action, ()):
                    self.assertNotIn(field, branch["properties"],
                                     "{} in {} branch".format(field, action))

    def test_wire_key_is_action_and_kind_is_never_a_property(self) -> None:
        for mode in tasks.TYPED_MODES:
            for branch in _branches(mode):
                action = branch["properties"]["action"]["enum"][0]
                self.assertEqual(branch["properties"]["action"]["enum"],
                                 [action])
                self.assertNotIn("kind", branch["properties"])
                self.assertNotIn("x", branch["properties"])
                self.assertNotIn("y", branch["properties"])

    def test_scroll_enum_and_field_types_mirror_the_validator(self) -> None:
        modes = {branch["properties"]["action"]["enum"][0]: branch
                 for mode in tasks.TYPED_MODES for branch in _branches(mode)}
        self.assertEqual(modes["scroll"]["properties"]["direction"]["enum"],
                         list(tasks.SCROLL_DIRECTIONS))
        self.assertEqual(modes["scroll"]["properties"]["amount"]["type"],
                         "integer")
        self.assertEqual(modes["set_toggle"]["properties"]["value"]["type"],
                         "boolean")
        self.assertEqual(modes["fill_field"]["properties"]["text"]["type"],
                         "string")
        self.assertEqual(modes["wait"]["properties"]["seconds"]["type"],
                         "number")
        self.assertEqual(
            modes["finish_answer"]["properties"]["answer"]["type"], "object")

    def test_optional_fields_only_where_the_validator_allows_them(self) -> None:
        for mode in tasks.TYPED_MODES:
            for branch in _branches(mode):
                action = branch["properties"]["action"]["enum"][0]
                optional = (set(branch["properties"]) - {"action"}
                            - set(branch["required"]))
                self.assertEqual(optional,
                                 _EXPECTED_OPTIONAL.get(action, set()), action)


class _FakeAdapter:
    def __init__(self, *, fail_with_schema: bool = False) -> None:
        self.calls: list = []
        self.fail_with_schema = fail_with_schema

    def predict_image(self, png_bytes, question, *, json_schema=None):
        self.calls.append({"json_schema": json_schema})
        if json_schema is not None and self.fail_with_schema:
            raise RuntimeError("schema request rejected")
        text = '{"action":"back"}'
        answer = types.SimpleNamespace(visible=[text], inferred=[],
                                       unknown=[])
        return answer, {"chars": len(text)}


class ProposerFallbackTest(unittest.TestCase):
    def test_schema_success_records_schema_event(self) -> None:
        adapter = _FakeAdapter()
        events: list = []
        proposer = agent.model_proposer(adapter, schema={"marker": 1},
                                        schema_events=events)
        action, _meta = proposer(b"png", "prompt")
        self.assertEqual(action, {"action": "back"})
        self.assertEqual(events, ["schema"])
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.calls[0]["json_schema"], {"marker": 1})

    def test_fallback_records_event_and_retries_unconstrained(self) -> None:
        adapter = _FakeAdapter(fail_with_schema=True)
        events: list = []
        proposer = agent.model_proposer(adapter, schema={"marker": 1},
                                        schema_events=events)
        action, _meta = proposer(b"png", "prompt")
        self.assertEqual(action, {"action": "back"})
        self.assertEqual(events, ["fallback"])
        self.assertEqual(len(adapter.calls), 2)
        self.assertIsNone(adapter.calls[1]["json_schema"])

    def test_require_schema_is_fatal_without_unconstrained_retry(self) -> None:
        adapter = _FakeAdapter(fail_with_schema=True)
        events: list = []
        proposer = agent.model_proposer(adapter, schema={"marker": 1},
                                        schema_events=events,
                                        require_schema=True)
        with self.assertRaises(RuntimeError):
            proposer(b"png", "prompt")
        self.assertEqual(events, ["fallback"])
        self.assertEqual(len(adapter.calls), 1)

    def test_schema_events_are_optional(self) -> None:
        adapter = _FakeAdapter()
        proposer = agent.model_proposer(adapter, schema={"marker": 1})
        action, _meta = proposer(b"png", "prompt")
        self.assertEqual(action, {"action": "back"})

    def test_typed_schema_reaches_the_adapter(self) -> None:
        adapter = _FakeAdapter()
        proposer = agent.model_proposer(
            adapter, schema=agent.typed_action_schema("form"))
        proposer(b"png", "prompt")
        self.assertEqual(adapter.calls[0]["json_schema"],
                         agent.typed_action_schema("form"))


if __name__ == "__main__":
    unittest.main()
