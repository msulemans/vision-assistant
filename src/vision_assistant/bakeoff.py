from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol, Tuple, Union, runtime_checkable

from .corpus import CorpusCase
from .ports import LabelledAnswer
from .scorer import aggregate, score

# Frozen M005 bake-off contract. This is locked before any model or runtime is
# downloaded; M005 may not revise it without a new evaluation version and a
# comparable rerun (per docs/METRICS.md "Frozen bake-off rules").
FROZEN_BAKEOFF = {
    "schema_version": "1.0",
    "candidate_rule": (
        "Compare one Apache-2.0 4B unified VLM hypothesis (initially Qwen3.5-4B), "
        "one second 4B-class architecture, portable llama.cpp vs Apple mlx-vlm; "
        "add a <=9B quality control only if both small candidates miss the gate. "
        "Ollama may be a convenience adapter, not the architecture."
    ),
    "runtime_matrix": [
        {"kind": "llama.cpp", "binaries": ["llama-mtmd-cli", "llama-server"], "note": "portable; per-model multimodal projector"},
        {"kind": "mlx-vlm", "binaries": [], "note": "Apple-specific performance treatment; not installed yet"},
        {"kind": "ollama", "binaries": ["ollama"], "note": "convenience adapter only; must verify real vision input"},
    ],
    "image": {
        "width": 480,
        "height": 300,
        "resize": "none (fixtures are frozen at 480x300)",
        "token_policy": "internal artifact reference; no raw pixels in trace",
    },
    "trial_counts": {"warm": 48, "cold": 3},
    "measurement": {
        "quality": "score each held-out case once for quality",
        "latency_schedule": "one excluded warm-up + 48 warm trials, fixed category-balanced schedule (two per held-out case)",
        "p95_method": "nearest-rank",
        "rss": "process-tree RSS sampling; shared-memory caveats recorded",
        "cpu_energy": "report diagnostics; numerical gate only after a reproducible baseline",
    },
    "promotion": (
        "Promote the smallest configuration meeting all frozen thresholds on the "
        "held-out set; tie-break by artifact size, then complete-answer p95. "
        "Public benchmarks nominate only, they do not promote."
    ),
    # Held-out score thresholds (must match the frozen corpus contract).
    "thresholds": {
        "required_fact_recall": 0.9,
        "unsupported_claim_rate": 0.05,
        "forbidden_claims": 0,
        "ui_string_match": 0.9,
        "abstain_heldout_correct": 1.0,
        "held_out_pass_rate": 1.0,
    },
    "ceilings": {
        "first_token_p95_ms": 5000,
        "complete_answer_p95_ms": 20000,
        "cold_readiness_ms": 60000,
        "balanced_active_rss_gib": 8.0,
        "quality_active_rss_gib": 14.0,
        "swap_growth_mib": 256,
        "acquisition_gib": 25,
    },
}


@dataclass(frozen=True)
class Candidate:
    """One frozen candidate to compare on the held-out corpus.

    Revisions/hashes are `"to-pin"` until the artifact is actually acquired; the
    bake-off record is invalid until every candidate pins them. Resource fields
    are `None` until they are actually profiled.
    """

    name: str
    family: str
    params_b: float
    licence: str
    quantization: str
    revision: str
    sha256: str
    runtime_kind: str
    artifact_size_mib: float
    first_token_ms: float
    complete_ms: float
    cold_readiness_ms: float | None = None
    rss_gib: float | None = None
    swap_mib: float | None = None
    acquisition_gib: float | None = None


AnswerFn = Callable[[CorpusCase], Union[LabelledAnswer, Tuple[LabelledAnswer, dict]]]


@runtime_checkable
class ModelAdapter(Protocol):
    def predict(self, case: CorpusCase) -> LabelledAnswer: ...


def _p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def run_candidate(
    candidate: Candidate,
    answer_fn: AnswerFn,
    held_cases: list[CorpusCase],
    progress: Callable[[int, str, str], None] | None = None,
) -> dict:
    """Run one candidate across every held-out case and grade it.

    *answer_fn* produces either a `LabelledAnswer` or a
    `(LabelledAnswer, timings)` tuple; the harness reads measured timings when
    provided and otherwise falls back to the candidate's frozen baselines.
    *progress* (if given) is called with (index, case_id, category) before each
    case so a live run can show it advancing.
    """
    per_case: list[dict] = []
    first_list: list[float] = []
    complete_list: list[float] = []
    for index, case in enumerate(held_cases):
        if progress is not None:
            progress(index, case.case_id, case.category)
        result = answer_fn(case)
        answer, timings = (result if isinstance(result, tuple) and len(result) == 2 else (result, None))
        per_case.append(score(case, answer))
        first_list.append(timings.get("first_token_ms", candidate.first_token_ms) if timings else candidate.first_token_ms)
        complete_list.append(timings.get("complete_ms", candidate.complete_ms) if timings else candidate.complete_ms)

    agg = aggregate(per_case)
    first_p95 = _p95(first_list)
    complete_p95 = _p95(complete_list)

    thresholds = FROZEN_BAKEOFF["thresholds"]
    ceilings = FROZEN_BAKEOFF["ceilings"]
    quality = (
        agg["passes_heldout"] == len(held_cases)
        and agg["required_fact_recall_heldout"] >= thresholds["required_fact_recall"]
        and agg["unsupported_claim_rate_heldout"] <= thresholds["unsupported_claim_rate"]
        and agg["forbidden_claims_heldout"] == thresholds["forbidden_claims"]
        and agg["ui_string_match"] >= thresholds["ui_string_match"]
        and agg["abstain_heldout_correct"] >= thresholds["abstain_heldout_correct"]
    )
    measured = [
        (candidate.cold_readiness_ms, ceilings["cold_readiness_ms"]),
        (candidate.rss_gib, ceilings["balanced_active_rss_gib"]),
        (candidate.swap_mib, ceilings["swap_growth_mib"]),
        (candidate.acquisition_gib, ceilings["acquisition_gib"]),
    ]
    measured = [(value, ceil) for value, ceil in measured if value is not None]
    resource_ok = all(value <= ceil for value, ceil in measured)
    resource_measured = len(measured)
    resource = first_p95 <= ceilings["first_token_p95_ms"] and complete_p95 <= ceilings["complete_answer_p95_ms"]
    pass_thresholds = quality and resource_ok and resource

    return {
        "candidate": candidate.name,
        "family": candidate.family,
        "params_b": candidate.params_b,
        "licence": candidate.licence,
        "quantization": candidate.quantization,
        "revision": candidate.revision,
        "sha256": candidate.sha256,
        "runtime_kind": candidate.runtime_kind,
        "artifact_size_mib": candidate.artifact_size_mib,
        "required_fact_recall": agg["required_fact_recall_heldout"],
        "unsupported_claim_rate": agg["unsupported_claim_rate_heldout"],
        "forbidden_claims": agg["forbidden_claims_heldout"],
        "ui_string_match": agg["ui_string_match"],
        "abstain_heldout_correct": agg["abstain_heldout_correct"],
        "passes_heldout": agg["passes_heldout"],
        "first_token_p95_ms": first_p95,
        "complete_answer_p95_ms": complete_p95,
        "cold_readiness_ms": candidate.cold_readiness_ms,
        "rss_gib": candidate.rss_gib,
        "swap_mib": candidate.swap_mib,
        "acquisition_gib": candidate.acquisition_gib,
        "resource_measured": resource_measured,
        "quality_ok": quality,
        "resource_ok": resource_ok,
        "resource_timing_ok": resource,
        "pass_thresholds": pass_thresholds,
        "per_case": [
            {
                "case_id": row["case_id"],
                "category": row["category"],
                "pass": row["pass"],
                "required_fact_recall": row["required_fact_recall"],
                "unsupported_claim_rate": row["unsupported_claim_rate"],
                "forbidden_claims": row["forbidden_claim_count"],
                "ui_string_match": row["ui_string_match"],
                "abstain_correct": row["abstain_correct"],
            }
            for row in per_case
        ],
    }


def promote(results: list[dict]) -> str | None:
    """Return the name of the smallest passing candidate, or None.

    Tie-break: smaller artifact size, then lower complete-answer p95.
    """
    passing = [r for r in results if r["pass_thresholds"]]
    if not passing:
        return None
    passing.sort(key=lambda r: (r["params_b"], r["artifact_size_mib"], r["complete_answer_p95_ms"]))
    return passing[0]["candidate"]


# Convenience baseline candidates for the deterministic harness self-test.
# These are NOT real models; they prove the harness and promotion rule work.
def gold_adapter() -> AnswerFn:
    from .corpus_cli import gold_answer

    return gold_answer


def bad_adapter() -> AnswerFn:
    from .corpus_cli import bad_answer

    return bad_answer
