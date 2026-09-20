"""M022 dev-set tests: determinism, design invariants, oracle teeth.

Deterministic only — no model, no browser, no external network (one loopback
static-server test binds 127.0.0.1).
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from vision_assistant import browser_cli
from vision_assistant import m022_dev as dev
from vision_assistant import m022_scan as scan
from vision_assistant.browser_session import BrowserError

FROZEN_MANIFEST_SHA256 = (
    "b5aea1718350d961b96c9574377b35acacfe311cfa935caccd080d98f41503be")


class DevSetShapeTest(unittest.TestCase):
    def test_build_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = dev.build_site(Path(tmp) / "a")
            second = dev.build_site(Path(tmp) / "b")
        self.assertEqual(first, second)
        self.assertEqual(first["files"], 6)

    def test_tasks_are_well_formed(self) -> None:
        self.assertEqual(len(dev.DEV_TASKS), 5)
        ids = [task.id for task in dev.DEV_TASKS]
        self.assertEqual(len(set(ids)), 5)
        for task in dev.DEV_TASKS:
            ranks = [row["rank"] for row in task.rows]
            self.assertEqual(ranks, list(range(1, task.size + 1)), task.id)
            titles = [row["title"] for row in task.rows]
            self.assertEqual(len(set(titles)), len(titles), task.id)
            kinds = {row["kind"] for row in task.rows}
            self.assertTrue(kinds <= {"primary", "decoy", "plain"}, task.id)
            primaries = [row for row in task.rows
                         if row["kind"] == "primary"]
            self.assertGreaterEqual(len(primaries), 3, task.id)
            self.assertGreaterEqual(len(task.decoys), 2, task.id)
            combined = " ".join(row["title"] for row in primaries).lower()
            self.assertTrue(
                any(token in combined for token in
                    ("ai", "ml", "llm", "model", "learning", "intelligence",
                     "speech", "robotics")), task.id)

    def test_expected_selection_is_the_three_lowest_primaries(self) -> None:
        for task in dev.DEV_TASKS:
            primaries = sorted((row for row in task.rows
                                if row["kind"] == "primary"),
                               key=lambda row: row["rank"])
            expected = tuple((row["rank"], row["title"])
                             for row in primaries[:3])
            self.assertEqual(task.expected, expected, task.id)
        quad = dev.DEV_TASKS_BY_ID["d22-04"]
        self.assertNotIn(41, [rank for rank, _ in quad.expected])
        self.assertTrue(any("retrieval-augmented" in row["title"]
                            for row in quad.rows))
        self.assertTrue(any(row["rank"] == 41 and row["kind"] == "primary"
                            for row in quad.rows))

    def test_expected_primaries_span_viewports(self) -> None:
        for task in dev.DEV_TASKS:
            bands = {dev.band_for_row(task.document_height,
                                      task.row_top(rank))
                     for rank, _ in task.expected}
            self.assertGreaterEqual(len(bands), task.min_observations, task.id)

    def test_decoys_rank_above_the_third_primary(self) -> None:
        for task in dev.DEV_TASKS:
            third = task.expected[-1][0]
            self.assertLess(min(row["rank"] for row in task.decoys), third,
                            task.id)

    def test_pages_are_multi_viewport_and_fit_budgets(self) -> None:
        for task in dev.DEV_TASKS:
            self.assertGreater(task.document_height, 2 * dev.VIEWPORT_HEIGHT,
                               task.id)
            bands = dev.viewport_bands(task.document_height)
            self.assertGreaterEqual(len(bands), 3, task.id)
            self.assertLessEqual(len(bands), scan.MAX_VIEWPORTS, task.id)
            self.assertLessEqual(2 * len(bands) + 1, scan.MAX_CALLS, task.id)

    def test_manifest_sha_is_pinned(self) -> None:
        self.assertEqual(dev.manifest_sha256(), FROZEN_MANIFEST_SHA256)

    def test_generated_html_contains_ranks_titles_and_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dev.build_site(Path(tmp))
            page = (Path(tmp) / "d22-01" / "index.html").read_text(
                encoding="utf-8")
        self.assertIn("<title>The Long List — d22-01</title>", page)
        self.assertIn("3. ", page)
        self.assertIn("AgentBench: evaluating tool-using assistants", page)
        self.assertIn("(agentbench.example)", page)
        self.assertIn("· 214 points", page)
        self.assertIn("end of list", page)


class OracleTest(unittest.TestCase):
    def _good(self):
        task = dev.DEV_TASKS[0]
        return task, {
            "outcome": "finished",
            "selection": [{"rank": rank, "title": title,
                           "observation_id": "obs-{}".format(
                               1 if rank < 20 else 2)}
                          for rank, title in task.expected],
            "ledger": [1] * len(task.expected),
        }

    def test_correct_selection_passes_and_mutations_fail(self) -> None:
        task, good = self._good()
        self.assertTrue(dev.verify_dev_task(task, good)["ok"])
        mutations = [
            ("missing", good["selection"][:2]),
            ("extra", good["selection"] + [dict(good["selection"][0],
                                                rank=99)]),
            ("wrong title", [dict(good["selection"][0], title="Other")]
             + good["selection"][1:]),
            ("wrong rank", [dict(good["selection"][0], rank=2)]
             + good["selection"][1:]),
            ("collapsed evidence",
             [dict(entry, observation_id="obs-1")
              for entry in good["selection"]]),
        ]
        for label, selection in mutations:
            payload = {**good, "selection": selection}
            verdict = dev.verify_dev_task(task, payload)
            self.assertFalse(verdict["ok"], label)
        stopped = {**good, "outcome": "stopped"}
        self.assertFalse(dev.verify_dev_task(task, stopped)["ok"])

    def test_run_checks_covers_everything(self) -> None:
        checks = dev.run_checks()
        self.assertTrue(checks["ok"], checks["problems"])
        self.assertEqual(checks["tasks"], 5)
        self.assertEqual(checks["manifest_sha256"], FROZEN_MANIFEST_SHA256)
        for info in checks["per_task"].values():
            self.assertEqual(info["problems"], [])
            self.assertGreaterEqual(info["span"], 2)


class DevServerTest(unittest.TestCase):
    def test_server_serves_pages_on_loopback_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dev.build_site(Path(tmp))
            server = dev.DevSiteServer(Path(tmp))
            port = server.start()
            try:
                self.assertEqual(server._httpd.server_address[0], "127.0.0.1")
                with urllib.request.urlopen(
                        "http://127.0.0.1:{}/d22-01/".format(port),
                        timeout=5) as response:
                    body = response.read().decode("utf-8")
                self.assertIn("AgentBench", body)
                with self.assertRaises(Exception):
                    urllib.request.urlopen(
                        "http://127.0.0.1:{}/../etc/passwd".format(port),
                        timeout=5)
            finally:
                server.stop()


class CliTest(unittest.TestCase):
    def test_check_only_gate_runs_end_to_end(self) -> None:
        self.assertEqual(browser_cli.main(["m022-dev", "--check-only"]), 0)

    def test_cli_reports_a_crash_before_any_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "crash-run"
            args = SimpleNamespace(ids="d22-01", check_only=False,
                                   pin_dir=str(Path(tmp) / "pin"),
                                   ctx_size=8192, out_dir=str(root), out="")
            with mock.patch(
                    "vision_assistant.browser_session.compile_helper",
                    side_effect=BrowserError("helper_source_missing")):
                code = browser_cli.cmd_m022_dev(args)
            self.assertEqual(code, 1)
            report = json.loads((root / "summary.json").read_text(
                encoding="utf-8"))
            self.assertEqual(report["aborted"], "exception:BrowserError")
            self.assertEqual(report["model_calls"], 0)
            self.assertEqual(report["fallbacks"], 0)
            self.assertFalse(report["ok"])
            self.assertIn("orphans", report)


if __name__ == "__main__":
    unittest.main()
