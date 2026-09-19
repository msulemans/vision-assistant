from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from vision_assistant import package_cli
from vision_assistant.package_cli import audit_offline, doctor_report

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_fake_pin_dir(root: Path) -> Path:
    """A tiny fake pinned model directory with real hashes."""
    pin_dir = root / "models-qwen"
    pin_dir.mkdir(parents=True, exist_ok=True)
    model = pin_dir / "model.gguf"
    model.write_bytes(b"MODEL" * 100)
    mmproj = pin_dir / "mmproj.gguf"
    mmproj.write_bytes(b"MMPROJ" * 50)

    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    pin = {
        "candidate": "qwen3.5-4b",
        "repo": "unsloth/Qwen3.5-4B-GGUF",
        "licence": "Apache-2.0",
        "files": [
            {"name": "model.gguf", "role": "model", "bytes": model.stat().st_size,
             "sha256": sha(model), "revision": "main"},
            {"name": "mmproj.gguf", "role": "mmproj", "bytes": mmproj.stat().st_size,
             "sha256": sha(mmproj), "revision": "main"},
        ],
    }
    (pin_dir / "pin.json").write_text(json.dumps(pin), encoding="utf-8")
    return pin_dir


def run_cli(*argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = package_cli.main(list(argv))
    return code, buffer.getvalue()


class TempWorkspaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.pin_dir = make_fake_pin_dir(self.root)

    def build_bundle(self, name: str = "bundle", version: str | None = None) -> Path:
        bundle = self.root / name
        argv = ["build", "--out", str(bundle), "--pin-dir", str(self.pin_dir)]
        if version:
            argv += ["--version", version]
        code, output = run_cli(*argv)
        self.assertEqual(code, 0, output)
        return bundle


class BuildVerifyTest(TempWorkspaceTest):
    def test_build_creates_self_contained_bundle(self) -> None:
        bundle = self.build_bundle()
        for relative in (
            "VERSION", "manifest.json", "integrity.json", "LICENCES.md",
            "README-INSTALL.md", "install.sh",
            "src/vision_assistant/package_cli.py", "src/vision_assistant/profiles.py",
            "tools/ax_action.swift", "tools/practice_window.swift",
        ):
            self.assertTrue((bundle / relative).is_file(), relative)
        self.assertTrue(os.access(bundle / "install.sh", os.X_OK))
        self.assertEqual((bundle / "VERSION").read_text().strip(), "0.1.0")
        manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertEqual(len(manifest["models"]), 2)
        self.assertEqual([p["name"] for p in manifest["profiles"]], ["inspect", "balanced", "quality"])

    def test_build_refuses_existing_bundle_without_force(self) -> None:
        self.build_bundle()
        code, output = run_cli(
            "build", "--out", str(self.root / "bundle"), "--pin-dir", str(self.pin_dir)
        )
        self.assertEqual(code, 1)
        self.assertIn("exists", output)
        code, _ = run_cli(
            "build", "--out", str(self.root / "bundle"), "--pin-dir", str(self.pin_dir), "--force"
        )
        self.assertEqual(code, 0)

    def test_verify_passes_then_fails_on_tamper(self) -> None:
        bundle = self.build_bundle()
        code, output = run_cli("verify", "--bundle", str(bundle))
        self.assertEqual(code, 0, output)
        report = json.loads(output)
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["offline_audit"]["ok"])

        target = bundle / "src" / "vision_assistant" / "profiles.py"
        target.write_text(target.read_text() + "\n# tampered\n", encoding="utf-8")
        code, output = run_cli("verify", "--bundle", str(bundle))
        self.assertEqual(code, 1)
        report = json.loads(output)
        self.assertTrue(any(m["path"].endswith("profiles.py") for m in report["mismatches"]))


class OfflineAuditTest(unittest.TestCase):
    def test_real_repo_passes_the_frozen_audit(self) -> None:
        self.assertEqual(audit_offline(REPO_ROOT / "src" / "vision_assistant"), [])

    def test_planted_violations_are_caught(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw)
            (src / "bad.py").write_text(
                "import urllib.request\nURL = 'https://example.com/model'\nHOST = '0.0.0.0'\n"
                'CMD = ["curl", "-L"]\n',
                encoding="utf-8",
            )
            (src / "acquire.py").write_text("URL = 'https://huggingface.co/x'\nCMD = 'curl'\n", encoding="utf-8")
            (src / "runtime_llamaserver.py").write_text(
                "import urllib.request\nBASE = f'http://{host}:{port}'\n", encoding="utf-8"
            )
            (src / "ui_server.py").write_text(
                "URL = f'http://127.0.0.1:{port}'\nOTHER = 'http://localhost:1'\n", encoding="utf-8"
            )
            rules = {violation["rule"] for violation in audit_offline(src)}
            self.assertEqual(rules, {"network_client_import", "external_url", "wildcard_bind", "download_command"})
            files = {violation["file"] for violation in audit_offline(src)}
            self.assertEqual(files, {"bad.py"})


class InstallLifecycleTest(TempWorkspaceTest):
    def test_install_upgrade_rollback_history(self) -> None:
        bundle_v1 = self.build_bundle("bundle-v1", version="0.1.0")
        bundle_v2 = self.build_bundle("bundle-v2", version="0.1.1")
        prefix = self.root / "prefix"

        code, output = run_cli("install", "--bundle", str(bundle_v1), "--prefix", str(prefix))
        self.assertEqual(code, 0, output)
        self.assertTrue((prefix / "versions" / "0.1.0").is_dir())
        self.assertEqual(os.readlink(prefix / "current"), "versions/0.1.0")
        wrapper = prefix / "bin" / "vision"
        self.assertTrue(os.access(wrapper, os.X_OK))
        history = json.loads((prefix / "install.json").read_text())["entries"]
        self.assertEqual(history[-1]["action"], "install")

        code, output = run_cli("install", "--bundle", str(bundle_v2), "--prefix", str(prefix))
        self.assertEqual(code, 0, output)
        self.assertEqual(os.readlink(prefix / "current"), "versions/0.1.1")
        history = json.loads((prefix / "install.json").read_text())["entries"]
        self.assertEqual(history[-1]["action"], "upgrade")
        self.assertEqual(history[-1]["previous"], "0.1.0")

        code, output = run_cli("rollback", "--prefix", str(prefix))
        self.assertEqual(code, 0, output)
        self.assertEqual(os.readlink(prefix / "current"), "versions/0.1.0")

        code, output = run_cli("rollback", "--prefix", str(prefix))
        self.assertEqual(code, 0, output)
        self.assertEqual(os.readlink(prefix / "current"), "versions/0.1.1")

        code, output = run_cli("versions", "--prefix", str(prefix))
        self.assertEqual(code, 0)
        report = json.loads(output)
        self.assertEqual(report["current"], "0.1.1")
        self.assertEqual(report["installed"], ["0.1.0", "0.1.1"])

    def test_reinstall_without_force_fails(self) -> None:
        bundle = self.build_bundle()
        prefix = self.root / "prefix"
        run_cli("install", "--bundle", str(bundle), "--prefix", str(prefix))
        code, output = run_cli("install", "--bundle", str(bundle), "--prefix", str(prefix))
        self.assertEqual(code, 1)
        self.assertIn("already installed", output)

    def test_rollback_without_previous_fails(self) -> None:
        bundle = self.build_bundle()
        prefix = self.root / "prefix"
        run_cli("install", "--bundle", str(bundle), "--prefix", str(prefix))
        code, output = run_cli("rollback", "--prefix", str(prefix))
        self.assertEqual(code, 1)
        self.assertIn("no previous version", output)


class UninstallTest(TempWorkspaceTest):
    def _install_with_local_state(self) -> Path:
        bundle = self.build_bundle()
        prefix = self.root / "prefix"
        run_cli("install", "--bundle", str(bundle), "--prefix", str(prefix))
        (prefix / "models" / "qwen3.5-4b").mkdir(parents=True)
        (prefix / "models" / "qwen3.5-4b" / "model.gguf").write_bytes(b"x" * 32)
        (prefix / "captures").mkdir()
        (prefix / "captures" / "note.txt").write_text("kept by default")
        return prefix

    def test_dry_run_changes_nothing(self) -> None:
        prefix = self._install_with_local_state()
        code, output = run_cli("uninstall", "--prefix", str(prefix))
        self.assertEqual(code, 0)
        self.assertIn("dry_run", output)
        self.assertTrue((prefix / "versions").is_dir())
        self.assertTrue((prefix / "models").is_dir())

    def test_apply_keeps_models_and_captures_by_default(self) -> None:
        prefix = self._install_with_local_state()
        code, output = run_cli("uninstall", "--prefix", str(prefix), "--apply")
        self.assertEqual(code, 0, output)
        self.assertFalse((prefix / "versions").exists())
        self.assertFalse((prefix / "current").is_symlink())
        self.assertFalse((prefix / "bin").exists())
        self.assertTrue((prefix / "models").is_dir())
        self.assertTrue((prefix / "captures").is_dir())
        history = json.loads((prefix / "install.json").read_text())["entries"]
        self.assertEqual(history[-1]["action"], "uninstall")

    def test_explicit_flags_delete_models_and_captures(self) -> None:
        prefix = self._install_with_local_state()
        code, _ = run_cli(
            "uninstall", "--prefix", str(prefix), "--apply", "--remove-models", "--remove-captures"
        )
        self.assertEqual(code, 0)
        self.assertFalse((prefix / "models").exists())
        self.assertFalse((prefix / "captures").exists())


class DoctorTest(TempWorkspaceTest):
    FAKE_PROBES = {
        "python_version": "3.9.6",
        "python_ok": True,
        "swiftc": "/usr/bin/swiftc",
        "llama_server": {"path": "/opt/homebrew/bin/llama-server", "version": "build 10621"},
        "screencapture": "/usr/sbin/screencapture",
        "accessibility": {"trusted": False},
    }

    def test_report_shape_and_education(self) -> None:
        report = doctor_report(models_dir=self.pin_dir, probes=self.FAKE_PROBES)
        self.assertTrue(report["models"]["ok"])
        self.assertEqual(report["models"]["reason"], "ok")
        capabilities = [entry["capability"] for entry in report["permissions"]]
        self.assertEqual(len(capabilities), 3)
        for entry in report["permissions"]:
            self.assertTrue(entry["revoke"])
            self.assertTrue(entry["default"])
        self.assertIn("Accessibility", json.dumps(report["permissions"]))

    def test_missing_models_reported_with_hint(self) -> None:
        report = doctor_report(models_dir=self.root / "nowhere", probes=self.FAKE_PROBES)
        self.assertFalse(report["models"]["ok"])
        self.assertEqual(report["models"]["reason"], "not_found")
        self.assertIn("hint", report["models"])

    def test_json_mode_via_cli(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = package_cli.main(
                ["doctor", "--models-dir", str(self.pin_dir), "--json"]
            )
        self.assertEqual(code, 0)
        report = json.loads(buffer.getvalue())
        self.assertIn("probes", report)


class SmokeDeterministicTest(TempWorkspaceTest):
    def test_smoke_passes_with_fake_models_in_repo_layout(self) -> None:
        out = self.root / "m015"
        code, output = run_cli(
            "smoke", "--models-dir", str(self.pin_dir), "--out-dir", str(out)
        )
        self.assertEqual(code, 0, output)
        self.assertIn("offline audit: ok", output)
        files = list(out.glob("m015-smoke-*.json"))
        self.assertEqual(len(files), 1)
        report = json.loads(files[0].read_text())
        self.assertTrue(report["passed"])
        self.assertTrue(report["checks"]["offline_audit"])
        self.assertTrue(report["checks"]["grounding_gate"])
        self.assertIsNone(report["model_smoke"])

    def test_smoke_fails_without_models(self) -> None:
        out = self.root / "m015"
        code, output = run_cli(
            "smoke", "--models-dir", str(self.root / "nowhere"), "--out-dir", str(out)
        )
        self.assertEqual(code, 1)
        self.assertIn("not_found", output)

    def test_forecast_cli(self) -> None:
        code, output = run_cli("forecast", "--pin-dir", str(self.pin_dir))
        self.assertEqual(code, 0)
        self.assertIn("download", output)
        code, output = run_cli("forecast", "--pin-dir", str(self.pin_dir), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertGreater(payload["download"]["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
