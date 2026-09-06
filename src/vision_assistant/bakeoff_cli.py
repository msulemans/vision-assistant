from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path


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
            held_cases = [c for c in build_corpus(out_dir) if c.split == "heldout"]
            adapter = LlamaCppAdapter(pin_dir / model["name"], pin_dir / mmproj["name"])
            result = run_candidate(candidate, adapter.predict, held_cases)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    parser.error("choose --plan, --verify, or --real")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
