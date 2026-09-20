from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from vision_assistant import browser_agent as agent
from vision_assistant import browser_fixtures as fixtures
from vision_assistant import browser_targets as bt
from vision_assistant import browser_tasks as tasks
from vision_assistant.browser_session import BrowserError, Snapshot, TargetList


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


class FakeTargetSession:
    width = 1280
    height = 720

    def __init__(self, tmp: Path, urls, target_script=None):
        self.tmp = tmp
        self.urls = list(urls)
        self.calls: list = []
        self.seq = 0
        self.target_script = list(target_script or [])
        self.fail_click_target = None

    def _default_targets(self) -> TargetList:
        entries = (
            bt.TargetEntry("t1", "link", "Rank three story",
                           (16.0, 100.0, 400.0, 20.0), True, False),
            bt.TargetEntry("t2", "button", "More",
                           (600.0, 300.0, 80.0, 24.0), True, False),
        )
        return TargetList(seq=self.seq, targets=entries, truncated=False,
                          total=len(entries))

    def navigate(self, url: str) -> str:
        self.calls.append(("navigate", url))
        return "http://127.0.0.1:1" + url if url.startswith("/") else url

    def snapshot(self) -> Snapshot:
        self.seq += 1
        url = self.urls.pop(0) if self.urls else "http://127.0.0.1:1/news/"
        path = self.tmp / "shot-{}.png".format(self.seq)
        path.write_bytes(_make_png())
        return Snapshot(seq=self.seq, width=2560, height=1440, scale=2.0,
                        url=url, path=str(path))

    def targets(self) -> TargetList:
        self.calls.append(("targets",))
        item = self.target_script.pop(0) if self.target_script else None
        if item is None:
            return self._default_targets()
        if isinstance(item, Exception):
            raise item
        return item

    def click_target(self, target_id: str) -> str:
        if self.fail_click_target is not None:
            raise BrowserError(self.fail_click_target)
        self.calls.append(("click_target", target_id))
        return ""

    def click(self, px: int, py: int) -> str:
        self.calls.append(("click", px, py))
        return ""

    def type_text(self, text: str) -> int:
        self.calls.append(("type", text))
        return len(text)

    def press_key(self, key: str) -> None:
        self.calls.append(("press", key))

    def scroll(self, direction: str, amount: int) -> int:
        self.calls.append(("scroll", direction, amount))
        return amount

    def back(self) -> str:
        self.calls.append(("back",))
        return ""

    def stop(self) -> None:
        pass


class ScriptedProposer:
    def __init__(self, actions):
        self.actions = list(actions)
        self.prompts: list = []

    def __call__(self, png_bytes, prompt):
        self.prompts.append((len(png_bytes), prompt))
        if not self.actions:
            return None, {"chars": 0}
        return self.actions.pop(0), {"chars": 42}


class TargetLoopBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_target(self, task_id: str, actions, urls, target_script=None, **kwargs):
        spec = tasks.TASKS_BY_ID[task_id]
        session = FakeTargetSession(self.tmp, urls, target_script)
        proposer = ScriptedProposer(actions)
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=fixtures.defaults,
            sleep=lambda seconds: None,
            log=lambda *args, **kw: None,
            limits=agent.LoopLimits(**kwargs) if kwargs else None,
            mode="target",
        )
        return spec, session, proposer, report

    def run_plain(self, task_id: str, actions, urls):
        spec = tasks.TASKS_BY_ID[task_id]
        session = FakeTargetSession(self.tmp, urls)
        proposer = ScriptedProposer(actions)
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=fixtures.defaults,
            sleep=lambda seconds: None,
            log=lambda *args, **kw: None,
        )
        return spec, session, proposer, report


class TargetRoutingTest(TargetLoopBase):
    def test_click_target_routes_by_id_without_coordinates(self) -> None:
        spec, session, proposer, report = self.run_target(
            "02", [{"action": "click_target", "target": "t1"}],
            ["http://127.0.0.1:1/news/", "http://127.0.0.1:1/story/d03/"])
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["mode"], "target")
        self.assertEqual(report["prompt_version"], "m018t-v2")
        self.assertIn(("click_target", "t1"), session.calls)
        self.assertEqual([c for c in session.calls if c[0] == "click"], [])

    def test_prompt_carries_current_target_table(self) -> None:
        spec, session, proposer, report = self.run_target(
            "11", [{"action": "stop"}], ["http://127.0.0.1:1/search/"])
        self.assertEqual(report["outcome"], "stopped")
        _size, prompt = proposer.prompts[0]
        self.assertIn("Targets (2).", prompt)
        self.assertIn('"id": "t1"', prompt)
        self.assertIn('"id": "t2"', prompt)
        self.assertIn("click_target", prompt)

    def test_already_satisfied_finishes_without_model_calls_or_targets(self) -> None:
        spec, session, proposer, report = self.run_target(
            "01", [], ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["calls"], 0)
        self.assertEqual(proposer.prompts, [])
        self.assertEqual([c for c in session.calls if c[0] == "targets"], [])

    def test_targets_failure_counts_as_infrastructure(self) -> None:
        spec = tasks.TASKS_BY_ID["02"]
        session = FakeTargetSession(
            self.tmp, ["http://127.0.0.1:1/news/"] * 2,
            [BrowserError("targets_unreadable")] * 3)
        proposer = ScriptedProposer([{"action": "stop"}] * 3)
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=fixtures.defaults,
            sleep=lambda seconds: None, log=lambda *args, **kw: None,
            mode="target")
        self.assertEqual(report["outcome"], "failed:infrastructure")
        self.assertEqual(proposer.prompts, [])


class TargetRejectionTest(TargetLoopBase):
    def test_raw_click_is_rejected_in_target_mode(self) -> None:
        spec, session, proposer, report = self.run_target(
            "02",
            [{"action": "click", "x": 40, "y": 20},
             {"action": "click", "x": 40, "y": 20},
             {"action": "click", "x": 40, "y": 20}],
            ["http://127.0.0.1:1/news/"] * 2)
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        self.assertEqual([c for c in session.calls if c[0] == "click"], [])
        rows = [row for row in report["steps"]
                if row.get("kind") == "proposal" and not row.get("parsed")]
        self.assertEqual(len(rows), 3)
        self.assertIn("raw click", rows[0].get("error", ""))

    def test_unknown_target_id_rejected_at_validation(self) -> None:
        spec, session, proposer, report = self.run_target(
            "02", [{"action": "click_target", "target": "t9"}] * 3,
            ["http://127.0.0.1:1/news/"] * 2)
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        self.assertEqual([c for c in session.calls if c[0] == "click_target"], [])
        rows = [row for row in report["steps"]
                if row.get("kind") == "proposal" and not row.get("parsed")]
        self.assertIn("unknown target id", rows[0].get("error", ""))

    def test_adapter_refusal_feeds_history_and_recovery(self) -> None:
        spec = tasks.TASKS_BY_ID["02"]
        session = FakeTargetSession(self.tmp, ["http://127.0.0.1:1/news/"] * 2)
        session.fail_click_target = "refused_target_moved"
        proposer = ScriptedProposer(
            [{"action": "click_target", "target": "t1"}] * 3)
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=fixtures.defaults,
            sleep=lambda seconds: None, log=lambda *args, **kw: None,
            mode="target")
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        refusals = [row for row in report["steps"] if row.get("refused")]
        self.assertEqual(len(refusals), 3)
        self.assertTrue(all(row["refused"] == "refused_target_moved"
                            for row in refusals))

    def test_click_target_rejected_in_screenshot_mode(self) -> None:
        spec, session, proposer, report = self.run_plain(
            "02", [{"action": "click_target", "target": "t1"}] * 3,
            ["http://127.0.0.1:1/news/"] * 2)
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        self.assertEqual([c for c in session.calls if c[0] == "click_target"], [])
        rows = [row for row in report["steps"]
                if row.get("kind") == "proposal" and not row.get("parsed")]
        self.assertIn("not available", rows[0].get("error", ""))


class TargetGuardsTest(TargetLoopBase):
    def test_budget_calls_holds_in_target_mode(self) -> None:
        spec, session, proposer, report = self.run_target(
            "02", [{"action": "wait"}], ["http://127.0.0.1:1/news/"] * 2,
            max_calls=1)
        self.assertEqual(report["outcome"], "failed:budget_calls")

    def test_identical_target_clicks_block_no_progress(self) -> None:
        spec, session, proposer, report = self.run_target(
            "02",
            [{"action": "click_target", "target": "t1"},
             {"action": "click_target", "target": "t1"}],
            ["http://127.0.0.1:1/news/", "http://127.0.0.1:1/news/",
             "http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "blocked:no_progress")

    def test_screenshot_mode_default_is_unchanged_and_labelled(self) -> None:
        spec, session, proposer, report = self.run_plain(
            "02", [{"action": "click", "x": 40, "y": 20}],
            ["http://127.0.0.1:1/news/", "http://127.0.0.1:1/story/d03/"])
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["mode"], "screenshot")
        self.assertEqual(report["prompt_version"], "m018d-v3")
        # model pixel 40 of 64 -> 1600 of 2560 -> css 800 (baseline mapping)
        self.assertIn(("click", 1600, 800), session.calls)
        self.assertEqual([c for c in session.calls if c[0] == "targets"], [])

    def test_invalid_mode_is_rejected(self) -> None:
        spec = tasks.TASKS_BY_ID["02"]
        with self.assertRaises(ValueError):
            agent.run_task(spec, session=None, proposer=None,
                           server_state_provider=fixtures.defaults,
                           mode="hybrid")


if __name__ == "__main__":
    unittest.main()
