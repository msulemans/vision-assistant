from __future__ import annotations

import json
import unittest

from vision_assistant.manifest import (
    APP_VERSION,
    PYTHON_FLOOR,
    build_manifest,
    licences_markdown,
    model_entries,
    sha256_file,
    size_forecast,
    verify_models,
)
from vision_assistant.profiles import (
    DEFAULT_PROFILE,
    PROFILES,
    default_profile,
    get_profile,
    profile_summaries,
)


def _fake_pin(tmp_root):
    """A tiny fake pinned model directory with real hashes."""
    from tests.test_package_cli import make_fake_pin_dir

    return make_fake_pin_dir(tmp_root)


class ProfilesTest(unittest.TestCase):
    def test_registry_is_frozen_and_honest(self) -> None:
        names = [profile.name for profile in PROFILES]
        self.assertEqual(names, ["inspect", "balanced", "quality"])
        self.assertEqual(DEFAULT_PROFILE, "balanced")
        self.assertEqual(default_profile().name, "balanced")
        measured = [p for p in PROFILES if p.status == "measured"]
        self.assertEqual({p.name for p in measured}, {"inspect", "balanced"})
        for profile in measured:
            self.assertEqual(profile.model_candidate, "qwen3.5-4b")
            self.assertLess(profile.measured["rss_gib"], profile.memory_target_gib)

    def test_quality_is_planned_and_unpinned(self) -> None:
        quality = get_profile("quality")
        self.assertEqual(quality.status, "planned")
        self.assertIsNone(quality.model_candidate)
        self.assertEqual(quality.measured, {})

    def test_unknown_profile_raises(self) -> None:
        with self.assertRaises(ValueError):
            get_profile("nope")

    def test_summaries_are_serializable(self) -> None:
        payload = json.dumps(profile_summaries(), sort_keys=True)
        self.assertIn('"name": "balanced"', payload)


class ManifestTest(unittest.TestCase):
    def test_manifest_from_fake_pin_is_complete(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            pin_dir = _fake_pin(Path(raw))
            manifest = build_manifest(pin_dir=pin_dir)
            self.assertEqual(manifest["app_version"], APP_VERSION)
            self.assertEqual(manifest["python_floor"], PYTHON_FLOOR)
            self.assertEqual(len(manifest["models"]), 2)
            for entry in manifest["models"]:
                self.assertTrue(entry["name"])
                self.assertTrue(entry["licence"])
                self.assertTrue(entry["sha256"] and entry["sha256"] != "to-pin")
            self.assertEqual(len(manifest["profiles"]), 3)
            self.assertTrue(any("MIT" == item["licence"] for item in manifest["runtime"]))
            text = licences_markdown(manifest)
            self.assertIn("Apache-2.0", text)
            self.assertIn("MIT", text)

    def test_registry_fallback_when_no_pin(self) -> None:
        entries = model_entries(None)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["sha256"], "to-pin")

    def test_verify_models_size_and_hash_modes(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            pin_dir = _fake_pin(Path(raw))
            size = verify_models(pin_dir, mode="size")
            self.assertTrue(size["ok"])
            full = verify_models(pin_dir, mode="hash")
            self.assertTrue(full["ok"])
            self.assertTrue(all(entry["sha_ok"] for entry in full["files"]))

            # Tamper: flip one byte of the model file (same size).
            model_file = pin_dir / "model.gguf"
            data = bytearray(model_file.read_bytes())
            data[0] ^= 0xFF
            model_file.write_bytes(bytes(data))
            # Size mode cannot see same-size corruption by design...
            self.assertTrue(verify_models(pin_dir, mode="size")["ok"])
            # ...hash mode must.
            tampered_hash = verify_models(pin_dir, mode="hash")
            self.assertFalse(tampered_hash["ok"])
            self.assertIn(False, [entry["sha_ok"] for entry in tampered_hash["files"]])

    def test_verify_models_missing_pin(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            report = verify_models(Path(raw) / "nowhere", mode="size")
            self.assertFalse(report["ok"])
            self.assertEqual(report["reason"], "no_pin")

    def test_forecast_matches_pin(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            pin_dir = _fake_pin(Path(raw))
            forecast = size_forecast(pin_dir=pin_dir)
            total = sum(entry["bytes"] for entry in forecast["models"])
            self.assertEqual(forecast["download"]["bytes"], total)
            self.assertGreater(forecast["on_disk"]["bytes"], forecast["download"]["bytes"])
            self.assertEqual(set(forecast["ram_targets_gib"]), {"inspect", "balanced", "quality"})

    def test_sha256_file_round_trip(self) -> None:
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "blob"
            path.write_bytes(b"vision")
            self.assertEqual(sha256_file(path), hashlib.sha256(b"vision").hexdigest())


if __name__ == "__main__":
    unittest.main()
