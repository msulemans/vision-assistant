"""M015 artifact/licence manifest, size forecast, and model verification.

The manifest is the packaging milestone's honest inventory: which model
files are pinned (name, bytes, sha256, licence, source), which runtimes and
frameworks the product depends on (and under which licences), what the
install costs in disk and memory, and how to verify the local model files
against the pin (size mode for speed, full-hash mode for certainty).

Nothing here touches the network; acquisition stays in `acquire.py` and is
an explicit, one-time, online step.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .acquire import CANDIDATES, DEFAULT_CANDIDATE, source_url
from .profiles import profile_summaries

APP_VERSION = "0.1.0"
PYTHON_FLOOR = "3.9"

CHUNK = 1024 * 1024

RUNTIME_ENTRIES: tuple[dict, ...] = (
    {
        "name": "llama.cpp (llama-server)",
        "licence": "MIT",
        "role": "local inference runtime",
        "redistributed": False,
        "note": "installed separately (e.g. Homebrew); never bundled",
    },
    {
        "name": "Python",
        "licence": "PSF-2.0",
        "role": "host interpreter (stdlib only)",
        "redistributed": False,
    },
    {
        "name": "Apple Vision / AppKit / ApplicationServices",
        "licence": "Apple system frameworks",
        "role": "OCR, overlay, and accessibility helper compilation",
        "redistributed": False,
    },
)

TOOLS_DERIVED: tuple[dict, ...] = (
    {"name": "vision_ocr", "source": "tools/vision_ocr.swift", "note": "compiled on first use (swiftc)"},
    {"name": "ax_dump", "source": "tools/ax_dump.swift", "note": "read-only accessibility snapshot"},
    {"name": "ax_action", "source": "tools/ax_action.swift", "note": "the only action-capable artifact"},
    {"name": "ax_overlay", "source": "tools/ax_overlay.swift", "note": "click-through highlight"},
    {"name": "practice_window", "source": "tools/practice_window.swift", "note": "disposable action target"},
)

# Estimated non-model footprint of an install (stdlib venv + bundle sources).
VENV_ESTIMATE_BYTES = 32 * 1024 * 1024
BUNDLE_ESTIMATE_BYTES = 4 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def model_entries(pin_dir: Path | None = None) -> list[dict]:
    """Pinned model files with licence and source; falls back to the registry."""
    if pin_dir is not None and (Path(pin_dir) / "pin.json").is_file():
        pin = json.loads((Path(pin_dir) / "pin.json").read_text(encoding="utf-8"))
        source = pin.get("repo")
        licence = pin.get("licence", "unknown")
        licence_url = pin.get("licence_url")
    else:
        candidate = CANDIDATES[DEFAULT_CANDIDATE]
        pin = {**candidate}
        source = candidate["repo"]
        licence = candidate["licence"]
        licence_url = candidate.get("licence_url")
    entries = []
    for entry in pin["files"]:
        record = {
            "name": entry["name"],
            "role": entry["role"],
            "bytes": entry["bytes"],
            "sha256": entry.get("sha256", "to-pin"),
            "licence": licence,
            "source": source_url(source) if source else None,
            "revision": entry.get("revision"),
            "redistributed": False,
        }
        if licence_url:
            record["licence_url"] = licence_url
        entries.append(record)
    return entries


def build_manifest(*, pin_dir: Path | None = None) -> dict:
    """The artifact/licence manifest written into every bundle."""
    return {
        "app_version": APP_VERSION,
        "python_floor": PYTHON_FLOOR,
        "profiles": profile_summaries(),
        "models": model_entries(pin_dir),
        "runtime": [dict(entry) for entry in RUNTIME_ENTRIES],
        "tools_derived": [dict(entry) for entry in TOOLS_DERIVED],
    }


def verify_models(pin_dir: Path, *, mode: str = "size") -> dict:
    """Verify local model files against the pin.

    ``mode="size"`` checks presence and byte counts (fast); ``mode="hash"``
    additionally recomputes SHA-256. Unpinned hashes (``to-pin``) are
    reported as unverified rather than treated as failures.
    """
    if mode not in ("size", "hash"):
        raise ValueError(f"unknown verification mode {mode!r}")
    directory = Path(pin_dir)
    pin_path = directory / "pin.json"
    if not pin_path.is_file():
        return {"ok": False, "reason": "no_pin", "directory": str(directory), "files": []}
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    files = []
    ok = True
    for entry in pin["files"]:
        path = directory / entry["name"]
        present = path.is_file()
        size_ok = present and path.stat().st_size == entry["bytes"]
        sha_ok: bool | None = None
        if mode == "hash" and present:
            expected = entry.get("sha256", "to-pin")
            if expected and expected != "to-pin":
                sha_ok = sha256_file(path) == expected
        verified = present and size_ok and (sha_ok is not False)
        ok = ok and verified
        files.append(
            {
                "name": entry["name"],
                "present": present,
                "size_ok": bool(size_ok),
                "sha_ok": sha_ok,
                "verified": bool(verified),
            }
        )
    return {
        "ok": bool(ok),
        "reason": "ok" if ok else "mismatch",
        "mode": mode,
        "directory": str(directory),
        "files": files,
    }


def size_forecast(*, pin_dir: Path | None = None) -> dict:
    """Download, on-disk, and memory figures straight from the pin."""
    models = model_entries(pin_dir)
    download_bytes = sum(entry["bytes"] for entry in models)
    on_disk_bytes = download_bytes + VENV_ESTIMATE_BYTES + BUNDLE_ESTIMATE_BYTES
    return {
        "models": [
            {"name": entry["name"], "role": entry["role"], "bytes": entry["bytes"]}
            for entry in models
        ],
        "download": {
            "bytes": download_bytes,
            "gib": round(download_bytes / (1024**3), 2),
            "note": "one-time, online, explicit (`acquire download`); everything afterwards runs offline",
        },
        "on_disk": {
            "bytes": on_disk_bytes,
            "gib": round(on_disk_bytes / (1024**3), 2),
            "venv_estimate_bytes": VENV_ESTIMATE_BYTES,
            "bundle_estimate_bytes": BUNDLE_ESTIMATE_BYTES,
        },
        "ram_targets_gib": {
            profile["name"]: profile["memory_target_gib"] for profile in profile_summaries()
        },
    }


def licences_markdown(manifest: dict) -> str:
    """LICENCES.md content generated from the manifest."""
    lines = [
        "# Third-party licences and artifacts",
        "",
        f"Bundle version {manifest['app_version']} · Python ≥ {manifest['python_floor']} · stdlib only.",
        "",
        "## Pinned model artifacts (acquired by the user, verified by size and SHA-256)",
        "",
        "| Artifact | Role | Bytes | Licence | Source |",
        "|---|---|---|---|---|",
    ]
    for entry in manifest["models"]:
        lines.append(
            f"| {entry['name']} | {entry['role']} | {entry['bytes']:,} | {entry['licence']} | {entry.get('source') or '—'} |"
        )
    lines += [
        "",
        "## Runtime and framework dependencies (not redistributed)",
        "",
        "| Component | Role | Licence |",
        "|---|---|---|",
    ]
    for entry in manifest["runtime"]:
        lines.append(f"| {entry['name']} | {entry['role']} | {entry['licence']} |")
    lines += [
        "",
        "## Compiler-derived tools (built locally on first use)",
        "",
        "| Tool | Source | Note |",
        "|---|---|---|",
    ]
    for entry in manifest["tools_derived"]:
        lines.append(f"| {entry['name']} | {entry['source']} | {entry['note']} |")
    lines += [
        "",
        "No model weights are redistributed with this bundle; every pinned file is",
        "acquired explicitly by the user and verified against the manifest.",
        "",
    ]
    return "\n".join(lines)
