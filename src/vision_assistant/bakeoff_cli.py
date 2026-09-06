from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bakeoff import (
    FROZEN_BAKEOFF,
    Candidate,
    bad_adapter,
    gold_adapter,
    promote,
    run_candidate,
)
from .corpus import build_corpus
from .corpus_cli import FROZEN

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "runs" / "m005-bakeoff"

# Placeholder registry for the intended real bake-off. Revisions/hashes/sizes
# are `"to-pin"` or placeholders until each artifact is actually acquired; the
# M005 record stays open until every row is pinned and measured.
REAL_CANDIDATES: list[Candidate] = [
    Candidate(
        name="qwen3.5-4b",
        family="qwen",
        params_b=4.0,
        licence="Apache-2.0",
        quantization="to-pin",
        revision="to-pin",
        sha256="to-pin",
        runtime_kind="llama.cpp",
        artifact_size_mib=0,
        cold_readiness_ms=0,
        rss_gib=0,
        swap_mib=0,
        acquisition_gib=0,
        first_token_ms=0,
        complete_ms=0,
    ),
    Candidate(
        name="second-4b",
        family="second-4b-class",
        params_b=4.0,
        licence="to-pin",
        quantization="to-pin",
        revision="to-pin",
        sha256="to-pin",
        runtime_kind="llama.cpp",
        artifact_size_mib=0,
        cold_readiness_ms=0,
        rss_gib=0,
        swap_mib=0,
        acquisition_gib=0,
        first_token_ms=0,
        complete_ms=0,
    ),
    Candidate(
        name="9b-quality-control",
        family="quality-control",
        params_b=9.0,
        licence="to-pin",
        quantization="to-pin",
        revision="to-pin",
        sha256="to-pin",
        runtime_kind="llama.cpp",
        artifact_size_mib=0,
        cold_readiness_ms=0,
        rss_gib=0,
        swap_mib=0,
        acquisition_gib=0,
        first_token_ms=0,
        complete_ms=0,
    ),
]


def _fake_candidates() -> tuple[list[Candidate], dict[str, object]]:
    """Deterministic harness proof: fake candidates, no real model."""
    gold = gold_adapter()
    bad = bad_adapter()
    fakes = [
        Candidate("gold-mini", "probe", 1.0, "Apache-2.0", "q4", "fake", "fake", "fake", 2000.0, 30000.0, 4.0, 100.0, 12.0, 1200.0, 8000.0),
        Candidate("gold-large", "probe", 4.0, "Apache-2.0", "q4", "fake", "fake", "fake", 6000.0, 50000.0, 7.0, 200.0, 20.0, 2500.0, 14000.0),
        Candidate("bad-tiny", "probe", 0.5, "Apache-2.0", "q4", "fake", "fake", "fake", 1000.0, 20000.0, 3.0, 80.0, 8.0, 800.0, 5000.0),
    ]
    adapters = {"gold-mini": gold, "gold-large": gold, "bad-tiny": bad}
    return fakes, adapters  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone 005 local VLM and runtime bake-off")
    parser.add_argument("--plan", action="store_true", help="print the frozen bake-off contract and candidate registry")
    parser.add_argument("--verify", action="store_true", help="run the deterministic harness self-check with fake candidates")
    args = parser.parse_args(argv)

    if args.plan:
        print(json.dumps(FROZEN_BAKEOFF, ensure_ascii=False, sort_keys=True))
        print(json.dumps([r.__dict__ for r in REAL_CANDIDATES], ensure_ascii=False, sort_keys=True))
        return 0

    if args.verify:
        held_cases = [c for c in build_corpus() if c.split == "heldout"]
        fakes, adapters = _fake_candidates()
        results = [run_candidate(c, adapters[c.name], held_cases) for c in fakes]
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

    parser.error("choose --plan and/or --verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
