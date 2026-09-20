from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from vision_assistant import browser_eval as ev
from vision_assistant import browser_fixtures as fixtures
from vision_assistant import browser_tasks as tasks

FROZEN_MANIFEST_SHA = "df630b21d9a0330214bb5cf01e0892ad82f589e5cb4206e81ff38af54f43d510"


class EvalManifestTest(unittest.TestCase):
    def test_twenty_tasks_with_frozen_ids(self) -> None:
        ids = [spec.id for spec in ev.EVAL_TASKS]
        self.assertEqual(ids, ["t{:02d}".format(n) for n in range(1, 21)])
        self.assertTrue(all(spec.instance == "eval" for spec in ev.EVAL_TASKS))
        self.assertTrue(all(spec.split == "E" for spec in ev.EVAL_TASKS))

    def test_eighteen_productive_two_refusals(self) -> None:
        refusals = [spec.id for spec in ev.EVAL_TASKS if spec.refusal]
        self.assertEqual(refusals, ["t19", "t20"])
        self.assertEqual(len(ev.EVAL_TASKS) - len(refusals), 18)

    def test_eval_instance_stays_out_of_the_frozen_public_pair(self) -> None:
        self.assertEqual(fixtures.instances(), ("dev", "heldout"))
        self.assertEqual(fixtures.story("eval", "e01")["sid"], "e01")
        digest = hashlib.sha256(tasks.manifest_json().encode("utf-8")).hexdigest()
        self.assertEqual(digest, FROZEN_MANIFEST_SHA)

    def test_manifest_is_deterministic_and_labelled(self) -> None:
        first = ev.eval_manifest_json()
        self.assertEqual(first, ev.eval_manifest_json())
        payload = json.loads(first)
        self.assertEqual(payload["instance"], "eval")
        self.assertEqual(payload["eval_version"], "m018t-eval-v1")
        self.assertEqual(len(payload["tasks"]), 20)


class EvalOracleTeethTest(unittest.TestCase):
    def test_all_positive_states_pass_and_every_mutation_is_rejected(self) -> None:
        report = ev.run_eval_checks()
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["positive_pass"], 20)
        self.assertEqual(report["mutations_rejected"], report["mutations_total"])
        self.assertGreater(report["mutations_total"], 50)

    def test_seeded_tasks_use_the_eval_seeds(self) -> None:
        self.assertEqual(fixtures.seeds("eval")["t14"]["prefs"]["default_query"],
                         "telescopse")
        self.assertEqual(fixtures.seeds("eval")["t16"]["draft"]["title"],
                         "Draft: bench notes")
        # Dev/heldout seeds untouched.
        self.assertEqual(fixtures.seeds("dev")["32"]["prefs"]["default_query"],
                         "robotcis")

    def test_refusal_oracles_require_blocked_outcomes(self) -> None:
        for task_id in ("t19", "t20"):
            spec = ev.EVAL_TASKS_BY_ID[task_id]
            forged = tasks.good_state(spec)
            forged["outcome"] = "finished"
            self.assertFalse(tasks.verify_task(spec, forged)["ok"], task_id)


class EvalSiteDeterminismTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_site_rebuilds_byte_identical(self) -> None:
        first = fixtures.build_site("eval", self.tmp / "a")
        second = fixtures.build_site("eval", self.tmp / "a")
        third = fixtures.build_site("eval", self.tmp / "b")
        self.assertEqual(first["tree_sha256"], second["tree_sha256"])
        self.assertEqual(first["tree_sha256"], third["tree_sha256"])
        self.assertEqual(first["files"], 77)

    def test_key_derivations(self) -> None:
        self.assertEqual(fixtures.rank_of("eval", "e15"), 15)
        self.assertTrue(fixtures.ai_story("eval", "e08"))
        self.assertFalse(fixtures.ai_story("eval", "e05"))
        hits = fixtures.search("eval", q="robotics")
        self.assertEqual([s["sid"] for s in hits["stories"]], ["e10"])
        self.assertEqual(fixtures.search("eval", q="zzzz")["stories"], [])
        self.assertEqual(fixtures.date_display("eval", "e03"), "Sep 18")
        self.assertEqual(len(fixtures.comments_for("eval", "e02")), 3)
        self.assertEqual(fixtures.duplicate_titles("eval"), ())
        self.assertEqual(fixtures.page_count("eval"), 3)


if __name__ == "__main__":
    unittest.main()
