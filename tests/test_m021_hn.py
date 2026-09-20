"""M021 focused tests: read-only live Hacker News transfer (deterministic).

Proves, without any model, browser, or network: (1) answer mode exposes no
click/type/navigation action; (2) target lists are never requested or sent;
(3) the result schema validates and rejects structural violations (duplicate
ranks/urls, ordering, target ids, count mismatches); (4) scroll and call
budgets bound the run; (5) duplicate/unsupported answers are refused with
feedback before execution; (6) reviewer data can never enter the prompt;
(7) the origin policy is Hacker-News-only; (8) report writing is crash-safe.
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

from vision_assistant import browser_agent as agent
from vision_assistant import browser_cli
from vision_assistant import browser_session as bs
from vision_assistant import browser_tasks as tasks
from vision_assistant import m021_hn as m021
from vision_assistant.browser_session import BrowserError, Snapshot

FROZEN_GOAL_SHA256 = (
    "867b5b42e6669ce583920d207e8ba1477e93708899f27cd4293501c830835afc")


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


VALID_ANSWER = {
    "found": 3,
    "stories": [
        {"rank": 1, "title": "Local models get a benchmark",
         "url": "arxiv.org", "points": 412, "reason": "LLM benchmark"},
        {"rank": 3, "title": "Agent harness released",
         "url": "github.com", "points": 171, "reason": "agent product"},
        {"rank": 5, "title": "Scaling laws revisited",
         "url": "openai.com", "reason": "research result"},
    ],
}


def _stories(*ranks):
    return {"found": len(ranks),
            "stories": [{"rank": rank, "title": "T{}".format(rank),
                         "url": "d{}.example".format(index), "reason": "why"}
                        for index, rank in enumerate(ranks)]}


class FakeReadSession:
    """Read-only fake: targets() records the call and raises if ever used."""

    width = 1280
    height = 720

    def __init__(self, tmp: Path, page=None):
        self.tmp = tmp
        self.calls: list = []
        self.seq = 0
        self.scroll_y = 0
        self.states = 0
        self.page = dict(page if page is not None else
                         {"scrollY": 0, "scrollHeight": 5300,
                          "innerHeight": 720})

    def navigate(self, url: str) -> str:
        self.calls.append(("navigate", url))
        return url

    def snapshot(self) -> Snapshot:
        self.seq += 1
        path = self.tmp / "shot-{}.png".format(self.seq)
        path.write_bytes(_make_png())
        return Snapshot(seq=self.seq, width=2560, height=1440, scale=2.0,
                        url=m021.START_URL, path=str(path))

    def targets(self):
        self.calls.append(("targets",))
        raise AssertionError("targets() must never be called in a read-only run")

    def scroll(self, direction: str, amount: int) -> int:
        self.calls.append(("scroll", direction, amount))
        self.scroll_y += amount * 720
        self.page = {"scrollY": self.scroll_y, "scrollHeight": 5300,
                     "innerHeight": 720}
        return amount

    def state(self) -> dict:
        self.states += 1
        return {"page": dict(self.page), "url": m021.START_URL}

    def stop(self) -> None:
        pass


class ScriptedProposer:
    def __init__(self, actions):
        self.actions = list(actions)
        self.prompts: list = []

    def __call__(self, png_bytes, prompt):
        self.prompts.append(prompt)
        if not self.actions:
            return None, {"chars": 0}
        item = self.actions.pop(0)
        if callable(item):
            item = item(prompt)
        return item, {"chars": 42}


def _finish(answer):
    return {"action": "finish_answer", "answer": answer}


class ReadOnlyLoopBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_readonly(self, actions, *, session=None, spec=None, verifier=None,
                     limits=None, exempt=("scroll", "wait")):
        session = session or FakeReadSession(self.tmp)
        proposer = ScriptedProposer(actions)
        report = agent.run_task(
            spec or m021.hn_spec(), session=session, proposer=proposer,
            server_state_provider=lambda: {},
            sleep=lambda seconds: None, log=lambda *args, **kw: None,
            limits=limits or agent.LoopLimits(
                max_steps=m021.MAX_CALLS, max_calls=m021.MAX_CALLS,
                max_seconds=m021.MAX_SECONDS, max_scrolls=m021.MAX_SCROLLS),
            mode="typed", verifier=verifier or m021.verify_m021,
            exempt_actions=exempt)
        return session, proposer, report


# ------------------------------------------------------------ (1) no actions

class AnswerModeCapabilityTest(unittest.TestCase):
    def test_manifest_excludes_every_interaction_action(self) -> None:
        manifest = tasks.capability_manifest("answer")
        self.assertEqual(manifest["allowed_actions"],
                         ["scroll", "wait", "finish_answer", "stop"])
        for kind in ("click_target", "fill_field", "select_option",
                     "set_toggle", "save_form", "back", "finish"):
            self.assertIn(kind, manifest["unavailable_actions"])

    def test_action_schema_has_no_interaction_or_target_fields(self) -> None:
        schema = m021.action_schema()
        branches = [branch["properties"]["action"]["enum"][0]
                    for branch in schema["oneOf"]]
        self.assertEqual(branches, ["scroll", "wait", "finish_answer", "stop"])
        forbidden = {"target_ref", "observation_id", "text", "option", "value",
                     "expected_change", "url", "x", "y", "key"}
        for branch in schema["oneOf"]:
            self.assertIs(branch["additionalProperties"], False)
            self.assertFalse(forbidden & set(branch["properties"]))

    def test_validator_refuses_interaction_kinds_in_answer_mode(self) -> None:
        payloads = (
            {"kind": "click_target", "target_ref": "ui:3",
             "observation_id": "obs-1"},
            {"kind": "fill_field", "target_ref": "ui:1", "text": "hi",
             "observation_id": "obs-1"},
            {"kind": "select_option", "target_ref": "ui:1", "option": "x",
             "observation_id": "obs-1"},
            {"kind": "set_toggle", "target_ref": "ui:1", "value": True,
             "observation_id": "obs-1"},
            {"kind": "save_form", "target_ref": "ui:1",
             "observation_id": "obs-1"},
            {"kind": "back"},
            {"kind": "finish"},
        )
        for payload in payloads:
            parsed, error = tasks.validate_typed_action(payload, mode="answer")
            self.assertIsNone(parsed, payload)
            self.assertIn("not available in 'answer' mode", error)

    def test_frozen_spec_and_limits(self) -> None:
        spec = m021.hn_spec()
        self.assertEqual(spec.mode, "answer")
        self.assertFalse(spec.observe_targets)
        self.assertTrue(spec.page_metrics)
        self.assertEqual(spec.start, "https://news.ycombinator.com/")
        self.assertEqual((m021.MAX_SCROLLS, m021.MAX_CALLS,
                          m021.MAX_SECONDS, m021.CTX_SIZE),
                         (4, 8, 120.0, 8192))
        self.assertEqual(m021.goal_sha256(), FROZEN_GOAL_SHA256)
        self.assertIn("three", m021.GOAL.lower())


# ------------------------------------------------- (2) targets never sent

class TargetFreeObservationTest(ReadOnlyLoopBase):
    def test_run_never_requests_targets_and_omits_target_block(self) -> None:
        session, proposer, report = self.run_readonly([_finish(VALID_ANSWER)])
        self.assertEqual(report["outcome"], "finished")
        self.assertNotIn(("targets",), session.calls)
        for prompt in proposer.prompts:
            self.assertNotIn('"ui:', prompt)
            self.assertNotIn("target_ref", prompt)
            self.assertNotIn("obs-", prompt)
            self.assertNotIn("Observation:", prompt)
            self.assertNotIn("ui:N", prompt)
        self.assertIn("finish_answer", proposer.prompts[0])

    def test_scroll_position_is_reported_in_the_prompt(self) -> None:
        session, proposer, report = self.run_readonly(
            [{"action": "scroll", "direction": "down", "amount": 1},
             _finish(VALID_ANSWER)])
        self.assertEqual(report["outcome"], "finished")
        self.assertIn("Scroll position: y=0 CSS pixels of 5300",
                      proposer.prompts[0])
        self.assertIn("y=720 CSS pixels", proposer.prompts[1])
        self.assertIn("4 scrolls", proposer.prompts[0])
        self.assertIn("3 scrolls", proposer.prompts[1])
        pages = [step for step in report["steps"] if step.get("kind") == "page"]
        self.assertTrue(pages)
        self.assertEqual(pages[-1]["scroll_y"], 720)
        self.assertGreaterEqual(session.states, 2)

    def test_no_change_guard_never_fires_on_readonly_scrolls(self) -> None:
        session, _proposer, report = self.run_readonly(
            [{"action": "scroll", "direction": "down", "amount": 1},
             {"action": "scroll", "direction": "down", "amount": 1},
             {"action": "wait"},
             _finish(VALID_ANSWER)]
        )
        self.assertEqual(report["outcome"], "finished")
        self.assertFalse([step for step in report["steps"]
                          if step.get("kind") == "no_change"])


# ----------------------------------------------------- (3) schema validation

class AnswerValidationTest(unittest.TestCase):
    def test_valid_answers_pass(self) -> None:
        clean, error = m021.validate_m021_answer(VALID_ANSWER)
        self.assertIsNone(error)
        self.assertEqual(clean, VALID_ANSWER)
        for answer in (_stories(2, 5, 9), _stories(2, 5), _stories()):
            _clean, error = m021.validate_m021_answer(answer)
            self.assertIsNone(error, answer)

    def test_structural_violations_rejected(self) -> None:
        duplicate = _stories(5, 5)
        descending = _stories(5, 2)
        cases = (
            ({"stories": [], "found": 3}, "must equal"),
            ({"found": 2, "stories": []}, "must equal"),
            ({"found": 4, "stories": []}, "between 0 and 3"),
            ({"stories": []}, "missing answer field"),
            ({"found": 0, "stories": [], "observed_at": "x"},
             "unexpected answer field"),
            ({"found": True, "stories": []}, "must be an integer"),
            ({"found": 0, "stories": "x"}, "stories must be a list"),
            ({"found": 1, "stories": ["x"]}, "must be an object"),
            ({"found": 1, "stories": [{"rank": True, "title": "T",
                                       "url": "a", "reason": "r"}]},
             "rank must be an integer"),
            ({"found": 1, "stories": [{"rank": 0, "title": "T",
                                       "url": "a", "reason": "r"}]},
             "rank must be >= 1"),
            (duplicate, "duplicate rank 5"),
            (descending, "strictly increase"),
            ({"found": 1, "stories": [{"rank": 1, "title": "  ",
                                       "url": "a", "reason": "r"}]},
             "must not be empty"),
            ({"found": 1, "stories": [{"rank": 1, "title": "T",
                                       "url": "a"}]}, "missing field"),
            ({"found": 1, "stories": [{"rank": 1, "title": "T", "url": "a",
                                       "reason": "r", "score": 1}]},
             "unexpected field"),
            ({"found": 1, "stories": [{"rank": 1, "title": "T",
                                       "url": "a", "reason": "r",
                                       "points": "9"}]},
             "points must be an integer"),
            ({"found": 1, "stories": [{"rank": 1, "title": "T",
                                       "url": "a", "reason": "r",
                                       "points": -1}]}, "points must be >= 0"),
            ({"found": 2, "stories": [{"rank": 1, "title": "T", "url": "a",
                                       "reason": "r"},
                                      {"rank": 2, "title": "T2", "url": "A",
                                       "reason": "r2"}]}, "duplicate url"),
            ({"found": 1, "stories": [{"rank": 1, "title": "ui:3",
                                       "url": "a", "reason": "r"}]},
             "ui: target reference"),
            ({"found": 1, "stories": [{"rank": 1, "title": "T", "url": "t7",
                                       "reason": "r"}]}, "target id"),
            ({"found": 1, "stories": [{"rank": 1, "title": "T", "url": "a",
                                       "reason": "bad\x07"}]},
             "control characters"),
            ({"found": 1, "stories": [{"rank": 1, "title": "x" * 400,
                                       "url": "a", "reason": "r"}]},
             "too long"),
        )
        for answer, needle in cases:
            parsed, error = m021.validate_m021_answer(answer)
            self.assertIsNone(parsed, answer)
            self.assertIn(needle, error, answer)

    def test_verify_m021_requires_finished_answer_and_no_side_effects(self) -> None:
        spec = m021.hn_spec()
        base = {"external_visits": 0, "credential_typed": False,
                "submission_attempts": 0}
        ok = m021.verify_m021(spec, dict(base, outcome="finished",
                                         answer=VALID_ANSWER))
        self.assertTrue(ok["ok"], ok)
        missing = m021.verify_m021(spec, dict(base, outcome="finished",
                                              answer=None))
        self.assertFalse(missing["ok"])
        self.assertIn("answer: missing", missing["failures"])
        early = m021.verify_m021(spec, dict(base, outcome="finished",
                                            answer=None))
        self.assertFalse(early["ok"])
        dirty = m021.verify_m021(spec, dict(base, outcome="finished",
                                            answer=VALID_ANSWER,
                                            submission_attempts=1))
        self.assertFalse(dirty["ok"])
        self.assertTrue(any("side-effects" in item
                            for item in dirty["failures"]))


# -------------------------------------------------- (4) budgets and (5) loop

class BudgetAndFeedbackTest(ReadOnlyLoopBase):
    def test_scroll_budget_refuses_fifth_scroll_then_recovers(self) -> None:
        scroll = {"action": "scroll", "direction": "down", "amount": 1}
        session, _proposer, report = self.run_readonly(
            [scroll] * 5 + [_finish(VALID_ANSWER)])
        self.assertEqual(len([call for call in session.calls
                              if call[0] == "scroll"]), 4)
        self.assertEqual(report["scrolls"], 4)
        refused = [step for step in report["steps"]
                   if step.get("refused") == "budget_scrolls"]
        self.assertTrue(refused)
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["final_answer"], VALID_ANSWER)

    def test_persistent_scrolling_terminates_within_budgets(self) -> None:
        scroll = {"action": "scroll", "direction": "down", "amount": 1}
        session, _proposer, report = self.run_readonly([scroll] * 8)
        self.assertEqual(len([call for call in session.calls
                              if call[0] == "scroll"]), 4)
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        self.assertLessEqual(report["calls"], m021.MAX_CALLS)

    def test_call_budget_caps_the_run(self) -> None:
        wait = {"action": "wait"}
        session, proposer, report = self.run_readonly([wait] * 10)
        self.assertEqual(report["calls"], m021.MAX_CALLS)
        self.assertEqual(len(proposer.prompts), m021.MAX_CALLS)
        self.assertEqual(report["outcome"], "failed:budget_steps")

    def test_duplicate_rank_answer_refused_then_corrected(self) -> None:
        session, proposer, report = self.run_readonly(
            [_finish(_stories(5, 5)), _finish(VALID_ANSWER)])
        self.assertEqual(report["outcome"], "finished")
        errors = [step.get("error") for step in report["steps"]
                  if step.get("kind") == "proposal" and step.get("error")]
        self.assertTrue(any("duplicate rank" in str(error)
                            for error in errors), errors)
        self.assertIn("duplicate rank", proposer.prompts[1])
        self.assertEqual(report["final_answer"], VALID_ANSWER)

    def test_found_mismatch_refused_then_corrected(self) -> None:
        _session, proposer, report = self.run_readonly(
            [_finish({"found": 3, "stories": []}), _finish(VALID_ANSWER)])
        self.assertEqual(report["outcome"], "finished")
        self.assertIn("must equal the number of stories", proposer.prompts[1])

    def test_verifier_failure_marks_finish_unverified(self) -> None:
        def verifier(_spec, _state):
            return {"ok": False, "task": "m021-hn", "failures": ["forced"],
                    "failed_checks": 1}

        _session, _proposer, report = self.run_readonly(
            [_finish(VALID_ANSWER)], verifier=verifier)
        self.assertEqual(report["outcome"], "failed:finish_unverified")


# ------------------------------------------------ (6) reviewer data isolation

class ReviewerIsolationTest(ReadOnlyLoopBase):
    def test_reviewer_canary_never_reaches_the_prompt(self) -> None:
        canary = "CANARY-REVIEWER-9F31"
        root = self.tmp / "m021-hn-run"
        reviewer = root / "reviewer"
        reviewer.mkdir(parents=True)
        (reviewer / "snapshot.json").write_text(
            json.dumps({"canary": canary, "truth": "ranks 1,3,5"}),
            encoding="utf-8")
        (reviewer / "snapshot-01.png").write_bytes(_make_png())
        session, proposer, report = self.run_readonly(
            [{"action": "scroll", "direction": "down", "amount": 1},
             _finish(VALID_ANSWER)])
        self.assertEqual(report["outcome"], "finished")
        joined = "\n".join(proposer.prompts)
        self.assertNotIn(canary, joined)
        self.assertNotIn("reviewer", joined.lower())
        self.assertNotIn(m021.CLASSIFICATION_RULE[:40], joined)
        self.assertNotIn("Frozen before the run", joined)


# --------------------------------------------------------- (7) origin policy

class ScrollDeliveryTest(unittest.TestCase):
    def test_session_scroll_passes_dom_method_only_when_configured(self) -> None:
        calls: list = []

        def fake_call(cmd, **fields):
            calls.append((cmd, fields))
            return {"pages": int(fields.get("amount", 0))}

        dom = bs.BrowserSession(port=1, scroll_method="dom")
        dom._call = fake_call
        dom.scroll("down", 2)
        self.assertEqual(calls[0][0], "scroll")
        self.assertEqual(calls[0][1].get("method"), "dom")
        default = bs.BrowserSession(port=1)
        default._call = fake_call
        default.scroll("down", 1)
        self.assertNotIn("method", calls[1][1])
        dom.scroll("up", 1, method="keys")
        self.assertEqual(calls[2][1].get("method"), "keys")

    def test_helper_dom_scroll_path_is_pinned(self) -> None:
        source = (Path(bs.REPO_ROOT) / "tools" / "browser_window.swift"
                  ).read_text(encoding="utf-8")
        self.assertIn('if method == "dom"', source)
        self.assertIn("window.scrollBy(0,d)", source)

    def test_m021_cli_sessions_use_dom_scrolling(self) -> None:
        source = (Path(bs.REPO_ROOT) / "src" / "vision_assistant" /
                  "browser_cli.py").read_text(encoding="utf-8")
        section = source.split("def cmd_m021")[1].split(
            "def _m022_scripted_check")[0]
        self.assertEqual(section.count('scroll_method="dom"'), 2)


class OriginPolicyTest(unittest.TestCase):
    def test_session_origin_policy_is_hacker_news_only(self) -> None:
        session = bs.BrowserSession(port=1234,
                                    live_origins=(m021.HN_ORIGIN,))
        self.assertTrue(session._origin_allowed(m021.START_URL))
        self.assertTrue(session._origin_allowed(m021.HN_ORIGIN + "/news"))
        self.assertTrue(session._origin_allowed(m021.HN_ORIGIN + "?x=1"))
        self.assertFalse(session._origin_allowed(
            "https://news.ycombinator.com.evil.example/"))
        self.assertFalse(session._origin_allowed("http://news.ycombinator.com/"))
        self.assertFalse(session._origin_allowed("https://evil.example/"))
        self.assertFalse(session._origin_allowed(
            "https://news.ycombinator.com@evil.example/"))

    def test_helper_live_host_gate_is_pinned(self) -> None:
        source = (Path(bs.REPO_ROOT) / "tools" / "browser_window.swift"
                  ).read_text(encoding="utf-8")
        self.assertIn("url.host == live", source)
        self.assertIn('url.scheme == "https"', source)
        self.assertIn('"--live-host"', source)

    def test_origin_literal_is_assembled_from_parts(self) -> None:
        self.assertEqual(m021.HN_ORIGIN, "https://" + m021.HN_HOST)
        self.assertEqual(m021.START_URL, "https://news.ycombinator.com/")


# ----------------------------------------------- (8) crash-safe reporting

class CrashSafeReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_atomic_write_survives_a_crash_and_leaves_no_litter(self) -> None:
        target = self.tmp / "out" / "report.json"
        m021.atomic_write_json(target, {"a": 1})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"a": 1})
        self.assertFalse((target.parent / "report.json.tmp").exists())
        with mock.patch("vision_assistant.m021_hn.json.dumps",
                        side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                m021.atomic_write_json(target, {"a": 2})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"a": 1})

    def test_result_document_carries_trusted_timestamp(self) -> None:
        doc = m021.result_document(VALID_ANSWER, "2026-09-20T12:00:00Z")
        self.assertEqual(doc["stories"], VALID_ANSWER["stories"])
        self.assertEqual(doc["found"], 3)
        self.assertEqual(doc["observed_at"], "2026-09-20T12:00:00Z")
        empty = m021.result_document(None, "2026-09-20T12:00:00Z")
        self.assertEqual(empty["stories"], [])
        self.assertIsNone(empty["found"])

    def test_cmd_m021_reports_a_crash_before_any_model_call(self) -> None:
        root = self.tmp / "crash-run"
        args = SimpleNamespace(pin_dir=str(self.tmp / "pin"),
                               ctx_size=8192, reviewer_pages=1,
                               out_dir=str(root))
        with mock.patch("vision_assistant.browser_session.compile_helper",
                        side_effect=BrowserError("helper_source_missing")):
            code = browser_cli.cmd_m021(args)
        self.assertEqual(code, 1)
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["outcome"], "failed:exception")
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(report["fallbacks"], 0)
        self.assertFalse(report["ok"])
        self.assertIsNone(report["result_file"])
        self.assertIn("orphans", report)


if __name__ == "__main__":
    unittest.main()
