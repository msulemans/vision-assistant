from __future__ import annotations

import base64
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

from .corpus import CorpusCase
from .corpus_cli import FROZEN as FROZEN_CORPUS
from .ports import LabelledAnswer
from .runtime_llamacpp import _STATEMENT_RE

# llama-server runs the model once and handles each request over HTTP, so the
# model stays resident and the response streams. This measures a real first-token
# latency, unlike the one-shot `llama-mtmd-cli` path.
HEALTH = "/health"
COMPLETIONS = "/v1/chat/completions"


def build_prompt(question: str) -> str:
    return f"{FROZEN_CORPUS['prompt']}\n\nQuestion: {question}"


def parse_answer(text: str) -> LabelledAnswer:
    buckets: dict[str, list[str]] = {"visible": [], "inferred": [], "unknown": []}
    for line in text.splitlines():
        match = _STATEMENT_RE.match(line.strip())
        if not match:
            continue
        label, body = match.group(1).lower(), match.group(2).strip()
        buckets[label].append(body)
    if not any(buckets.values()) and text.strip():
        buckets["visible"].append(text.strip())
    return LabelledAnswer(
        visible=tuple(buckets["visible"]),
        inferred=tuple(buckets["inferred"]),
        unknown=tuple(buckets["unknown"]),
    )


def _http_request(url: str, payload: dict, timeout_s: float) -> Iterable[str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        for raw in response:
            yield raw.decode("utf-8", "replace")


def _consume_sse(lines: Iterable[str], started_ns: int) -> tuple[str, float, float]:
    """Consume streaming SSE lines, returning (text, first_token_ms, complete_ms)."""
    full = ""
    first_ms: float | None = None
    last_ms: float | None = None
    for raw in lines:
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        now_ns = time.monotonic_ns()
        try:
            data = json.loads(payload)
            delta = (data.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
        except (json.JSONDecodeError, IndexError, AttributeError):
            continue
        if delta:
            if first_ms is None:
                first_ms = (now_ns - started_ns) / 1_000_000
            full += delta
            last_ms = (now_ns - started_ns) / 1_000_000
    if first_ms is None:
        first_ms = last_ms if last_ms is not None else 0.0
    if last_ms is None:
        last_ms = first_ms
    return full, first_ms, last_ms


class LlamaServerAdapter:
    """Runs `llama-server` once (model resident) and streams answers over HTTP."""

    def __init__(
        self,
        model_path: Path,
        mmproj_path: Path,
        *,
        host: str = "127.0.0.1",
        port: int = 8080,
        executable: str = "llama-server",
        max_tokens: int = 256,
        seed: int = 42,
        timeout_s: float = 120.0,
        transport: Callable[[str, dict, float], Iterable[str]] = _http_request,
        runner: object = subprocess.Popen,
        monotonic_ns: object = time.monotonic_ns,
    ) -> None:
        self.model_path = Path(model_path)
        self.mmproj_path = Path(mmproj_path)
        self.host = host
        self.port = port
        self.executable = executable
        self.max_tokens = max_tokens
        self.seed = seed
        self.timeout_s = timeout_s
        self._transport = transport
        self._runner = runner
        self._monotonic_ns = monotonic_ns
        self._process: object | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, *, wait_s: float = 60.0) -> None:
        if self._process is not None:
            return
        self._process = self._runner(
            [
                self.executable,
                "-m", str(self.model_path),
                "--mmproj", str(self.mmproj_path),
                "--host", self.host,
                "--port", str(self.port),
                "--no-webui",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/opt/homebrew/bin", "LC_ALL": "C"},
        )
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.base_url}{HEALTH}", timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.5)
        raise RuntimeError(f"llama-server did not become healthy on {self.base_url}")

    def stop(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()  # type: ignore[union-attr]
            self._process.wait(timeout=5)  # type: ignore[union-attr]
        except Exception:
            try:
                self._process.kill()  # type: ignore[union-attr]
            except Exception:
                pass
        self._process = None

    def predict(self, case: CorpusCase) -> tuple[LabelledAnswer, dict]:
        if case.fixture.path is None or not case.fixture.path.exists():
            case.fixture.path.parent.mkdir(parents=True, exist_ok=True)
            case.fixture.path.write_bytes(case.fixture.png_bytes)
        data_uri = "data:image/png;base64," + base64.b64encode(case.fixture.png_bytes).decode("ascii")
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_prompt(case.question)},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "seed": self.seed,
            "stream": True,
        }
        started = self._monotonic_ns()
        lines = self._transport(f"{self.base_url}{COMPLETIONS}", payload, self.timeout_s)
        text, first_ms, complete_ms = _consume_sse(lines, started)
        # The transport may stream lines lazily in the caller's generator; if it
        # returned a pre-built iterable the timing snapshot above is best-effort.
        answer = parse_answer(text)
        return answer, {"first_token_ms": first_ms, "complete_ms": complete_ms, "raw": text}
