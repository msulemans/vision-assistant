"""Local macOS Vision OCR adapter (M007).

Compiles `tools/vision_ocr.swift` once into a cached helper binary (no new
packages, no TCC permission) and turns its JSON output into `EvidenceFact`
records with pixel regions. Raw OCR text may enter a model prompt but never
traces: callers use `EvidenceReport.summary` for anything recorded.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .evidence import KIND_OCR, EvidenceFact, EvidenceReport

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOL_DIR = REPO_ROOT / "runs" / "m007-tools"
DEFAULT_HELPER_SOURCE = REPO_ROOT / "tools" / "vision_ocr.swift"
ADAPTER_NAME = "vision-ocr-apple"


class OcrUnavailable(RuntimeError):
    """OCR could not run (no toolchain, build failure, or helper error)."""


class VisionOcrAdapter:
    def __init__(
        self,
        *,
        tool_dir: Path | None = None,
        helper_source: Path | None = None,
        workdir: Path | None = None,
        timeout_s: float = 20.0,
        compile_timeout_s: float = 120.0,
    ) -> None:
        self.tool_dir = Path(tool_dir) if tool_dir is not None else DEFAULT_TOOL_DIR
        self.helper_source = (
            Path(helper_source) if helper_source is not None else DEFAULT_HELPER_SOURCE
        )
        self.workdir = Path(workdir) if workdir is not None else None
        self.timeout_s = timeout_s
        self.compile_timeout_s = compile_timeout_s
        self._helper: Path | None = None

    @property
    def helper_path(self) -> Path:
        return self.tool_dir / "vision_ocr"

    def ensure_helper(self) -> Path:
        if self._helper is not None:
            return self._helper
        if self.helper_path.is_file() and os.access(self.helper_path, os.X_OK):
            self._helper = self.helper_path
            return self._helper
        swiftc = shutil.which("swiftc") or "/usr/bin/swiftc"
        if not Path(swiftc).exists():
            raise OcrUnavailable("swiftc not found; install Xcode command line tools")
        if not self.helper_source.is_file():
            raise OcrUnavailable(f"helper source not found at {self.helper_source}")
        self.tool_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [swiftc, "-O", str(self.helper_source), "-o", str(self.helper_path)],
                capture_output=True,
                timeout=self.compile_timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrUnavailable("timed out compiling the vision_ocr helper") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()[-300:]
            raise OcrUnavailable(f"vision_ocr build failed: {detail}")
        self._helper = self.helper_path
        return self._helper

    def collect(self, png_bytes: bytes) -> EvidenceReport:
        helper = self.ensure_helper()
        started = time.monotonic()
        if self.workdir is not None:
            self.workdir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(suffix=".png", dir=self.workdir)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(png_bytes)
            try:
                result = subprocess.run(
                    [str(helper), str(temp_path)],
                    capture_output=True,
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                raise OcrUnavailable(f"vision_ocr timed out after {self.timeout_s}s") from exc
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", "replace").strip()[-200:]
                raise OcrUnavailable(f"vision_ocr exited {result.returncode}: {detail}")
            try:
                rows = json.loads(result.stdout.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise OcrUnavailable("vision_ocr produced invalid JSON") from exc
        finally:
            temp_path.unlink(missing_ok=True)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return EvidenceReport(
            adapter=ADAPTER_NAME,
            facts=self._facts_from_rows(rows),
            elapsed_ms=round(elapsed_ms, 3),
        )

    @staticmethod
    def _facts_from_rows(rows: object) -> tuple[EvidenceFact, ...]:
        if not isinstance(rows, list):
            raise OcrUnavailable("vision_ocr output must be a JSON array")
        facts: list[EvidenceFact] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = row.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                region = (
                    int(row["x"]),
                    int(row["y"]),
                    int(row["w"]),
                    int(row["h"]),
                )
                confidence = float(row["confidence"])
            except (KeyError, TypeError, ValueError):
                continue
            facts.append(
                EvidenceFact(
                    fact_id=f"ocr-{len(facts) + 1}",
                    kind=KIND_OCR,
                    text=text,
                    region=region,
                    source=ADAPTER_NAME,
                    confidence=confidence,
                )
            )
        return tuple(facts)
