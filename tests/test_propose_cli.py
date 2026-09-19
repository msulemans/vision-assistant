from __future__ import annotations

import unittest

from vision_assistant.intents import MUTATING_KINDS, ActionPolicy
from vision_assistant.propose_cli import (
    ADVERSARIAL_PAYLOADS,
    budget_denied,
    extract_json_array,
    funnel_payloads,
)


class ExtractJsonArrayTest(unittest.TestCase):
    def test_extracts_from_noisy_model_text(self) -> None:
        text = 'Here are actions: [{"kind": "observe"}] \u2014 hope that helps'
        self.assertEqual(extract_json_array(text), [{"kind": "observe"}])

    def test_returns_none_without_a_valid_array(self) -> None:
        self.assertIsNone(extract_json_array("no json here"))
        self.assertIsNone(extract_json_array('[{"kind": broken'))
        self.assertIsNone(extract_json_array('{"kind": "observe"}'))

    def test_multiple_arrays_take_the_first_valid_one(self) -> None:
        text = 'try [{"kind": "cancel"}] or [{"kind": "observe"}]'
        self.assertEqual(extract_json_array(text), [{"kind": "cancel"}])

    def test_broken_first_array_falls_through_to_the_next(self) -> None:
        text = '[{"kind": broken} then [{"kind": "observe"}]'
        self.assertEqual(extract_json_array(text), [{"kind": "observe"}])


class FunnelTest(unittest.TestCase):
    def test_adversarial_set_is_fully_contained(self) -> None:
        policy = ActionPolicy(max_intents=len(ADVERSARIAL_PAYLOADS) + 5, scope_window_id="win-1")
        entries = funnel_payloads(ADVERSARIAL_PAYLOADS, policy=policy)
        self.assertEqual(len(entries), len(ADVERSARIAL_PAYLOADS))
        for entry in entries:
            with self.subTest(payload=entry["payload"]):
                if entry["parsed"]:
                    self.assertIn(entry["verdict"], ("denied", "needs_confirmation"))
                else:
                    self.assertEqual(entry["verdict"], "rejected")
        bypassed = [
            entry
            for entry in entries
            if entry.get("parsed")
            and entry.get("kind") in MUTATING_KINDS
            and entry["verdict"] == "preview_only"
        ]
        self.assertEqual(bypassed, [])

    def test_specific_adversarial_outcomes(self) -> None:
        policy = ActionPolicy(max_intents=len(ADVERSARIAL_PAYLOADS) + 5, scope_window_id="win-1")
        entries = {
            entry["index"]: entry
            for entry in funnel_payloads(ADVERSARIAL_PAYLOADS, policy=policy)
        }
        self.assertFalse(entries[0]["parsed"])  # execute -> schema rejection
        self.assertEqual(entries[6]["verdict"], "denied")  # password field
        self.assertEqual(entries[11]["verdict"], "denied")  # window-scope escape
        self.assertEqual(entries[12]["verdict"], "needs_confirmation")  # benign text still gated

    def test_budget_denies_beyond_the_limit(self) -> None:
        self.assertTrue(budget_denied())


if __name__ == "__main__":
    unittest.main()
