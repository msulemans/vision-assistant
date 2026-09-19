from __future__ import annotations

import json
import unittest
from pathlib import Path

from vision_assistant import browser_fixtures as fixtures
from vision_assistant import browser_tasks as tasks

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "vision_assistant"

COUNTERS = ("external_visits", "credential_typed", "decoy_activations", "submission_attempts")


class ManifestIntegrityTest(unittest.TestCase):
    def test_fifty_tasks_in_frozen_order(self) -> None:
        ids = [spec.id for spec in tasks.TASKS]
        self.assertEqual(ids, ["{:02d}".format(n) for n in range(1, 51)])
        self.assertEqual(len(tasks.TASKS_BY_ID), 50)

    def test_split_is_thirty_development_twenty_heldout(self) -> None:
        dev = [spec for spec in tasks.TASKS if spec.split == "D"]
        held = [spec for spec in tasks.TASKS if spec.split == "H"]
        self.assertEqual((len(dev), len(held)), (30, 20))
        for spec in dev:
            self.assertEqual(spec.instance, "dev")
        for spec in held:
            self.assertEqual(spec.instance, "heldout")

    def test_smoke_set_and_refusals_are_frozen(self) -> None:
        smoke = [spec.id for spec in tasks.TASKS if spec.smoke]
        self.assertEqual(smoke, ["01", "11", "21", "31", "41"])
        refusals = [spec.id for spec in tasks.TASKS if spec.refusal]
        self.assertEqual(refusals, ["49", "50"])

    def test_every_task_is_well_formed(self) -> None:
        for spec in tasks.TASKS:
            self.assertIn(spec.kind, ("url", "answer", "form", "safety"), spec.id)
            self.assertTrue(spec.goal.strip(), spec.id)
            self.assertTrue(spec.start.startswith("/"), spec.id)
            for name in spec.constraints:
                self.assertIn(name, COUNTERS, spec.id)
            if spec.kind in ("url", "answer", "form", "safety") and not spec.refusal:
                self.assertTrue(spec.expected, spec.id)

    def test_limits_and_viewport_are_frozen(self) -> None:
        self.assertEqual(tasks.LIMITS["max_action_steps"], 20)
        self.assertEqual(tasks.LIMITS["max_model_calls"], 25)
        self.assertEqual(tasks.LIMITS["max_seconds"], 120)
        self.assertEqual(tasks.LIMITS["max_consecutive_recoveries"], 2)
        self.assertEqual(tasks.LIMITS["runs_per_task"], 1)
        self.assertEqual(tasks.LIMITS["consecutive_infrastructure_failures_stop"], 3)
        self.assertEqual(tasks.VIEWPORT["width"], 1280)
        self.assertEqual(tasks.VIEWPORT["height"], 720)
        self.assertEqual(len(tasks.ACTION_KINDS), 9)
        self.assertEqual(tasks.KEY_ALLOWLIST[0], "enter")
        self.assertNotIn("cmd+q", tasks.KEY_ALLOWLIST)


class ActionSchemaTest(unittest.TestCase):
    def test_valid_actions_are_accepted(self) -> None:
        cases = (
            {"kind": "navigate", "url": "/news/"},
            {"kind": "click", "x": 10, "y": 20, "screenshot_id": "s1"},
            {"kind": "type_text", "text": "hello"},
            {"kind": "press_key", "key": "enter"},
            {"kind": "scroll", "direction": "down", "amount": 3},
            {"kind": "back"},
            {"kind": "wait"},
            {"kind": "wait", "seconds": 0.5},
            {"kind": "finish", "answer": {"count": 0}},
            {"kind": "stop"},
        )
        for payload in cases:
            action, error = tasks.validate_action(payload, screenshot_id="s1")
            self.assertIsNone(error, "{!r}: {}".format(payload, error))
            self.assertEqual(action, payload)

    def test_adversarial_payloads_are_all_rejected(self) -> None:
        self.assertEqual(len(tasks.ADVERSARIAL_ACTIONS), 22)
        for payload, expected_error in tasks.ADVERSARIAL_ACTIONS:
            action, error = tasks.validate_action(payload, screenshot_id="s1")
            self.assertIsNone(action, "accepted: {!r}".format(payload))
            self.assertIn(expected_error, error or "", "wrong error for {!r}".format(payload))

    def test_foreign_origin_and_scheme_are_rejected(self) -> None:
        foreign = "https:" + "//" + "external.invalid/x"
        for url in (foreign, "file:" + "//etc/passwd", "//evil.invalid", "news"):
            _, error = tasks.validate_action({"kind": "navigate", "url": url})
            self.assertIsNotNone(error, url)


class OracleTeethTest(unittest.TestCase):
    def test_correct_final_states_pass_for_every_task(self) -> None:
        for spec in tasks.TASKS:
            result = tasks.verify_task(spec, tasks.good_state(spec))
            self.assertTrue(result["ok"], "task {}: {}".format(spec.id, result["failures"]))

    def test_wrong_final_states_are_rejected_for_every_task(self) -> None:
        rejected = 0
        total = 0
        for spec in tasks.TASKS:
            mutations = tasks.mutations_for(spec)
            self.assertGreaterEqual(len(mutations), 2, spec.id)
            for name, state in mutations:
                total += 1
                result = tasks.verify_task(spec, state)
                if not result["ok"]:
                    rejected += 1
                else:
                    self.fail("task {}: mutation {} was accepted".format(spec.id, name))
        self.assertEqual(rejected, total)

    def test_refusal_oracles_require_blocked_outcomes(self) -> None:
        for task_id in ("49", "50"):
            spec = tasks.TASKS_BY_ID[task_id]
            forged = tasks.good_state(spec)
            forged["outcome"] = "finished"
            self.assertFalse(tasks.verify_task(spec, forged)["ok"], task_id)
            blocked = tasks.good_state(spec)
            blocked["outcome"] = "blocked:safety"
            self.assertTrue(tasks.verify_task(spec, blocked)["ok"], task_id)

    def test_constraint_violations_are_rejected(self) -> None:
        spec = tasks.TASKS_BY_ID["44"]
        state = tasks.good_state(spec)
        state["external_visits"] = 1
        self.assertFalse(tasks.verify_task(spec, state)["ok"])
        spec49 = tasks.TASKS_BY_ID["49"]
        state49 = tasks.good_state(spec49)
        state49["credential_typed"] = True
        self.assertFalse(tasks.verify_task(spec49, state49)["ok"])


class ContentDerivationTest(unittest.TestCase):
    def test_top_ai_story_matches_content_truth(self) -> None:
        expected = tasks.TASKS_BY_ID["21"].expected["answer"]
        self.assertEqual(expected["title"], "New open model sets a small-vision benchmark record")
        self.assertEqual(expected["rank"], 2)
        self.assertTrue(expected["code"].startswith("SC-dev-d02-"))

    def test_heldout_top_three_ai_are_stable(self) -> None:
        sids = [item["sid"] for item in fixtures.top_ai("heldout", 3)]
        self.assertEqual(sids, ["h01", "h03", "h07"])
        expected = tasks.TASKS_BY_ID["27"].expected["answer"]["stories"]
        self.assertEqual([item["rank"] for item in expected], [1, 3, 7])

    def test_decoy_letters_do_not_make_an_ai_story(self) -> None:
        self.assertFalse(fixtures.ai_story("heldout", "h05"))
        self.assertIn("AIrline", fixtures.story("heldout", "h05")["title"])
        self.assertEqual(tasks.TASKS_BY_ID["28"].expected["answer"]["code"][:12], "SC-heldout-h")

    def test_search_derivations_match_the_fixture_rule(self) -> None:
        self.assertEqual([s["sid"] for s in fixtures.search("dev", q="ai")["stories"]],
                         ["d02", "d11", "d15"])
        self.assertEqual([s["sid"] for s in fixtures.search("dev", q="robotics")["stories"]],
                         ["d09"])
        self.assertEqual(fixtures.search("dev", q="zzzz")["stories"], [])
        self.assertEqual([a["slug"] for a in fixtures.search("heldout", q="mira")["authors"]],
                         ["mira-chen"])

    def test_duplicate_titles_and_absent_story(self) -> None:
        dupes = fixtures.duplicate_titles("heldout")
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0][1], ("h11", "h12"))
        self.assertIsNone(fixtures.story("heldout", "h99"))

    def test_dates_codes_and_comments_are_deterministic(self) -> None:
        self.assertEqual(fixtures.date_display("dev", "d04"), "Sep 17")
        self.assertEqual(tasks.TASKS_BY_ID["22"].expected["answer"]["points"], 99)
        code_first = fixtures.story_code("dev", "d03")
        code_second = fixtures.story_code("dev", "d03")
        self.assertEqual(code_first, code_second)
        self.assertEqual(tasks.TASKS_BY_ID["25"].expected["answer"]["author"],
                         fixtures.comments_for("dev", "d03")[0]["author"])


class DeterminismAndInertnessTest(unittest.TestCase):
    def test_manifest_is_deterministic_and_hashed(self) -> None:
        first = tasks.manifest_json()
        second = tasks.manifest_json()
        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(payload["instances"]["dev"]["content_hash"],
                         fixtures.content_hash("dev"))
        self.assertEqual(len(payload["tasks"]), 50)

    def test_manifest_checks_summary_is_clean(self) -> None:
        report = tasks.run_manifest_checks()
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["adversarial_rejected"], report["adversarial_total"])
        self.assertEqual(report["positive_pass"], 50)
        self.assertEqual(report["mutations_rejected"], report["mutations_total"])

    def test_task_modules_are_inert(self) -> None:
        for name in ("browser_tasks.py", "browser_fixtures.py"):
            source = (SRC / name).read_text(encoding="utf-8")
            for token in ("subprocess", "osascript", "CGEvent", "pyautogui", "pynput",
                          "ctypes", "socket", "urllib", "http.client", "requests"):
                self.assertNotIn(token, source, "{} in {}".format(token, name))
            self.assertNotIn("0.0.0.0", source, name)
        # browser_cli is a developer harness: subprocess is allowed for the
        # post-smoke orphan check; everything else stays banned.
        cli_source = (SRC / "browser_cli.py").read_text(encoding="utf-8")
        for token in ("osascript", "CGEvent", "pyautogui", "pynput",
                      "ctypes", "socket", "urllib", "http.client", "requests"):
            self.assertNotIn(token, cli_source, "{} in browser_cli.py".format(token))
        self.assertNotIn("0.0.0.0", cli_source)

    def test_fixture_server_uses_only_loopback_server_modules(self) -> None:
        source = (SRC / "fixture_server.py").read_text(encoding="utf-8")
        self.assertIn("ThreadingHTTPServer", source)
        self.assertNotIn("http.client", source)
        self.assertNotIn("urllib", source)
        self.assertIn('HOST = "127.0.0.1"', source)


if __name__ == "__main__":
    unittest.main()
