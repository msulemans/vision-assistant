from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vision_assistant import audit_cli
from vision_assistant.audit import (
    CANARY_FACT,
    CATEGORIES,
    SRC,
    a11y_findings,
    import_violations,
    redaction_findings,
    release_manifest,
    run_audit,
    support_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class AuditGateTest(unittest.TestCase):
    def test_full_audit_zero_critical_failures(self) -> None:
        report = run_audit()
        summary = report["summary"]
        self.assertEqual(summary["critical_failures"], 0, report["findings"])
        self.assertTrue(summary["gate_pass"])
        self.assertGreaterEqual(summary["checks"], 24)

    def test_every_category_reports(self) -> None:
        report = run_audit()
        covered = {finding["category"] for finding in report["findings"]}
        self.assertEqual(covered, set(CATEGORIES))

    def test_no_finding_is_an_unexpected_status(self) -> None:
        for finding in run_audit()["findings"]:
            self.assertIn(finding["status"], {"pass", "fail", "note"})


class RedactionTeethTest(unittest.TestCase):
    def test_planted_canary_fails_the_check(self) -> None:
        findings = redaction_findings(
            f"trace mentioning {CANARY_FACT} in a payload",
            CANARY_FACT,
            released=True,
            leftover_files=0,
        )
        canary = next(f for f in findings if f.check_id == "trace.canary-fact-never-in-trace")
        self.assertEqual(canary.status, "fail")

    def test_planted_pixel_bytes_fail_the_check(self) -> None:
        findings = redaction_findings(
            'payload includes iVBORw0KGgo=', CANARY_FACT, released=True, leftover_files=0
        )
        pixels = next(f for f in findings if f.check_id == "trace.pixels-never-in-trace")
        self.assertEqual(pixels.status, "fail")

    def test_leftover_artifacts_fail_the_check(self) -> None:
        findings = redaction_findings(
            "clean trace", CANARY_FACT, released=False, leftover_files=2
        )
        released = next(f for f in findings if f.check_id == "trace.artifact-released")
        self.assertEqual(released.status, "fail")


class ImportScanTeethTest(unittest.TestCase):
    def test_planted_third_party_import_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw)
            (src / "bad.py").write_text("import numpy\nfrom pandas import DataFrame\n", encoding="utf-8")
            violations = import_violations(src)
            self.assertIn("bad.py:numpy", violations)
            self.assertIn("bad.py:pandas", violations)

    def test_stdlib_and_relative_imports_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw)
            (src / "good.py").write_text(
                "import json\nfrom pathlib import Path\nfrom . import sibling\n", encoding="utf-8"
            )
            self.assertEqual(import_violations(src), [])

    def test_repo_source_is_stdlib_only(self) -> None:
        self.assertEqual(import_violations(SRC), [])


class A11yTeethTest(unittest.TestCase):
    def test_unlabeled_input_is_flagged(self) -> None:
        findings = a11y_findings('<form><input type="text" name="q"></form>')
        labeled = next(f for f in findings if f.check_id == "a11y.all-inputs-labeled")
        self.assertEqual(labeled.status, "fail")

    def test_explicit_and_nested_labels_pass(self) -> None:
        html = (
            '<label for="a">A</label><input id="a">'
            "<label><input type=\"radio\" name=\"r\"></label>"
            '<button aria-label="Go"></button>'
        )
        for finding in a11y_findings(html):
            self.assertEqual(finding.status, "pass", finding.detail)

    def test_unnamed_button_is_flagged(self) -> None:
        findings = a11y_findings("<button></button>")
        named = next(f for f in findings if f.check_id == "a11y.all-buttons-named")
        self.assertEqual(named.status, "fail")


class ReleaseManifestTest(unittest.TestCase):
    def test_manifest_is_deterministic_and_aggregates_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bundle = Path(raw)
            (bundle / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            (bundle / "a.txt").write_text("alpha", encoding="utf-8")
            (bundle / "b.txt").write_text("beta", encoding="utf-8")
            first = release_manifest(bundle)
            second = release_manifest(bundle)
            self.assertEqual(first, second)
            self.assertEqual(first["version"], "9.9.9")
            expected = hashlib.sha256(
                "".join(f"{e['path']}\0{e['sha256']}\n" for e in first["files"]).encode("utf-8")
            ).hexdigest()
            self.assertEqual(first["aggregate_sha256"], expected)
            self.assertIn("known limitation", first["integrity"])

    def test_support_markdown_carries_the_facts(self) -> None:
        text = support_markdown()
        self.assertIn("0.1.0", text)
        self.assertIn("3.14.7", text)
        self.assertIn("Known limitations", text)
        self.assertIn("notarization", text)
        self.assertIn("rollback", text.lower())


class CliTest(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = audit_cli.main(list(argv))
        return code, buffer.getvalue()

    def test_sign_cli_on_a_tiny_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bundle = Path(raw) / "bundle"
            bundle.mkdir()
            (bundle / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            (bundle / "payload.py").write_text("print('x')\n", encoding="utf-8")
            out = Path(raw) / "release.json"
            code, output = self.run_cli("sign", "--bundle", str(bundle), "--out", str(out))
            self.assertEqual(code, 0, output)
            manifest = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "9.9.9")
            self.assertEqual(len(manifest["files"]), 2)

    def test_support_cli_writes_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "SUPPORT.md"
            code, output = self.run_cli("support", "--out", str(out))
            self.assertEqual(code, 0, output)
            self.assertTrue(out.is_file())
            self.assertIn("Known limitations", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
