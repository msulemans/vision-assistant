from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def _summarize_raw(raw: str, content_limit: int = 1200) -> str:
    """Summarize a captured model response for diagnosis.

    For streaming SSE captures, separate the labelled answer (`content`) from
    the chain-of-thought (`reasoning_content`) and report the finish reason, so
    an empty answer can be distinguished from an over-abstaining one. For
    non-streaming captures, print the raw text directly.
    """
    if not any(line.strip().startswith("data:") for line in raw.splitlines()):
        return f"RAW (non-streaming, {len(raw)} chars): {raw[:content_limit]}"
    reasoning: list[str] = []
    content: list[str] = []
    finish = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            data = json.loads(payload)
            choice = (data.get("choices") or [{}])[0]
            delta = choice.get("delta", {})
            if delta.get("reasoning_content"):
                reasoning.append(delta["reasoning_content"])
            if delta.get("content"):
                content.append(delta["content"])
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
        except (json.JSONDecodeError, IndexError, AttributeError):
            continue
    joined_content = "".join(content)
    joined_reasoning = "".join(reasoning)
    return (
        f"CONTENT ({len(joined_content)} chars): {joined_content[:content_limit]}\n"
        f"REASONING ({len(joined_reasoning)} chars, tail): ...{joined_reasoning[-300:]}\n"
        f"FINISH: {finish or 'unknown'}"
    )


def _candidate(name, family, params_b, size_mib, first_ms, complete_ms, *, runtime_kind="fake"):
    return {
        "name": name,
        "family": family,
        "params_b": params_b,
        "licence": "Apache-2.0",
        "quantization": "q4",
        "revision": "to-pin",
        "sha256": "to-pin",
        "runtime_kind": runtime_kind,
        "artifact_size_mib": size_mib,
        "first_token_ms": first_ms,
        "complete_ms": complete_ms,
    }


CANDIDATE_MATRIX = [
    _candidate("qwen3.5-4b", "qwen", 4.0, 0, 0, 0, runtime_kind="llama.cpp"),
    _candidate("second-4b", "second-4b-class", 4.0, 0, 0, 0, runtime_kind="llama.cpp"),
    _candidate("9b-quality-control", "quality-control", 9.0, 0, 0, 0, runtime_kind="llama.cpp"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone 005 local VLM and runtime bake-off")
    parser.add_argument("--plan", action="store_true", help="print the frozen bake-off contract and candidate registry")
    parser.add_argument("--verify", action="store_true", help="run the deterministic harness self-check with fake candidates")
    parser.add_argument("--real", action="store_true", help="run a real pinned candidate over the held-out corpus")
    parser.add_argument("--pin-dir", type=Path, help="directory containing pin.json and the GGUF/mmproj files")
    parser.add_argument("--limit", type=int, help="only run the first N held-out cases (smoke test)")
    parser.add_argument("--inspect", type=int, help="dump the raw model output for the first N held-out cases")
    parser.add_argument("--detail", action="store_true", help="print per-case results")
    parser.add_argument("--server", action="store_true", help="use the persistent llama-server adapter (streaming)")
    parser.add_argument("--split", choices=["dev", "heldout"], default="heldout", help="which corpus split to run")
    parser.add_argument("--dump", action="store_true", help="print a raw output summary for failing cases (with --real)")
    parser.add_argument("--max-tokens", type=int, default=1024, help="generation budget for the server adapter")
    parser.add_argument("--no-think", action="store_true", help="disable the model's thinking mode via --jinja + chat_template_kwargs")
    parser.add_argument("--probe-server", action="store_true", help="send one image request and print the raw server response")
    args = parser.parse_args(argv)

    if args.plan:
        from .bakeoff import FROZEN_BAKEOFF

        print(json.dumps(FROZEN_BAKEOFF, ensure_ascii=False, sort_keys=True))
        print(json.dumps(CANDIDATE_MATRIX, ensure_ascii=False, sort_keys=True))
        return 0

    if args.verify:
        from .bakeoff import Candidate, bad_adapter, gold_adapter, promote, run_candidate
        from .corpus import build_corpus

        held_cases = [c for c in build_corpus() if c.split == "heldout"]
        gold = gold_adapter()
        bad = bad_adapter()
        fakes = {
            "gold-mini": (1.0, 2000.0, 1200.0, 8000.0, gold),
            "gold-large": (4.0, 6000.0, 2500.0, 14000.0, gold),
            "bad-tiny": (0.5, 1000.0, 800.0, 5000.0, bad),
        }
        results = []
        for name, (params, size, first, complete, adapter) in fakes.items():
            cand = Candidate(
                name=name, family="probe", params_b=params, licence="Apache-2.0", quantization="q4",
                revision="fake", sha256="fake", runtime_kind="fake", artifact_size_mib=size,
                first_token_ms=first, complete_ms=complete,
            )
            results.append(run_candidate(cand, adapter, held_cases))
        winner = promote(results)
        print(f"heldout_cases={len(held_cases)}")
        for r in results:
            print(
                f"  {r['candidate']:<12} params={r['params_b']:.1f}B pass={r['pass_thresholds']} "
                f"recall={r['required_fact_recall']:.2f} forbidden={r['forbidden_claims']} "
                f"first_p95={r['first_token_p95_ms']:.0f}ms complete_p95={r['complete_answer_p95_ms']:.0f}ms"
            )
        ok = winner == "gold-mini" and all(r["pass_thresholds"] for r in results if r["candidate"] != "bad-tiny")
        print(f"promoted={winner}")
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1

    if args.inspect:
        from .acquire import MODELS_DIR
        from .corpus import build_corpus
        from .runtime_llamacpp import LlamaCppAdapter

        pin_dir = args.pin_dir or MODELS_DIR
        pin_path = pin_dir / "pin.json"
        if not pin_path.exists():
            print(f"no pin at {pin_path}; run `python -m vision_assistant.acquire download` first")
            return 1
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
        model = next((f for f in pin["files"] if f["role"] == "model"), None)
        mmproj = next((f for f in pin["files"] if f["role"] == "mmproj"), None)
        adapter = LlamaCppAdapter(pin_dir / model["name"], pin_dir / mmproj["name"])
        with tempfile.TemporaryDirectory(prefix="vision-assistant-m005-") as tmp:
            held = [c for c in build_corpus(Path(tmp)) if c.split == "heldout"]
            for case in held[: args.inspect]:
                answer, timings = adapter.predict(case)
                print(f"=== {case.case_id} ({case.category}) ===")
                print("RAW:")
                print(timings.get("raw", "")[:1800])
                print("PARSED:")
                print(answer)
        return 0

    if args.probe_server:
        from .acquire import MODELS_DIR
        from .corpus import build_corpus
        from .runtime_llamaserver import LlamaServerAdapter

        pin_dir = args.pin_dir or MODELS_DIR
        pin = json.loads((pin_dir / "pin.json").read_text(encoding="utf-8"))
        model = next(f for f in pin["files"] if f["role"] == "model")
        mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")
        adapter = LlamaServerAdapter(pin_dir / model["name"], pin_dir / mmproj["name"])
        adapter.start()
        try:
            with tempfile.TemporaryDirectory(prefix="vision-assistant-m005-") as tmp:
                case = [c for c in build_corpus(Path(tmp)) if c.split == "dev" and c.category == "dashboard"][0]
                answer, timings = adapter.predict(case)
                print("CASE:", case.case_id, case.category)
                print("RAW RESPONSE:")
                print(timings.get("raw", "")[:3000])
                print("RAW TEXT:")
                print(timings.get("raw", ""))
                print("PARSED:", answer)
                print("TIMINGS:", {k: timings[k] for k in ("first_token_ms", "complete_ms")})
        finally:
            adapter.stop()
        return 0

    if args.real:
        from .acquire import MODELS_DIR
        from .bakeoff import Candidate, run_candidate
        from .corpus import build_corpus
        from .runtime_llamacpp import LlamaCppAdapter

        pin_dir = args.pin_dir or MODELS_DIR
        pin_path = pin_dir / "pin.json"
        if not pin_path.exists():
            print(f"no pin at {pin_path}; run `python -m vision_assistant.acquire download` first")
            return 1
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
        model = next((f for f in pin["files"] if f["role"] == "model"), None)
        mmproj = next((f for f in pin["files"] if f["role"] == "mmproj"), None)
        if not model or not mmproj:
            print("pin.json missing model or mmproj entry")
            return 1

        size_mib = sum(f["bytes"] for f in pin["files"]) / (1024 * 1024)
        candidate = Candidate(
            name=pin["candidate"], family=pin.get("family", "qwen"), params_b=pin["params_b"],
            licence=pin["licence"], quantization=model.get("quantization", "q4_K_M"),
            revision="main", sha256=model["sha256"], runtime_kind="llama.cpp",
            artifact_size_mib=size_mib, first_token_ms=0.0, complete_ms=0.0,
        )

        with tempfile.TemporaryDirectory(prefix="vision-assistant-m005-") as tmp:
            out_dir = Path(tmp)
            held_cases = [c for c in build_corpus(out_dir) if c.split == args.split]
            if args.limit:
                held_cases = held_cases[: args.limit]
            total = len(held_cases)

            def _progress(index: int, case_id: str, category: str) -> None:
                print(f"  [{index + 1}/{total}] {case_id} ({category}) ...", file=sys.stderr, flush=True)

            raws: dict[str, str] = {}

            def _capture(case):
                answer, timings = adapter.predict(case)
                raws[case.case_id] = timings.get("raw", "") if timings else ""
                return answer, timings

            if args.server:
                from .runtime_llamaserver import LlamaServerAdapter

                adapter = LlamaServerAdapter(
                    pin_dir / model["name"],
                    pin_dir / mmproj["name"],
                    max_tokens=args.max_tokens,
                    jinja=args.no_think,
                    chat_template_kwargs={"enable_thinking": False} if args.no_think else None,
                )
                adapter.start()
            else:
                from .runtime_llamacpp import LlamaCppAdapter

                adapter = LlamaCppAdapter(pin_dir / model["name"], pin_dir / mmproj["name"])

            try:
                result = run_candidate(candidate, _capture, held_cases, progress=_progress)
            finally:
                if args.server:
                    adapter.stop()
            if args.dump:
                print("RAW DUMP (failing cases):")
                for row in result["per_case"]:
                    if not row["pass"]:
                        print(f"=== {row['case_id']} ({row['category']}) ===")
                        print(_summarize_raw(raws.get(row["case_id"], "")))
                print("")
            if args.detail:
                print("PER CASE:")
                for row in result["per_case"]:
                    flag = "PASS" if row["pass"] else "fail"
                    print(
                        f"  {row['case_id']:<28} {row['category']:<22} {flag:<5} "
                        f"recall={row['required_fact_recall']:.2f} unsup={row['unsupported_claim_rate']:.2f} "
                        f"ui={row['ui_string_match']:.2f} abstain={row['abstain_correct']}"
                    )
                print("")
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    parser.error("choose --plan, --verify, or --real")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
