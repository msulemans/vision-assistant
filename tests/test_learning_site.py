from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEARNING = ROOT / "learning"


class PageAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.local_assets: list[str] = []
        self.external_assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        candidate = values.get("src") if tag == "script" else values.get("href")
        if not candidate or candidate.startswith("#"):
            return
        if candidate.startswith(("http://", "https://", "//")):
            self.external_assets.append(candidate)
        else:
            self.local_assets.append(candidate)


class LearningSiteContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (LEARNING / "index.html").read_text(encoding="utf-8")
        self.css = (LEARNING / "styles.css").read_text(encoding="utf-8")
        self.js = (LEARNING / "app.js").read_text(encoding="utf-8")
        self.audit = PageAudit()
        self.audit.feed(self.html)

    def test_all_assets_are_local_and_present(self) -> None:
        self.assertEqual(self.audit.external_assets, [])
        for asset in self.audit.local_assets:
            with self.subTest(asset=asset):
                self.assertTrue((LEARNING / asset).resolve().is_file())

    def test_ids_are_unique_and_interactive_surfaces_exist(self) -> None:
        self.assertEqual(len(self.audit.ids), len(set(self.audit.ids)))
        required = {
            "screenSpecimen",
            "stageReader",
            "traceEvents",
            "captureCommand",
            "milestoneMap",
            "milestoneReader",
            "glossarySearch",
            "flashcard",
            "quiz",
            "waterfall",
            "waterfallStats",
            "compareBody",
            "failureSearch",
            "failureList",
            "failureComponents",
            "teachBackList",
            "commandList",
        }
        self.assertTrue(required.issubset(self.audit.ids))

    def test_current_evidence_and_honest_boundaries_are_visible(self) -> None:
        for phrase in (
            "Roadmap · complete",
            "392 passing · 386 product + 6 learning",
            "pinned, local",
            "Intentionally absent",
            "selection_timed_out",
            "User-selected capture: passed twice",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.html)

    def test_all_seventeen_milestones_are_registered_once(self) -> None:
        ids = [int(value) for value in re.findall(r"\{ id: (\d+), phase:", self.js)]
        self.assertEqual(ids, list(range(1, 18)))
        self.assertIn('status: "done", title: "Frozen screen-understanding corpus"', self.js)
        self.assertIn('status: "done", title: "Local VLM and runtime bake-off"', self.js)
        self.assertIn('status: "done", title: "One-shot local Vision Assistant"', self.js)
        self.assertIn('status: "done", title: "Evidence augmentation and focused re-observation"', self.js)
        self.assertIn('status: "done", title: "Multi-turn visual conversation"', self.js)
        self.assertIn('status: "done", title: "Usable capture and answer UI"', self.js)
        self.assertIn('status: "done", title: "Typed action intents and policy—no execution"', self.js)
        self.assertIn('status: "done", title: "Disposable simulated action loop"', self.js)
        self.assertIn('status: "done", title: "Read-only macOS UI grounding"', self.js)
        self.assertIn('status: "done", title: "Supervised mouse and keyboard execution"', self.js)
        self.assertIn('status: "done", title: "Recovery and bounded task agent"', self.js)
        self.assertIn('status: "done", title: "Profiles, packaging, and offline verification"', self.js)
        self.assertIn('status: "done", title: "Evaluation and reciprocal learning field manual"', self.js)
        self.assertIn('status: "done", title: "Public beta hardening"', self.js)
        self.assertNotIn('status: "current"', self.js)

    def test_accessibility_and_reduced_motion_contracts_exist(self) -> None:
        self.assertIn("skip-link", self.html)
        self.assertIn("aria-live", self.html)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("prefers-reduced-motion", self.css)

    def test_learning_site_is_linked_to_canonical_project_surfaces(self) -> None:
        for relative in ("../VISION_STATE.md", "../docs/MILESTONES.md", "../docs/ARCHITECTURE.md", "CURRICULUM.md"):
            self.assertIn(relative, self.audit.local_assets)


class FieldManualTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (LEARNING / "index.html").read_text(encoding="utf-8")
        self.js = (LEARNING / "app.js").read_text(encoding="utf-8")
        self.data_text = (LEARNING / "eval_data.js").read_text(encoding="utf-8")

    def test_eval_data_loads_before_app(self) -> None:
        self.assertIn('src="eval_data.js"', self.html)
        self.assertLess(
            self.html.index('src="eval_data.js"'),
            self.html.index('src="app.js"'),
        )

    def test_eval_data_is_a_valid_generated_payload(self) -> None:
        self.assertTrue(self.data_text.startswith("// Generated by"))
        body = self.data_text[self.data_text.index("{"): self.data_text.rindex("}") + 1]
        payload = json.loads(body)
        self.assertGreater(len(payload["failures"]), 5)
        self.assertEqual(len(payload["teach_back"]), 5)
        self.assertGreater(payload["waterfall"]["total_ms"], 0)

    def test_quiz_covers_network_and_recovery_boundaries(self) -> None:
        self.assertIn('name="q4"', self.html)
        self.assertIn('name="q5"', self.html)
        self.assertIn("5 / 5", self.js)

    def test_manual_section_is_wired_into_navigation(self) -> None:
        self.assertIn('href="#manual"', self.html)
        self.assertIn('id="manual"', self.html)


if __name__ == "__main__":
    unittest.main()
