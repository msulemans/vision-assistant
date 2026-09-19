from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from vision_assistant import browser_agent as agent
from vision_assistant import browser_fixtures as fixtures
from vision_assistant import browser_tasks as tasks
from vision_assistant.browser_session import BrowserError, Snapshot


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


class FakeSession:
    width = 1280
    height = 720

    def __init__(self, tmp: Path, urls):
        self.tmp = tmp
        self.urls = list(urls)
        self.calls: list = []
        self.seq = 0
        self.click_error = None

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

    def click(self, px: int, py: int) -> str:
        if self.click_error is not None:
            raise BrowserError(self.click_error)
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


class LoopBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_spec(self, task_id: str, actions, urls, **kwargs):
        spec = tasks.TASKS_BY_ID[task_id]
        session = FakeSession(self.tmp, urls)
        proposer = ScriptedProposer(actions)
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=fixtures.defaults,
            sleep=lambda seconds: None,
            log=lambda *args, **kw: None,
            limits=agent.LoopLimits(**kwargs) if kwargs else None,
        )
        return spec, session, proposer, report


class LoopFlowTest(LoopBase):
    def test_already_satisfied_task_finishes_without_model_calls(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "01", [], ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["calls"], 0)
        self.assertEqual(proposer.prompts, [])
        self.assertTrue(report["oracle"]["ok"])

    def test_click_then_navigation_finishes(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "02",
            [{"action": "click", "x": 40, "y": 20}],
            ["http://127.0.0.1:1/news/", "http://127.0.0.1:1/story/d03/"],
        )
        self.assertEqual(report["outcome"], "finished")
        self.assertEqual(report["calls"], 1)
        self.assertEqual(report["actions"], 1)
        # model pixel 40 of 64 -> 1600 of 2560 -> css 800
        self.assertEqual(session.calls[-1], ("click", 1600, 800))
        self.assertIn("/story/d03/", report["visited"])

    def test_wrong_finish_is_a_failure(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "21",
            [{"action": "finish", "answer": {"rank": 1, "title": "x"}}],
            ["http://127.0.0.1:1/news/"],
        )
        self.assertEqual(report["outcome"], "failed:finish_unverified")
        self.assertFalse(report["oracle"]["ok"])

    def test_correct_finish_passes(self) -> None:
        answer = dict(tasks.TASKS_BY_ID["21"].expected["answer"])
        spec, session, proposer, report = self.run_spec(
            "21", [{"action": "finish", "answer": answer}],
            ["http://127.0.0.1:1/news/"])
        self.assertEqual(report["outcome"], "finished")
        self.assertTrue(report["oracle"]["ok"])

    def test_stop_is_terminal(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "11", [{"action": "stop"}], ["http://127.0.0.1:1/search/"])
        self.assertEqual(report["outcome"], "stopped")


class LoopGuardTest(LoopBase):
    def test_invalid_proposals_exhaust_recovery(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "11", [None, None, None], ["http://127.0.0.1:1/search/"])
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        self.assertEqual(report["calls"], 3)

    def test_refusals_exhaust_recovery(self) -> None:
        spec = tasks.TASKS_BY_ID["11"]
        session = FakeSession(self.tmp, ["http://127.0.0.1:1/search/"] * 4)
        session.click_error = "refused_stale"
        proposer = ScriptedProposer(
            [{"action": "click", "x": 10, "y": 10}] * 3)
        report = agent.run_task(
            spec, session=session, proposer=proposer,
            server_state_provider=fixtures.defaults,
            sleep=lambda seconds: None, log=lambda *a, **k: None)
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        # Refused attempts still consume the step budget.
        self.assertEqual(report["actions"], 3)
        refusals = [row for row in report["steps"] if row.get("refused")]
        self.assertEqual(len(refusals), 3)

    def test_budget_calls_stops_the_loop(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "11", [None, None, None], ["http://127.0.0.1:1/search/"],
            max_calls=1)
        self.assertEqual(report["outcome"], "failed:budget_calls")
        self.assertEqual(report["calls"], 1)

    def test_budget_seconds_stops_the_loop(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "11", [{"action": "wait"}], ["http://127.0.0.1:1/search/"],
            max_seconds=0)
        self.assertEqual(report["outcome"], "failed:budget_seconds")

    def test_identical_outcomes_block_no_progress(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "11",
            [{"action": "click", "x": 10, "y": 10},
             {"action": "click", "x": 10, "y": 10}],
            ["http://127.0.0.1:1/search/", "http://127.0.0.1:1/search/",
             "http://127.0.0.1:1/search/"],
        )
        self.assertEqual(report["outcome"], "blocked:no_progress")

    def test_validate_rejects_foreign_navigation(self) -> None:
        spec, session, proposer, report = self.run_spec(
            "11", [{"action": "navigate", "url": "https://evil.example/"}],
            ["http://127.0.0.1:1/search/"])
        self.assertEqual(report["outcome"], "blocked:recovery_exhausted")
        kinds = [call[0] for call in session.calls]
        self.assertNotIn("navigate", kinds[1:])  # only the startup navigate


class PromptAndMappingTest(unittest.TestCase):
    def test_prompt_carries_geometry_goal_and_capped_history(self) -> None:
        history = ["step {} -> /x/".format(n) for n in range(10)]
        prompt = agent.build_loop_prompt("Find the story.", 2304, 1296, 1280, 720,
                                         history)
        self.assertIn("Find the story.", prompt)
        self.assertIn("2304x1296", prompt)
        self.assertIn("1280x720", prompt)
        self.assertIn("step 9", prompt)
        self.assertNotIn("step 2", prompt)

    def test_model_to_screenshot_maps_and_clamps(self) -> None:
        self.assertEqual(agent.model_to_screenshot(100, 50, 2304, 1296, 2560, 1440),
                         (111, 56))
        self.assertEqual(agent.model_to_screenshot(-5, -5, 2304, 1296, 2560, 1440),
                         (0, 0))
        self.assertEqual(agent.model_to_screenshot(99999, 99999, 2304, 1296,
                                                   2560, 1440),
                         (2559, 1439))

    def test_extract_json_object(self) -> None:
        self.assertEqual(agent.extract_json_object('{"action":"back"}'),
                         {"action": "back"})
        self.assertEqual(
            agent.extract_json_object('noise {"action":"click","x":1,"y":2} tail'),
            {"action": "click", "x": 1, "y": 2})
        self.assertIsNone(agent.extract_json_object("no object here [1,2]"))

    def test_agent_module_is_inert(self) -> None:
        source = Path(agent.__file__).read_text(encoding="utf-8")
        for token in ("subprocess", "NSEvent", "sendEvent", "CGEvent",
                      "pyautogui", "pynput", "osascript", "socket", "urllib"):
            self.assertNotIn(token, source, token)


if __name__ == "__main__":
    unittest.main()
