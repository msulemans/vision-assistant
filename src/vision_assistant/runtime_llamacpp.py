from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .corpus import CorpusCase
from .corpus_cli import FROZEN as FROZEN_CORPUS
from .ports import LabelledAnswer

# A statement like "[visible] A dialog titled ... ", "VISIBLE: ...", or
# "inferred - the cause is ...". The separator may be a space, colon, dot, or dash.
_STATEMENT_RE = re.compile(r"^\s*\[?(visible|inferred|unknown)\]?\s*[:.\-]?\s*(.+?)\s*$", re.IGNORECASE)


def build_prompt(question: str) -> str:
    base = FROZEN_CORPUS["prompt"]
    return f"{base}\n\nQuestion: {question}"


def parse_answer(text: str) -> LabelledAnswer:
    """Bucket the model's labelled answer into visible/inferred/unknown.

    A statement begins at a labelled line and continues across subsequent
    unlabelled lines: models commonly quote multi-line UI text underneath a
    single label, and dropping those lines would lose the verbatim quote.
    """
    buckets: dict[str, list[str]] = {"visible": [], "inferred": [], "unknown": []}
    current: tuple[list[str], int] | None = None
    for line in text.splitlines():
        match = _STATEMENT_RE.match(line.strip())
        if match:
            label, body = match.group(1).lower(), match.group(2).strip()
            buckets[label].append(body)
            current = (buckets[label], len(buckets[label]) - 1)
            continue
        stripped = line.strip()
        if current is not None and stripped:
            bucket, index = current
            bucket[index] = f"{bucket[index]} {stripped}".strip()
    # If the model never used labels, treat the non-empty text as one visible
    # statement so the scorer still evaluates it (and likely flags it).
    if not any(buckets.values()) and text.strip():
        buckets["visible"].append(text.strip())
    return LabelledAnswer(
        visible=tuple(buckets["visible"]),
        inferred=tuple(buckets["inferred"]),
        unknown=tuple(buckets["unknown"]),
    )


class LlamaCppAdapter:
    """Runs the frozen Qwen3.5-4B GGUF via `llama-mtmd-cli` for one case.

    The invocation uses a fixed argv list (no shell), a minimal environment, and
    a bounded generation. The CLI does not stream in this mode, so per the
    metric contract first-token latency equals complete-answer latency.
    """

    def __init__(
        self,
        model_path: Path,
        mmproj_path: Path,
        *,
        executable: str = "llama-mtmd-cli",
        max_tokens: int = 256,
        seed: int = 42,
        timeout_s: float = 120.0,
        runner: object = subprocess.run,
        monotonic_ns: object = time.monotonic_ns,
    ) -> None:
        self.model_path = Path(model_path)
        self.mmproj_path = Path(mmproj_path)
        self.executable = executable
        self.max_tokens = max_tokens
        self.seed = seed
        self.timeout_s = timeout_s
        self._runner = runner
        self._monotonic_ns = monotonic_ns

    def predict(self, case: CorpusCase) -> tuple[LabelledAnswer, dict]:
        if case.fixture.path is None or not case.fixture.path.exists():
            # Re-generate the fixture so an image path always exists.
            case.fixture.path.parent.mkdir(parents=True, exist_ok=True)
            case.fixture.path.write_bytes(case.fixture.png_bytes)
        argv = [
            self.executable,
            "-m", str(self.model_path),
            "--mmproj", str(self.mmproj_path),
            "--image", str(case.fixture.path),
            "-p", build_prompt(case.question),
            "-n", str(self.max_tokens),
            "--temp", "0",
            "--seed", str(self.seed),
        ]
        started = self._monotonic_ns()
        result = self._runner(
            argv,
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/opt/homebrew/bin", "LC_ALL": "C"},
        )
        elapsed_ms = (self._monotonic_ns() - started) / 1_000_000
        stderr = (result.stderr or "").lower()
        if result.returncode != 0:
            raise RuntimeError(f"llama-mtmd-cli failed ({result.returncode}): {stderr[:200] or result.stdout[:200]}")
        answer = parse_answer(result.stdout or "")
        return answer, {"first_token_ms": elapsed_ms, "complete_ms": elapsed_ms, "raw": result.stdout or ""}
