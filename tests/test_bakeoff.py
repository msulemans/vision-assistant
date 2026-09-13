from __future__ import annotations

import unittest

from vision_assistant.bakeoff import (
    FROZEN_BAKEOFF,
    Candidate,
    _p95,
    bad_adapter,
    gold_adapter,
    promote,
    run_candidate,
)
from vision_assistant.corpus import build_corpus


def _fake(name: str, params_b: float, size_mib: float, first_ms: float, complete_ms: float) -> Candidate:
    return Candidate(
        name=name,
        family="probe",
        params_b=params_b,
        licence="Apache-2.0",
        quantization="q4",
        revision="fake",
        sha256="fake",
        runtime_kind="fake",
        artifact_size_mib=size_mib,
        cold_readiness_ms=30000.0,
        rss_gib=4.0,
        swap_mib=100.0,
        acquisition_gib=12.0,
        first_token_ms=first_ms,
        complete_ms=complete_ms,
    )


class BakeoffHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.held = [c for c in build_corpus() if c.split == "heldout"]
        self.gold = gold_adapter()
        self.bad = bad_adapter()

    def test_frozen_contract_is_locked(self) -> None:
        self.assertEqual(FROZEN_BAKEOFF["schema_version"], "1.0")
        self.assertIn("candidate_rule", FROZEN_BAKEOFF)
        self.assertIn("promotion", FROZEN_BAKEOFF)
        kinds = {r["kind"] for r in FROZEN_BAKEOFF["runtime_matrix"]}
        self.assertTrue({"llama.cpp", "mlx-vlm", "ollama"}.issubset(kinds))
        self.assertIn("cold_readiness_ms", FROZEN_BAKEOFF["ceilings"])
        self.assertIn("balanced_active_rss_gib", FROZEN_BAKEOFF["ceilings"])

    def test_gold_candidates_pass_and_mini_wins(self) -> None:
        mini = run_candidate(_fake("gold-mini", 1.0, 2000, 1200, 8000), self.gold, self.held)
        large = run_candidate(_fake("gold-large", 4.0, 6000, 2500, 14000), self.gold, self.held)
        promoted = promote([large, mini])
        self.assertTrue(mini["pass_thresholds"])
        self.assertTrue(large["pass_thresholds"])
        self.assertEqual(promoted, "gold-mini")

    def test_bad_candidate_fails_the_gate(self) -> None:
        bad = run_candidate(_fake("bad-tiny", 0.5, 1000, 800, 5000), self.bad, self.held)
        self.assertFalse(bad["pass_thresholds"])
        self.assertFalse(bad["quality_ok"])
        self.assertGreater(bad["forbidden_claims"], 0)

    def test_nearest_rank_p95(self) -> None:
        data = list(range(1, 21))  # 20 values, 95th percentile = 19
        self.assertEqual(_p95(data), 19.0)
        self.assertEqual(_p95([]), 0.0)

    def test_parse_answer_buckets_labels(self) -> None:
        from vision_assistant.runtime_llamacpp import parse_answer

        text = (
            "[visible] A dialog titled CONNECT TO DATABASE is visible.\n"
            "[inferred] A password may be needed.\n"
            "[unknown] The cause is not visible."
        )
        answer = parse_answer(text)
        self.assertEqual(answer.visible, ("A dialog titled CONNECT TO DATABASE is visible.",))
        self.assertEqual(answer.inferred, ("A password may be needed.",))
        self.assertEqual(answer.unknown, ("The cause is not visible.",))

    def test_acquire_candidate_is_pinned(self) -> None:
        from vision_assistant.acquire import CANDIDATE

        self.assertEqual(CANDIDATE["candidate"], "qwen3.5-4b")
        self.assertEqual(CANDIDATE["licence"], "Apache-2.0")
        self.assertEqual(len(CANDIDATE["files"]), 2)
        self.assertTrue(all(f["sha256"] == "to-pin" for f in CANDIDATE["files"]))

    def test_acquire_registry_has_a_second_candidate(self) -> None:
        from vision_assistant.acquire import CANDIDATES

        self.assertEqual(sorted(CANDIDATES), ["gemma-3-4b", "qwen3-vl-8b", "qwen3.5-4b"])
        gemma = CANDIDATES["gemma-3-4b"]
        self.assertEqual(gemma["repo"], "unsloth/gemma-3-4b-it-GGUF")
        self.assertEqual(gemma["family"], "gemma")
        self.assertEqual([f["role"] for f in gemma["files"]], ["model", "mmproj"])
        self.assertTrue(all(f["sha256"] == "to-pin" for f in gemma["files"]))

        control = CANDIDATES["qwen3-vl-8b"]
        self.assertEqual(control["licence"], "Apache-2.0")
        self.assertEqual(control["params_b"], 8.0)
        self.assertEqual([f["role"] for f in control["files"]], ["model", "mmproj"])
        self.assertTrue(all(f["sha256"] == "to-pin" for f in control["files"]))

    def test_sse_consume_measures_and_joins_tokens(self) -> None:
        import time

        from vision_assistant.runtime_llamaserver import _consume_sse

        lines = [
            'data: {"choices":[{"delta":{"content":"[visible] CONNECT "}}]}',
            'data: {"choices":[{"delta":{"content":"TO DATABASE."}}]}',
            "data: [DONE]",
        ]
        text, first_ms, complete_ms = _consume_sse(lines, time.monotonic_ns())
        self.assertIn("CONNECT TO DATABASE.", text)
        self.assertGreaterEqual(first_ms, 0.0)
        self.assertGreaterEqual(complete_ms, first_ms)

    def test_sse_consume_excludes_reasoning_from_answer(self) -> None:
        import time

        from vision_assistant.runtime_llamaserver import _consume_sse

        lines = [
            "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\" - Visible: CPU 78%\\n\"}}]}",
            "data: {\"choices\":[{\"delta\":{\"content\":\"[visible] CPU usage of 78%\"}}]}",
            "data: [DONE]",
        ]
        text, first_ms, complete_ms = _consume_sse(lines, time.monotonic_ns())
        # The chain-of-thought must not leak into the scored answer...
        self.assertNotIn(" - Visible: CPU 78%", text)
        self.assertIn("CPU usage of 78%", text)
        # ...but it still counts toward the first-token (responsiveness) latency.
        self.assertGreaterEqual(first_ms, 0.0)
        self.assertGreaterEqual(complete_ms, first_ms)

    def test_server_adapter_parses_streamed_answer(self) -> None:
        import tempfile
        from pathlib import Path

        from vision_assistant.corpus import build_corpus
        from vision_assistant.runtime_llamaserver import LlamaServerAdapter

        with tempfile.TemporaryDirectory() as tmp:
            case = [c for c in build_corpus(Path(tmp)) if c.split == "heldout"][0]
            lines = ['data: {"choices":[{"delta":{"content":"[visible] CONNECT TO DATABASE is visible."}}]}', "data: [DONE]"]
            adapter = LlamaServerAdapter(
                Path("models/x"), Path("models/y"), transport=lambda url, payload, timeout: lines
            )
            answer, timings = adapter.predict(case)
            self.assertTrue(answer.visible)
            self.assertIn("CONNECT TO DATABASE", answer.visible[0])

    def test_parse_answer_keeps_continuation_lines(self) -> None:
        from vision_assistant.runtime_llamacpp import parse_answer

        text = (
            "[visible]: ./APP\n"
            "404 NOT FOUND: /API/STATUS\n"
            "EXIT CODE 1\n"
            "[unknown]: The underlying cause is not visible."
        )
        answer = parse_answer(text)
        self.assertEqual(answer.visible, ("./APP 404 NOT FOUND: /API/STATUS EXIT CODE 1",))
        self.assertEqual(answer.unknown, ("The underlying cause is not visible.",))

    def test_wrapped_quote_scores_ui_match(self) -> None:
        from vision_assistant.corpus import build_corpus
        from vision_assistant.runtime_llamacpp import parse_answer
        from vision_assistant.scorer import score

        case = next(c for c in build_corpus() if c.case_id == "m004-terminal-03")
        text = (
            "[visible] ./APP\n"
            "404 NOT FOUND: /API/STATUS\n"
            "EXIT CODE 1\n"
            "[unknown] The underlying cause is not visible."
        )
        result = score(case, parse_answer(text))
        self.assertEqual(result["ui_string_match"], 1.0)
        self.assertEqual(result["required_fact_recall"], 1.0)
        self.assertTrue(result["pass"])

    def test_multi_string_quote_passes_dialog_and_form(self) -> None:
        from vision_assistant.corpus import build_corpus
        from vision_assistant.runtime_llamacpp import parse_answer
        from vision_assistant.scorer import score

        cases = {c.case_id: c for c in build_corpus()}

        dialog = parse_answer(
            "[visible] CONNECT TO DATABASE; ENTER THE PASSWORD TO CONTINUE\n"
            "[unknown] Whether the user has already entered a password is not visible."
        )
        result = score(cases["m004-dialog-01"], dialog)
        self.assertEqual(result["ui_string_match"], 1.0)
        self.assertTrue(result["pass"])

        form = parse_answer(
            "[visible] PASSWORD; REQUIRED\n"
            "[unknown] Whether the user entered a valid password is not visible."
        )
        result = score(cases["m004-form-01"], form)
        self.assertEqual(result["required_fact_recall"], 1.0)
        self.assertTrue(result["pass"])

    def test_server_argv_includes_jinja_only_when_enabled(self) -> None:
        from pathlib import Path

        from vision_assistant.runtime_llamaserver import LlamaServerAdapter

        plain = LlamaServerAdapter(Path("models/x"), Path("models/y"))
        self.assertNotIn("--jinja", plain._server_argv())
        thinking_off = LlamaServerAdapter(Path("models/x"), Path("models/y"), jinja=True)
        self.assertIn("--jinja", thinking_off._server_argv())

    def test_server_argv_disables_mmproj_offload_only_when_requested(self) -> None:
        from pathlib import Path

        from vision_assistant.runtime_llamaserver import LlamaServerAdapter

        plain = LlamaServerAdapter(Path("models/x"), Path("models/y"))
        self.assertNotIn("--no-mmproj-offload", plain._server_argv())
        cpu_vision = LlamaServerAdapter(Path("models/x"), Path("models/y"), mmproj_offload=False)
        self.assertIn("--no-mmproj-offload", cpu_vision._server_argv())

    def test_server_spawn_kwargs_use_log_file_when_provided(self) -> None:
        import subprocess
        import tempfile
        from pathlib import Path

        from vision_assistant.runtime_llamaserver import LlamaServerAdapter

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "server.log"
            adapter = LlamaServerAdapter(Path("models/x"), Path("models/y"), log_path=log_path)
            adapter._log_handle = log_path.open("w", encoding="utf-8")
            kwargs = adapter._spawn_kwargs()
            self.assertIs(kwargs["stdout"], adapter._log_handle)
            self.assertIs(kwargs["stderr"], adapter._log_handle)
            adapter._log_handle.close()
            adapter._log_handle = None
            kwargs = adapter._spawn_kwargs()
            self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
            self.assertIs(kwargs["stderr"], subprocess.DEVNULL)

    def test_server_adapter_sends_chat_template_kwargs(self) -> None:
        import tempfile
        from pathlib import Path

        from vision_assistant.corpus import build_corpus
        from vision_assistant.runtime_llamaserver import LlamaServerAdapter

        captured: list[dict] = []

        def transport(url, payload, timeout):
            captured.append(payload)
            return ['data: {"choices":[{"delta":{"content":"[visible] OK"}}]}', "data: [DONE]"]

        with tempfile.TemporaryDirectory() as tmp:
            case = [c for c in build_corpus(Path(tmp)) if c.split == "dev"][0]
            thinking_off = LlamaServerAdapter(
                Path("models/x"),
                Path("models/y"),
                chat_template_kwargs={"enable_thinking": False},
                transport=transport,
            )
            thinking_off.predict(case)
            plain = LlamaServerAdapter(Path("models/x"), Path("models/y"), transport=transport)
            plain.predict(case)
        self.assertEqual(captured[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("chat_template_kwargs", captured[1])

    def test_summarize_raw_separates_content_reasoning_and_finish(self) -> None:
        from vision_assistant.bakeoff_cli import _summarize_raw
        raw = (
            'data: {"choices":[{"delta":{"reasoning_content":"thinking hard "}}]}\n'
            'data: {"choices":[{"delta":{"content":"[visible] CPU 78%"}}]}\n'
            'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n'
            "data: [DONE]\n"
        )
        summary = _summarize_raw(raw)
        self.assertIn("CONTENT (17 chars): [visible] CPU 78%", summary)
        self.assertIn("thinking hard", summary)
        self.assertIn("FINISH: length", summary)

    def test_summarize_raw_handles_non_streaming_output(self) -> None:
        from vision_assistant.bakeoff_cli import _summarize_raw

        summary = _summarize_raw("[visible] The app shows ERROR 42.")
        self.assertIn("non-streaming", summary)
        self.assertIn("ERROR 42", summary)

    def test_summarize_raw_reveals_unrecognized_events(self) -> None:
        from vision_assistant.bakeoff_cli import _summarize_raw

        raw = (
            'data: {"error":{"message":"failed to process image","code":400}}\n'
            "data: [DONE]\n"
        )
        summary = _summarize_raw(raw)
        self.assertIn("CONTENT (0 chars)", summary)
        self.assertIn("EVENTS:", summary)
        self.assertIn("failed to process image", summary)


if __name__ == "__main__":
    unittest.main()
