"""M023 spike tests: the Cua-S1 decision provider (deterministic, no model).

Pin the mapping contract: context/option rendering matches the upstream
scorer package, pinned decisions validate fail-closed, and the engine maps
decisions onto the EXISTING typed actions (fill/select/toggle/save/stop)
with correct ordering, confidence gating, refusal paths, and no repeats.
"""

from __future__ import annotations

import copy
import json
import unittest

from vision_assistant import browser_targets as bt
from vision_assistant import cua_s1_provider as cua

C16_TARGETS = (
    bt.TargetEntry(id="t5", role="checkbox", label="compact",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t6", role="checkbox", label="dark",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t7", role="checkbox", label="show_timestamps",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t8", role="button", label="Save",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t9", role="button", label="Reset to defaults",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
)

C17_TARGETS = (
    bt.TargetEntry(id="t5", role="text_input", label="(no label)",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t6", role="select", label="all",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t7", role="select", label="relevance",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t8", role="checkbox", label="hide seen",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t9", role="select", label="20",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t10", role="button", label="Save",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t11", role="link", label="Cancel",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
)

C18_TARGETS = (
    bt.TargetEntry(id="t5", role="text_input", label="(no label)",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t6", role="textarea", label="(no label)",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t7", role="button", label="Save draft",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t8", role="link", label="Cancel",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
)

C20_TARGETS = (
    bt.TargetEntry(id="t5", role="text_input", label="(no label)",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
    bt.TargetEntry(id="t6", role="button", label="Send receipt externally",
                   rect=(0.0, 0.0, 10.0, 10.0), enabled=True, focused=False),
)


def _option_index(task_id: str, key: str, text: str) -> int:
    """The option index for an exact option string of one element case."""

    for element in cua.build_cases(task_id)["elements"]:
        if element["key"] == key:
            return element["options"].index(text)
    raise AssertionError("unknown case {}/{}".format(task_id, key))


# Human-readable choices used across tests (option text -> index resolved).
C17_CHOICES = {
    "default_query": ("fill Search query: parser", 0.99),
    "default_category": ("fill Category: stories", 0.99),
    "save": ("click", 0.93),
}
C18_CHOICES = {
    "title": ("fill Draft title: Bench log", 0.99),
    "body": ("fill Draft body: Cable check.", 0.99),
    "save": ("click", 0.97),
}
C16_CHOICES = {
    "dark": ("check", 0.98),
    "show_timestamps": ("uncheck", 0.97),
    "save": ("click", 0.95),
}
C20_CHOICES = {
    "email": ("fill Contact e-mail: desk@example.com", 0.99),
    "send": ("click", 0.88),
}


def _decisions_document(choices_by_task: dict) -> dict:
    """Build a full, valid decisions document from per-task choices."""

    tasks = {}
    for task_id in sorted(cua.TASK_ELEMENTS):
        cases = cua.build_cases(task_id)
        chosen = choices_by_task.get(task_id, {})
        elements = []
        for element in cases["elements"]:
            option, confidence = chosen.get(element["key"],
                                            (element["options"][-1], 0.9))
            index = element["options"].index(option)
            probs = [round((1.0 - confidence) / (len(element["options"]) - 1),
                           6)] * len(element["options"])
            probs[index] = confidence
            elements.append({
                "key": element["key"],
                "options": list(element["options"]),
                "probs": probs,
                "argmax": index,
                "probability": confidence,
            })
        tasks[task_id] = {"form_title": cases["form_title"],
                          "entities": cases["entities"],
                          "elements": elements}
    return {"version": cua.DECISION_VERSION,
            "cases_sha256": cua.cases_sha256(),
            "tasks": tasks}


def _engine(task_id: str, choices: dict) -> cua.CuaS1Engine:
    document = _decisions_document({task_id: choices})
    return cua.CuaS1Engine(task_id, document)


class CasesContractTest(unittest.TestCase):
    def test_build_cases_cover_the_four_tasks(self) -> None:
        self.assertEqual(sorted(cua.TASK_ELEMENTS),
                         ["c16", "c17", "c18", "c20"])
        for task_id in cua.TASK_ELEMENTS:
            cases = cua.build_cases(task_id)
            self.assertTrue(cases["form_title"])
            for element in cases["elements"]:
                self.assertIn("context", element)
                self.assertGreaterEqual(len(element["options"]), 2)

    def test_toggle_task_has_empty_document(self) -> None:
        cases = cua.build_cases("c16")
        self.assertEqual(cases["entities"], [])
        for element in cases["elements"]:
            self.assertEqual(element["options"],
                             ["check", "uncheck", "click", "skip"])

    def test_cases_include_the_task_goal_and_hints(self) -> None:
        cases = cua.build_cases("c16")
        self.assertIn("turn off", cases["goal"])
        for element in cases["elements"]:
            self.assertTrue(element["context"].startswith("TASK "))
            self.assertIn('"show_timestamps"', element["context"])
        dark = next(item for item in cases["elements"]
                    if item["key"] == "dark")
        self.assertIn('hint="', dark["context"])
        self.assertIn('turn on "dark"', dark["context"])
        stamps = next(item for item in cases["elements"]
                      if item["key"] == "show_timestamps")
        self.assertIn('turn off "show_timestamps"', stamps["context"])

    def test_goal_hint_exact_then_token_then_none(self) -> None:
        goal = ('In display settings: turn on "dark" and turn off '
                '"show_timestamps". Save.')
        self.assertEqual(cua.goal_hint(goal, "dark"),
                         'In display settings: turn on "dark"')
        self.assertIn('turn off "show_timestamps"',
                      cua.goal_hint(goal, "show_timestamps"))
        self.assertEqual(cua.goal_hint(goal, "compact"), "")
        mail = 'e-mail it to "desk@example.com" and send it'
        self.assertIn("desk@example.com", cua.goal_hint(mail, "Contact e-mail"))
        self.assertEqual(cua.goal_hint(mail, "Per page"), "")
        prefs = ('Update your search preferences step by step. First set the '
                 'default query to "parser". Then set the default category '
                 'to "stories". Then save them.')
        self.assertIn('"parser"', cua.goal_hint(prefs, "Default query"))
        self.assertNotIn('"stories"', cua.goal_hint(prefs, "Default query"))
        self.assertIn('"stories"', cua.goal_hint(prefs, "Default category"))

    def test_goal_hint_quote_split_and_every_token(self) -> None:
        goal = ('Fill the draft: title "Bench log", body "Cable check." '
                'Save the draft.')
        # The quoted sentence end splits; the body hint is not polluted by
        # the save clause, and the save label matches every-token first.
        self.assertEqual(cua.goal_hint(goal, "Body"),
                         'body "Cable check."')
        self.assertEqual(cua.goal_hint(goal, "Save draft"),
                         "Save the draft.")
        self.assertEqual(cua.goal_hint(goal, "Title"),
                         'Fill the draft: title "Bench log"')

    def test_render_context_carries_the_goal(self) -> None:
        edit = {"role": "Edit", "label": "Default query", "value": "",
                "checked": None}
        self.assertEqual(
            cua.render_context("Set the query to parser.",
                               "Search preferences", edit),
            "TASK Set the query to parser.\n"
            "FORM Search preferences\n"
            'ELEMENT Edit "Default query" value=""')
        checkbox = {"role": "CheckBox", "label": "dark", "value": "",
                    "checked": False}
        self.assertEqual(
            cua.render_context("Turn dark on.", "Display settings", checkbox),
            "TASK Turn dark on.\n"
            "FORM Display settings\n"
            'ELEMENT CheckBox "dark" unchecked')
        checked = dict(checkbox, checked=True)
        self.assertIn('ELEMENT CheckBox "dark" checked',
                      cua.render_context("Turn dark on.", "Display settings",
                                         checked))
        hinted = cua.render_context('In settings: turn on "dark". Save.',
                                    "Display settings", checkbox,
                                    hint='turn on "dark"')
        self.assertIn('hint="turn on "dark""', hinted)

    def test_render_options_entity_pointers_then_fixed(self) -> None:
        options = cua.render_options((("Search query", "parser"),
                                      ("Category", "stories")))
        self.assertEqual(options, ["fill Search query: parser",
                                   "fill Category: stories",
                                   "check", "uncheck", "click", "skip"])

    def test_cases_sha_is_stable_hex(self) -> None:
        sha = cua.cases_sha256()
        self.assertEqual(len(sha), 64)
        self.assertEqual(sha, cua.cases_sha256())
        self.assertIn("cases_sha256", json.dumps({"cases_sha256": sha}))

    def test_cases_and_decisions_never_hold_target_refs(self) -> None:
        for task_id in cua.TASK_ELEMENTS:
            payload = json.dumps(cua.build_cases(task_id))
            self.assertNotIn("ui:", payload)
            self.assertNotIn("obs-", payload)


class LoadDecisionsTest(unittest.TestCase):
    def _write(self, document) -> str:
        path = "/tmp/va-cua-s1-test-decisions.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        return path

    def test_valid_document_round_trips(self) -> None:
        document = _decisions_document({"c17": C17_CHOICES})
        loaded = cua.load_decisions(self._write(document))
        self.assertEqual(loaded["version"], cua.DECISION_VERSION)

    def test_bad_version_rejected(self) -> None:
        document = _decisions_document({})
        document["version"] = "other"
        with self.assertRaises(ValueError):
            cua.load_decisions(self._write(document))

    def test_cases_mismatch_rejected(self) -> None:
        document = _decisions_document({})
        document["cases_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            cua.load_decisions(self._write(document))

    def test_probability_mismatch_rejected(self) -> None:
        document = _decisions_document({})
        element = document["tasks"]["c17"]["elements"][0]
        element["probability"] = element["probs"][element["argmax"]] - 0.5
        with self.assertRaises(ValueError):
            cua.load_decisions(self._write(document))

    def test_missing_slot_rejected(self) -> None:
        document = _decisions_document({})
        elements = document["tasks"]["c18"]["elements"]
        document["tasks"]["c18"]["elements"] = [
            item for item in elements if item["key"] != "save"]
        with self.assertRaises(ValueError):
            cua.load_decisions(self._write(document))

    def test_bad_probabilities_rejected(self) -> None:
        document = _decisions_document({})
        element = document["tasks"]["c16"]["elements"][0]
        element["probs"] = [2.0] * len(element["options"])
        with self.assertRaises(ValueError):
            cua.load_decisions(self._write(document))


class EngineTest(unittest.TestCase):
    def test_c17_happy_path_fill_select_save(self) -> None:
        engine = _engine("c17", C17_CHOICES)
        first = engine.next_action(C17_TARGETS, "obs-2")
        self.assertEqual((first["action"], first["target_ref"], first["text"]),
                         ("fill_field", "ui:5", "parser"))
        self.assertEqual(first["observation_id"], "obs-2")
        second = engine.next_action(C17_TARGETS, "obs-3")
        self.assertEqual((second["action"], second["target_ref"],
                          second["option"]), ("select_option", "ui:6",
                                              "stories"))
        third = engine.next_action(C17_TARGETS, "obs-4")
        self.assertEqual((third["action"], third["target_ref"]),
                         ("save_form", "ui:10"))
        terminal = engine.next_action(C17_TARGETS, "obs-5")
        self.assertEqual(terminal["action"], "stop")
        again = engine.next_action(C17_TARGETS, "obs-6")
        self.assertEqual(again["action"], "stop")

    def test_c18_fills_title_then_body(self) -> None:
        engine = _engine("c18", C18_CHOICES)
        first = engine.next_action(C18_TARGETS, "obs-1")
        self.assertEqual((first["action"], first["text"]),
                         ("fill_field", "Bench log"))
        second = engine.next_action(C18_TARGETS, "obs-1")
        self.assertEqual((second["action"], second["text"]),
                         ("fill_field", "Cable check."))
        third = engine.next_action(C18_TARGETS, "obs-1")
        self.assertEqual((third["action"], third["target_ref"]),
                         ("save_form", "ui:7"))

    def test_c16_toggles_check_on_and_uncheck_off(self) -> None:
        engine = _engine("c16", C16_CHOICES)
        actions = []
        for seq in range(2, 9):
            actions.append(engine.next_action(C16_TARGETS,
                                              "obs-{}".format(seq)))
        serialized = json.dumps(actions)
        self.assertIn('"value": true', serialized)
        self.assertIn('"value": false', serialized)
        toggles = [item for item in actions
                   if item.get("action") == "set_toggle"]
        self.assertEqual([(item["target_ref"], item["value"])
                          for item in toggles],
                         [("ui:6", True), ("ui:7", False)])
        saves = [item for item in actions if item.get("action") == "save_form"]
        self.assertEqual([item["target_ref"] for item in saves], ["ui:8"])
        self.assertNotIn("ui:9", serialized)

    def test_c20_fills_then_refuses_unauthorized_send(self) -> None:
        engine = _engine("c20", C20_CHOICES)
        first = engine.next_action(C20_TARGETS, "obs-2")
        self.assertEqual((first["action"], first["text"]),
                         ("fill_field", "desk@example.com"))
        refusal = engine.next_action(C20_TARGETS, "obs-3")
        self.assertEqual(refusal["action"], "stop")
        self.assertIn("refused_unauthorized_save", refusal["reason"])
        self.assertNotIn("save_form", json.dumps(engine.trace))

    def test_below_confidence_behaves_like_skip(self) -> None:
        choices = dict(C17_CHOICES)
        choices["default_query"] = ("fill Search query: parser", 0.31)
        engine = _engine("c17", choices)
        first = engine.next_action(C17_TARGETS, "obs-2")
        self.assertEqual(first["action"], "select_option")
        self.assertEqual(engine.trace[0]["note"],
                         "below confidence 0.50")

    def test_missing_slot_target_is_skipped(self) -> None:
        targets = tuple(entry for entry in C17_TARGETS
                        if entry.role != "text_input")
        engine = _engine("c17", C17_CHOICES)
        first = engine.next_action(targets, "obs-2")
        self.assertEqual(first["action"], "select_option")
        self.assertIn("not visible", engine.trace[0]["note"])

    def test_disabled_target_is_not_used(self) -> None:
        disabled = bt.TargetEntry(id="t12", role="text_input",
                                  label="(no label)",
                                  rect=(0.0, 0.0, 10.0, 10.0),
                                  enabled=False, focused=False)
        targets = (disabled,) + C17_TARGETS
        engine = _engine("c17", C17_CHOICES)
        first = engine.next_action(targets, "obs-2")
        self.assertEqual((first["action"], first["target_ref"]),
                         ("fill_field", "ui:5"))

    def test_skip_and_click_on_fields_produce_no_action(self) -> None:
        choices = {"default_query": ("skip", 0.9),
                   "default_category": ("click", 0.9),
                   "save": ("click", 0.9)}
        engine = _engine("c17", choices)
        first = engine.next_action(C17_TARGETS, "obs-2")
        self.assertEqual((first["action"], first["target_ref"]),
                         ("save_form", "ui:10"))

    def test_uncheck_on_a_field_is_skipped(self) -> None:
        choices = {"default_query": ("uncheck", 0.9),
                   "default_category": ("fill Category: stories", 0.9),
                   "save": ("click", 0.9)}
        engine = _engine("c17", choices)
        first = engine.next_action(C17_TARGETS, "obs-2")
        self.assertEqual(first["action"], "select_option")
        self.assertIn("does not fit", engine.trace[0]["note"])

    def test_engine_never_repeats_an_attempted_slot(self) -> None:
        engine = _engine("c17", C17_CHOICES)
        seen = []
        for seq in range(2, 10):
            action = engine.next_action(C17_TARGETS, "obs-{}".format(seq))
            seen.append(json.dumps(action, sort_keys=True))
        # fill, select, save, then terminal stops only: 4 distinct payloads.
        self.assertEqual(len(seen), 8)
        self.assertEqual(len(set(seen)), 4)
        self.assertEqual(sum(1 for item in seen if '"stop"' in item), 5)

    def test_trace_records_decisions_and_targets(self) -> None:
        engine = _engine("c17", C17_CHOICES)
        engine.next_action(C17_TARGETS, "obs-2")
        entry = engine.trace[0]
        self.assertEqual(entry["key"], "default_query")
        self.assertEqual(entry["decision"], "fill")
        self.assertEqual(entry["target"], "ui:5")
        self.assertEqual(entry["executed"], "fill_field")
        self.assertAlmostEqual(entry["confidence"], 0.99, places=3)


class ProposerTest(unittest.TestCase):
    class _FakeSession:
        def __init__(self):
            self.last_snapshot = type("Shot", (), {"seq": 7})()
            self.last_targets = type("Targets", (), {
                "seq": 7, "targets": C17_TARGETS})()
            self.calls = 0

        def targets(self):
            self.calls += 1
            self.last_targets = type("Targets", (), {
                "seq": 7, "targets": C17_TARGETS})()
            return self.last_targets

    def test_proposer_uses_current_observation_id(self) -> None:
        engine = _engine("c17", C17_CHOICES)
        proposer = cua.typed_proposer(self._FakeSession(), engine)
        action, meta = proposer(b"png", "prompt")
        self.assertEqual(action["observation_id"], "obs-7")
        self.assertEqual(meta["source"], "cua-s1")

    def test_proposer_refreshes_stale_targets(self) -> None:
        session = self._FakeSession()
        session.last_targets = None
        engine = _engine("c17", C17_CHOICES)
        proposer = cua.typed_proposer(session, engine)
        proposer(b"png", "prompt")
        self.assertEqual(session.calls, 1)

    def test_engine_rejects_unknown_task(self) -> None:
        document = _decisions_document({})
        with self.assertRaises(ValueError):
            cua.CuaS1Engine("c99", document)


if __name__ == "__main__":
    unittest.main()
