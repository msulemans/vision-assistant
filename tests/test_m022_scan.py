"""M022 focused tests: multi-viewport evidence accumulation (deterministic).

Proves, without any model, browser, or network: (1) no skipped viewport
ranges + overlap between captures; (2) traversal starts at the top and fails
closed on unchanged/gap/layout changes and on the viewport budget; (3) the
ledger survives later screenshots, rejects stale observations, and rejects
duplicate/conflicting claims without overwriting; (4) the trusted ranking
selects the lowest three primary candidates; (5) the model cannot finish
before the document end (and must record the final viewport first); (6) the
final answer cannot contain unrecorded candidates; (7) clicks/types/
submissions are structurally unavailable; (8) reviewer/link data never
enters prompts; (9) budgets bound the run and reporting is crash-safe.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from vision_assistant import browser_cli
from vision_assistant import browser_session as bs
from vision_assistant import m022_scan as scan
from vision_assistant.browser_session import BrowserError, Snapshot

FROZEN_GOAL_SHA256 = (
    "736974ad2cbfbb7020c33c42377fa6f2ec5647dc2b5a9817705dff3fb17409b6")

CANARY = "CANARY-LINK-9F31"


def _make_png(width: int = 64, height: int = 36) -> bytes:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _obs_from(prompt: str) -> str:
    for token in prompt.split():
        if token.startswith("obs-"):
            return token.strip(".,")
    return ""


class FakeScanSession:
    """Deterministic stand-in for BrowserSession (no browser, no network)."""

    width = 1280
    height = 720

    def __init__(self, tmp: Path, *, document_height=1218, viewport_height=720,
                 step_factor=1.0, layout_drift=0, links_rows=None,
                 scroll_error=None):
        self.tmp = tmp
        self.document_height = document_height
        self.viewport_height = viewport_height
        self.scroll_y = 0
        self.step_factor = step_factor
        self.layout_drift = layout_drift
        self.links_rows = list(links_rows or [])
        self.scroll_error = scroll_error
        self.seq = 0
        self.calls: list = []
        self.scrolls: list = []

    def navigate(self, url: str) -> str:
        self.calls.append(("navigate", url))
        return url

    def snapshot(self) -> Snapshot:
        self.seq += 1
        path = self.tmp / "shot-{}.png".format(self.seq)
        path.write_bytes(_make_png())
        return Snapshot(seq=self.seq, width=2560, height=1440, scale=2.0,
                        url=scan.START_URL, path=str(path))

    def state(self) -> dict:
        return {"page": {"scrollY": self.scroll_y,
                         "scrollHeight": self.document_height,
                         "innerHeight": self.viewport_height}}

    def scroll(self, direction: str, amount, method=None):
        if self.scroll_error:
            raise BrowserError(self.scroll_error)
        self.scrolls.append((direction, amount, method))
        max_scroll = max(0, self.document_height - self.viewport_height)
        delta = round(amount * self.viewport_height * self.step_factor)
        self.scroll_y = min(self.scroll_y + delta, max_scroll)
        self.document_height += self.layout_drift
        return amount

    def links(self) -> dict:
        return {"links": [dict(row) for row in self.links_rows],
                "truncated": False}

    def click(self, *args, **kwargs):
        self.calls.append(("click", args))
        return ""

    def type_text(self, *args, **kwargs):
        self.calls.append(("type_text", args))
        return 0

    def save_form(self, *args, **kwargs):
        self.calls.append(("save_form", args))
        return ""

    def stop(self) -> None:
        pass


class ScriptedProposer:
    def __init__(self, actions):
        self.actions = list(actions)
        self.prompts: list = []
        self.pngs: list = []

    def __call__(self, png_bytes, prompt):
        self.prompts.append(prompt)
        self.pngs.append(png_bytes)
        if not self.actions:
            return None, {"chars": 0}
        item = self.actions.pop(0)
        if callable(item):
            item = item(prompt)
        return item, {"chars": 64}


def _candidate(rank, title, *, points=None, relevance="primary", obs=None):
    payload = {"rank": rank, "title": title, "ai_relevance": relevance,
               "reason": "visible and relevant"}
    if points is not None:
        payload["visible_points"] = points
    if obs is not None:
        payload["observation_id"] = obs
    return payload


def _record(candidates):
    def build(prompt):
        obs = _obs_from(prompt)
        items = []
        for candidate in candidates:
            item = dict(candidate)
            item.setdefault("observation_id", obs)
            items.append(item)
        return {"action": "record_candidates", "observation_id": obs,
                "candidates": items}
    return build


def _no_candidates(prompt):
    return {"action": "no_candidates", "observation_id": _obs_from(prompt)}


def _next(prompt):
    return {"action": "next_viewport", "observation_id": _obs_from(prompt)}


def _finish(ranks):
    return lambda prompt: {"action": "finish_selection", "ranks": list(ranks),
                           "explanation": "trusted ranking confirmed"}


def _stop(prompt):
    return {"action": "stop", "reason": "nothing further"}


HAPPY_LINKS = [
    {"row": 0, "label": "Exfiltrate Your Weights", "href": "https://exfil-weights.example/"},
    {"row": 1, "label": "218 comments", "href": "item?id=46100001"},
    {"row": 4, "label": "AI generated posters don't have to be horrible",
     "href": "https://posters.example/ai"},
    {"row": 5, "label": "451 comments", "href": "item?id=46100008"},
    {"row": 8, "label": "I built non-autoregressive decision models",
     "href": "https://laya.example/rl"},
    {"row": 9, "label": "88 comments", "href": "item?id=46100009"},
]


def _happy_actions():
    return [
        _record([_candidate(1, "Exfiltrate Your Weights", points=218),
                 _candidate(8, "AI generated posters don't have to be horrible",
                            points=1451)]),
        _next,
        _record([_candidate(9, "I built non-autoregressive decision models",
                            points=1146),
                 _candidate(27, "Can you tell which images are AI-generated?",
                            points=59, relevance="incidental")]),
        _next,
        _finish([1, 8, 9]),
    ]


# ----------------------------------------------------------- 1. traversal

class TraversalTest(unittest.TestCase):
    def test_steps_are_at_most_70_percent_with_overlap(self) -> None:
        traversal = scan.ViewportTraversal()
        traversal.begin(scroll_y=0, viewport_height=1000, document_height=10000,
                        observation_id="obs-1", seq=1)
        self.assertFalse(traversal.complete)
        self.assertEqual(traversal.next_step_px(), 700)
        self.assertAlmostEqual(traversal.next_fraction(), 0.7)
        for index in range(2, 8):
            y = 700 * (index - 1)
            traversal.advance(scroll_y=y, viewport_height=1000,
                              document_height=10000,
                              observation_id="obs-{}".format(index), seq=index)
        pairs = list(zip(traversal.viewports, traversal.viewports[1:]))
        self.assertTrue(pairs)
        for earlier, later in pairs:
            overlap = (earlier.scroll_y + earlier.viewport_height) - later.scroll_y
            self.assertGreaterEqual(overlap, 0.3 * earlier.viewport_height)

    def test_begin_requires_the_top(self) -> None:
        traversal = scan.ViewportTraversal()
        with self.assertRaises(scan.ScanError) as caught:
            traversal.begin(scroll_y=500, viewport_height=720,
                            document_height=5000, observation_id="obs-1")
        self.assertEqual(caught.exception.reason, "traversal_not_at_top")
        traversal.begin(scroll_y=0, viewport_height=720, document_height=5000,
                        observation_id="obs-1")
        self.assertEqual(len(traversal.viewports), 1)

    def test_advance_rejects_unchanged_gap_and_layout_changes(self) -> None:
        traversal = scan.ViewportTraversal()
        traversal.begin(scroll_y=0, viewport_height=720, document_height=5000,
                        observation_id="obs-1")
        with self.assertRaises(scan.ScanError) as caught:
            traversal.advance(scroll_y=0, viewport_height=720,
                              document_height=5000, observation_id="obs-x")
        self.assertEqual(caught.exception.reason, "viewport_unchanged")
        with self.assertRaises(scan.ScanError) as caught:
            traversal.advance(scroll_y=1000, viewport_height=720,
                              document_height=5000, observation_id="obs-x")
        self.assertEqual(caught.exception.reason, "viewport_gap")
        with self.assertRaises(scan.ScanError) as caught:
            traversal.advance(scroll_y=500, viewport_height=760,
                              document_height=5000, observation_id="obs-x")
        self.assertEqual(caught.exception.reason, "viewport_metrics_changed")
        with self.assertRaises(scan.ScanError) as caught:
            traversal.advance(scroll_y=500, viewport_height=720,
                              document_height=5300, observation_id="obs-x")
        self.assertEqual(caught.exception.reason, "viewport_layout_changed")
        self.assertEqual(len(traversal.viewports), 1)
        traversal.advance(scroll_y=500, viewport_height=720,
                          document_height=5000, observation_id="obs-2", seq=2)
        self.assertEqual(len(traversal.viewports), 2)

    def test_completion_at_document_end(self) -> None:
        traversal = scan.ViewportTraversal()
        traversal.begin(scroll_y=0, viewport_height=720, document_height=1218,
                        observation_id="obs-1")
        self.assertFalse(traversal.complete)
        self.assertEqual(traversal.next_step_px(), 498)
        traversal.advance(scroll_y=498, viewport_height=720,
                          document_height=1218, observation_id="obs-2")
        self.assertTrue(traversal.complete)
        self.assertIsNone(traversal.next_step_px())
        with self.assertRaises(scan.ScanError) as caught:
            traversal.advance(scroll_y=498, viewport_height=720,
                              document_height=1218, observation_id="obs-3")
        self.assertEqual(caught.exception.reason, "traversal_complete")
        short = scan.ViewportTraversal()
        short.begin(scroll_y=0, viewport_height=720, document_height=600,
                    observation_id="obs-1")
        self.assertTrue(short.complete)

    def test_viewport_budget_and_invalid_metrics(self) -> None:
        traversal = scan.ViewportTraversal(max_viewports=3)
        traversal.begin(scroll_y=0, viewport_height=720, document_height=50000,
                        observation_id="obs-1")
        traversal.advance(scroll_y=504, viewport_height=720,
                          document_height=50000, observation_id="obs-2")
        traversal.advance(scroll_y=1008, viewport_height=720,
                          document_height=50000, observation_id="obs-3")
        with self.assertRaises(scan.ScanError) as caught:
            traversal.advance(scroll_y=1512, viewport_height=720,
                              document_height=50000, observation_id="obs-4")
        self.assertEqual(caught.exception.reason, "viewport_budget")
        with self.assertRaises(scan.ScanError) as caught:
            scan.ViewportTraversal().begin(scroll_y=0, viewport_height=0,
                                           document_height=500,
                                           observation_id="obs-1")
        self.assertEqual(caught.exception.reason, "traversal_metrics_invalid")


# ------------------------------------------------------------- 2. ledger

class LedgerTest(unittest.TestCase):
    def test_entries_keep_their_observation_ids(self) -> None:
        ledger = scan.EvidenceLedger()
        ledger.add(_candidate(1, "Exfiltrate Your Weights", points=218,
                              obs="obs-1"),
                   current_observation_id="obs-1")
        ledger.add(_candidate(9, "non-autoregressive models", obs="obs-2"),
                   current_observation_id="obs-2")
        rows = ledger.as_dicts()
        self.assertEqual([row["observation_id"] for row in rows],
                         ["obs-1", "obs-2"])
        self.assertEqual([entry.rank for entry in ledger.selection()], [1, 9])

    def test_duplicate_and_conflicting_claims_rejected_without_overwrite(
            self) -> None:
        ledger = scan.EvidenceLedger()
        ledger.add(_candidate(1, "Exfiltrate Your Weights", points=218,
                              obs="obs-1"),
                   current_observation_id="obs-1")
        with self.assertRaises(scan.ScanError) as caught:
            ledger.add(_candidate(1, "Exfiltrate Your Weights", points=999,
                                  obs="obs-2"),
                       current_observation_id="obs-2")
        self.assertEqual(caught.exception.reason, "duplicate_candidate")
        with self.assertRaises(scan.ScanError) as caught:
            ledger.add(_candidate(1, "Something else entirely", obs="obs-2"),
                       current_observation_id="obs-2")
        self.assertEqual(caught.exception.reason, "conflicting_candidate")
        with self.assertRaises(scan.ScanError) as caught:
            ledger.add(_candidate(4, "Exfiltrate Your Weights", obs="obs-2"),
                       current_observation_id="obs-2")
        self.assertEqual(caught.exception.reason, "conflicting_candidate")
        self.assertEqual(len(ledger.entries), 1)
        self.assertEqual(ledger.entries[0].visible_points, 218)

    def test_stale_or_unknown_observations_rejected(self) -> None:
        ledger = scan.EvidenceLedger()
        for cited in ("obs-1", "obs-99"):
            with self.assertRaises(scan.ScanError) as caught:
                ledger.add(_candidate(3, "Story", obs=cited),
                           current_observation_id="obs-2")
            self.assertEqual(caught.exception.reason, "stale_observation")
        self.assertEqual(ledger.entries, [])

    def test_selection_is_the_lowest_three_primaries(self) -> None:
        ledger = scan.EvidenceLedger()
        ledger.add(_candidate(7, "Primary seven", obs="obs-1"),
                   current_observation_id="obs-1")
        ledger.add(_candidate(2, "Incidental two", relevance="incidental",
                              obs="obs-1"),
                   current_observation_id="obs-1")
        ledger.add(_candidate(5, "Primary five", obs="obs-1"),
                   current_observation_id="obs-1")
        ledger.add(_candidate(9, "Primary nine", obs="obs-1"),
                   current_observation_id="obs-1")
        ledger.add(_candidate(4, "Primary four", obs="obs-1"),
                   current_observation_id="obs-1")
        self.assertEqual([entry.rank for entry in ledger.selection()],
                         [4, 5, 7])
        lean = scan.EvidenceLedger()
        lean.add(_candidate(6, "Only one primary", obs="obs-1"),
                 current_observation_id="obs-1")
        lean.add(_candidate(1, "Incidental", relevance="incidental",
                            obs="obs-1"),
                 current_observation_id="obs-1")
        self.assertEqual([entry.rank for entry in lean.selection()], [6])

    def test_candidate_validation_rules(self) -> None:
        cases = (
            (_candidate(True, "Story"), "rank must be an integer"),
            (_candidate(0, "Story"), "rank must be an integer"),
            ({c: v for c, v in _candidate(1, "Story").items()
              if c != "observation_id"}, "missing field 'observation_id'"),
            (_candidate(1, "ui:3"), "ui: target reference"),
            (_candidate(1, "Story", relevance="maybe"), "ai_relevance must be"),
            ({**_candidate(1, "Story"), "visible_points": -3},
             "visible_points must be an integer"),
            ({**_candidate(1, "Story"), "extra": 1}, "unexpected field"),
        )
        for candidate, needle in cases:
            payload = dict(candidate)
            if needle != "missing field 'observation_id'":
                payload.setdefault("observation_id", "obs-5")
            parsed, error = scan.validate_candidate(payload,
                                                    current_observation_id="obs-5")
            self.assertIsNone(parsed, candidate)
            self.assertIn(needle, error, candidate)
        parsed, error = scan.validate_candidate(
            _candidate(1, "Story", obs="obs-4"), current_observation_id="obs-5")
        self.assertIsNone(parsed)
        self.assertIn("stale observation", error)
        parsed, error = scan.validate_candidate(
            _candidate(1, "Story", obs="obs-5"), current_observation_id="obs-5")
        self.assertIsNotNone(parsed)


# ---------------------------------------------------- 3. actions and schema

class ActionValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.traversal = scan.ViewportTraversal()
        self.traversal.begin(scroll_y=0, viewport_height=720,
                             document_height=1218, observation_id="obs-1")

    def test_interaction_actions_do_not_exist(self) -> None:
        self.assertEqual(scan.SCAN_ACTIONS,
                         ("record_candidates", "no_candidates",
                          "next_viewport", "finish_selection", "stop"))
        for kind in ("click_target", "fill_field", "select_option",
                     "set_toggle", "save_form", "scroll", "navigate", "back",
                     "finish", "click"):
            parsed, error = scan.validate_scan_action(
                {"action": kind}, observation_id="obs-1",
                traversal=self.traversal, phase="scanning")
            self.assertIsNone(parsed, kind)
            self.assertIn("unknown scan action", error)

    def test_schema_has_exactly_the_scan_actions(self) -> None:
        schema = scan.scan_action_schema()
        branches = {branch["properties"]["action"]["enum"][0]: branch
                    for branch in schema["oneOf"]}
        self.assertEqual(sorted(branches), sorted(scan.SCAN_ACTIONS))
        forbidden = {"target_ref", "url", "x", "y", "amount", "key"}
        for branch in branches.values():
            self.assertIs(branch["additionalProperties"], False)
            self.assertFalse(forbidden & set(branch["properties"]))
        self.assertEqual(branches["finish_selection"]["required"],
                         ["action", "ranks", "explanation"])
        candidate_shape = branches["record_candidates"]["properties"]["candidates"]["items"]
        self.assertEqual(candidate_shape["required"],
                         ["rank", "title", "ai_relevance", "reason",
                          "observation_id"])
        self.assertIs(candidate_shape["additionalProperties"], False)
        self.assertEqual(branches["record_candidates"]["required"],
                         ["action", "observation_id", "candidates"])

    def test_capabilities_track_the_three_phases(self) -> None:
        self.assertEqual(scan.scan_capabilities("scanning")["allowed_actions"],
                         ["record_candidates", "no_candidates",
                          "next_viewport", "stop"])
        self.assertEqual(scan.scan_capabilities("recording")["allowed_actions"],
                         ["record_candidates", "no_candidates",
                          "next_viewport", "stop"])
        self.assertEqual(scan.scan_capabilities("final")["allowed_actions"],
                         ["finish_selection", "stop"])

    def test_finish_is_gated_on_completion_and_exact_selection(self) -> None:
        payload = {"action": "finish_selection", "ranks": [1, 8],
                   "explanation": "the lowest three primary ranks"}
        parsed, error = scan.validate_scan_action(
            payload, observation_id="obs-1", traversal=self.traversal,
            phase="scanning", selection_ranks=[1, 8])
        self.assertIsNone(parsed)
        self.assertIn("traversal incomplete", error)
        self.traversal.advance(scroll_y=498, viewport_height=720,
                               document_height=1218, observation_id="obs-2")
        parsed, error = scan.validate_scan_action(
            payload, observation_id="obs-2", traversal=self.traversal,
            phase="recording", selection_ranks=[1, 8])
        self.assertIsNone(parsed)
        self.assertIn("record the final viewport first", error)
        mismatch, error = scan.validate_scan_action(
            {**payload, "ranks": [1, 8, 99]}, observation_id="obs-2",
            traversal=self.traversal, phase="final", selection_ranks=[1, 8])
        self.assertIsNone(mismatch, error)
        self.assertIn("trusted selection", error)
        parsed, error = scan.validate_scan_action(
            payload, observation_id="obs-2", traversal=self.traversal,
            phase="final", selection_ranks=[1, 8])
        self.assertIsNotNone(parsed, error)
        parsed, error = scan.validate_scan_action(
            {"action": "record_candidates", "observation_id": "obs-2",
             "candidates": [_candidate(1, "Later addition", obs="obs-2")]},
            observation_id="obs-2", traversal=self.traversal, phase="final")
        self.assertIsNone(parsed)
        self.assertIn("recording is closed", error)


# ------------------------------------------------------------- 4. runner

class ScanLoopBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_scan(self, actions, *, session=None, limits=None, links_provider=None):
        session = session or FakeScanSession(self.tmp, links_rows=HAPPY_LINKS)
        proposer = ScriptedProposer(actions)
        report = scan.run_scan(
            session, proposer, sleep=lambda seconds: None,
            log=lambda *args, **kw: None,
            limits=limits or scan.ScanLimits(),
            links_provider=links_provider,
            now=lambda: "2026-09-20T05:00:00Z")
        return session, proposer, report


class ScanLoopTest(ScanLoopBase):
    def test_two_viewport_scan_records_evidence_and_finishes(self) -> None:
        session, proposer, report = self.run_scan(_happy_actions())
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["viewports"], 2)
        self.assertEqual(len(report["ledger"]), 4)
        ids = [row["observation_id"] for row in report["ledger"]]
        self.assertEqual(ids.count("obs-1"), 2)
        self.assertEqual(ids.count("obs-2"), 2)
        self.assertEqual([row["rank"] for row in report["selection"]],
                         [1, 8, 9])
        result = report["result"]
        self.assertEqual(result["found"], 3)
        self.assertEqual(result["observed_at"], "2026-09-20T05:00:00Z")
        self.assertEqual([story["hn_link"] for story in result["stories"]],
                         ["item?id=46100001", "item?id=46100008",
                          "item?id=46100009"])
        self.assertIn("trusted browser metadata", result["hn_link_note"])
        scrolls = session.scrolls
        self.assertEqual(len(scrolls), 1)
        self.assertEqual(scrolls[0][0], "down")
        self.assertAlmostEqual(scrolls[0][1], 498 / 720, places=4)
        self.assertEqual(scrolls[0][2], "dom")
        self.assertEqual(len(proposer.prompts), 5)

    def test_final_call_gets_only_the_ledger_not_a_screenshot(self) -> None:
        _session, proposer, report = self.run_scan(_happy_actions())
        self.assertEqual(report["outcome"], "finished")
        final_prompt = proposer.prompts[-1]
        self.assertIn("No screenshot accompanies this step", final_prompt)
        self.assertIn("Ledger (authoritative", final_prompt)
        self.assertIn('rank 1: "Exfiltrate Your Weights"', final_prompt)
        self.assertIn("Trusted selection", final_prompt)
        self.assertEqual(proposer.pngs[-1], scan.placeholder_png())
        scan_prompt = proposer.prompts[0]
        self.assertIn("Current observation: obs-1", scan_prompt)
        self.assertNotEqual(proposer.pngs[0], scan.placeholder_png())

    def test_cannot_finish_before_the_document_end(self) -> None:
        _session, proposer, report = self.run_scan([
            _record([_candidate(1, "Exfiltrate Your Weights", points=218)]),
            _finish([1]),
            _next,
            _record([_candidate(8, "AI generated posters", points=1451)]),
            _finish([1, 8]),
            _next,
            _finish([1, 8]),
        ])
        self.assertEqual(report["outcome"], "finished", report["steps"])
        errors = [step.get("error") for step in report["steps"]
                  if step.get("kind") == "proposal" and step.get("error")]
        self.assertTrue(any("traversal incomplete" in str(error)
                            for error in errors), errors)
        self.assertTrue(any("record the final viewport first" in str(error)
                            for error in errors), errors)
        self.assertTrue(any("traversal incomplete" in prompt
                            for prompt in proposer.prompts))

    def test_stale_and_duplicate_candidates_are_fed_back(self) -> None:
        _session, proposer, report = self.run_scan([
            _record([_candidate(1, "Exfiltrate Your Weights", points=218)]),
            _next,
            _record([_candidate(5, "New story", points=10, obs="obs-1")]),
            _record([_candidate(1, "Exfiltrate Your Weights", points=218)]),
            _record([_candidate(6, "Exfiltrate Your Weights")]),
            _next,
            _finish([1]),
        ])
        self.assertEqual(report["outcome"], "finished", report["steps"])
        self.assertEqual(len(report["ledger"]), 1)
        errors = [step.get("error") for step in report["steps"]
                  if step.get("kind") == "proposal" and step.get("error")]
        self.assertTrue(any("stale observation" in str(error) for error in errors))
        rejected = [step for step in report["steps"]
                    if step.get("kind") == "ledger" and step.get("rejected")]
        reasons = [reason for step in rejected for reason in step["rejected"]]
        self.assertIn("duplicate_candidate", reasons)
        self.assertIn("conflicting_candidate", reasons)
        history = "\n".join(proposer.prompts)
        self.assertIn("already recorded", history)

    def test_unchanged_viewport_fails_the_run_closed(self) -> None:
        session = FakeScanSession(self.tmp, step_factor=0.0)
        _session, _proposer, report = self.run_scan(
            [_no_candidates, _next, _next, _next], session=session)
        self.assertEqual(report["outcome"], "failed:traversal")
        self.assertEqual(report["steps"][-1]["reason"], "viewport_unchanged")

    def test_skipped_range_fails_the_run_closed(self) -> None:
        session = FakeScanSession(self.tmp, document_height=5000,
                                  step_factor=1.6)
        _session, _proposer, report = self.run_scan(
            [_no_candidates, _next], session=session)
        self.assertEqual(report["outcome"], "failed:traversal")
        self.assertEqual(report["steps"][-1]["reason"], "viewport_gap")

    def test_call_budget_caps_the_run(self) -> None:
        session = FakeScanSession(self.tmp)
        _session, proposer, report = self.run_scan(
            [_no_candidates] * 10, session=session,
            limits=scan.ScanLimits(max_calls=3))
        self.assertEqual(report["outcome"], "failed:budget_calls")
        self.assertEqual(report["calls"], 3)
        self.assertEqual(len(proposer.prompts), 3)
        self.assertEqual(session.scrolls, [])

    def test_viewport_budget_bounds_a_very_long_page(self) -> None:
        session = FakeScanSession(self.tmp, document_height=50000)
        _session, _proposer, report = self.run_scan([_next] * 12,
                                                    session=session)
        self.assertEqual(report["viewports"], 8)
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        self.assertEqual(len(session.scrolls), 7)
        self.assertLessEqual(report["calls"], scan.MAX_CALLS)

    def test_no_interaction_calls_and_link_data_never_in_prompts(self) -> None:
        links = list(HAPPY_LINKS) + [
            {"row": 30, "label": "Other links " + CANARY,
             "href": "https://canary.example/" + CANARY},
        ]
        session = FakeScanSession(self.tmp, links_rows=links)
        _session, proposer, report = self.run_scan(_happy_actions(),
                                                   session=session)
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual([story["hn_link"]
                          for story in report["result"]["stories"]],
                         ["item?id=46100001", "item?id=46100008",
                          "item?id=46100009"])
        joined = "\n".join(proposer.prompts)
        self.assertNotIn(CANARY, joined)
        self.assertNotIn("item?id=", joined)
        self.assertNotIn("exfil-weights.example", joined)
        self.assertNotIn("canary.example", joined)
        self.assertEqual(_session.calls, [])
        self.assertEqual([call for call in session.calls
                          if call[0] in ("click", "type_text", "save_form")],
                         [])

    def test_reviewer_canary_file_never_reaches_prompts(self) -> None:
        root = self.tmp / "run"
        reviewer = root / "reviewer"
        reviewer.mkdir(parents=True)
        (reviewer / "snapshot.json").write_text(
            json.dumps({"canary": CANARY}), encoding="utf-8")
        _session, proposer, report = self.run_scan(_happy_actions())
        self.assertEqual(report["outcome"], "finished")
        self.assertNotIn(CANARY, "\n".join(proposer.prompts))
        self.assertNotIn(scan.CLASSIFICATION_RULE[:40],
                         "\n".join(proposer.prompts))


# ------------------------------------------------ 5. mapping and session IO

class LinkMappingTest(unittest.TestCase):
    def test_exact_title_maps_to_item_link_via_row_or_own_href(self) -> None:
        rows = [
            {"row": 0, "label": "Exfiltrate Your Weights",
             "href": "https://exfil-weights.example/"},
            {"row": 1, "label": "218 comments", "href": "item?id=46100001"},
            {"row": 2, "label": "A text post", "href": "item?id=46200002"},
            {"row": 2, "label": "A text post", "href": "item?id=46200002"},
            {"row": 6, "label": "Mirror story", "href": "https://m.example/"},
            {"row": 7, "label": "3 comments", "href": "item?id=46300003"},
            {"row": 7, "label": "mirrored thread", "href": "/item?id=46300004"},
        ]
        mapping = scan.map_titles_to_hn_links(
            ["Exfiltrate Your Weights", "A text post", "Missing", "Mirror story"],
            rows)
        self.assertEqual(mapping["Exfiltrate Your Weights"], "item?id=46100001")
        self.assertEqual(mapping["A text post"], "item?id=46200002")
        self.assertIsNone(mapping["Missing"])
        self.assertIsNone(mapping["Mirror story"])  # two item links in-window

    def test_item_link_recognizer_rejects_foreign_hosts(self) -> None:
        self.assertTrue(scan.is_hn_item_link("item?id=1"))
        self.assertTrue(scan.is_hn_item_link("/item?id=1"))
        self.assertTrue(scan.is_hn_item_link(scan.HN_ORIGIN + "/item?id=1"))
        self.assertFalse(scan.is_hn_item_link(
            "https://news.ycombinator.com.evil.example/item?id=1"))
        self.assertFalse(scan.is_hn_item_link("https://example.com/item?id=1"))
        self.assertFalse(scan.is_hn_item_link("item?id=abc"))
        self.assertFalse(scan.is_hn_item_link(""))

    def test_session_links_parsing_and_float_scroll_passthrough(self) -> None:
        session = bs.BrowserSession(port=1, scroll_method="dom")
        calls: list = []

        def fake_call(cmd, **fields):
            calls.append((cmd, fields))
            if cmd == "links":
                return {"links": [{"row": 2, "label": "Story", "href": "item?id=5"},
                                  {"row": "x", "label": 3, "href": "h"},
                                  "junk"],
                        "truncated": True}
            return {"pages": fields.get("amount", 0)}

        session._call = fake_call
        payload = session.links()
        self.assertEqual(payload["truncated"], True)
        self.assertEqual(payload["links"],
                         [{"row": 2, "label": "Story", "href": "item?id=5"}])
        session.scroll("down", 0.7)
        self.assertEqual(calls[-1], ("scroll", {"direction": "down",
                                                "amount": 0.7,
                                                "method": "dom"}))
        default = bs.BrowserSession(port=1)
        default._call = fake_call
        default.scroll("down", 2)
        self.assertEqual(calls[-1], ("scroll", {"direction": "down", "amount": 2}))

    def test_helper_source_pins_the_new_capabilities(self) -> None:
        source = (Path(bs.REPO_ROOT) / "tools" / "browser_window.swift"
                  ).read_text(encoding="utf-8")
        self.assertIn('if method == "dom"', source)
        self.assertIn("truncatingRemainder", source)
        self.assertIn("linksCommand", source)
        self.assertIn("window.scrollBy(0,d)", source)


# ---------------------------------------------------- 6. crash-safe report

class CrashSafeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_atomic_write_survives_a_crash(self) -> None:
        target = self.tmp / "out" / "report.json"
        scan.atomic_write_json(target, {"a": 1})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"a": 1})
        self.assertFalse((target.parent / "report.json.tmp").exists())
        with mock.patch("vision_assistant.m022_scan.json.dumps",
                        side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                scan.atomic_write_json(target, {"a": 2})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"a": 1})

    def test_cmd_m022_reports_a_crash_before_any_model_call(self) -> None:
        root = self.tmp / "crash-run"
        args = SimpleNamespace(pin_dir=str(self.tmp / "pin"), ctx_size=8192,
                               reviewer_pages=1, out_dir=str(root),
                               scripted_check=False)
        with mock.patch("vision_assistant.browser_session.compile_helper",
                        side_effect=BrowserError("helper_source_missing")):
            code = browser_cli.cmd_m022(args)
        self.assertEqual(code, 1)
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["outcome"], "failed:exception")
        self.assertEqual(report["fallbacks"], 0)
        self.assertFalse(report["ok"])
        self.assertIsNone(report["result_file"])
        self.assertIn("orphans", report)


if __name__ == "__main__":
    unittest.main()
