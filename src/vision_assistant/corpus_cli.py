from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .corpus import CorpusCase, build_corpus, manifest
from .ports import LabelledAnswer
from .scorer import aggregate, score

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "runs" / "m004-corpus"

# Frozen evaluation configuration for the M004 corpus (locked before any model
# is downloaded). M005 must not change these without a new version and reruns.
#
# v1.1 (M005, development-data-driven; thresholds and ceilings unchanged):
#   - require verbatim on-screen quoting (the UI-string metric is exact match)
#   - require an [unknown] statement when the requested cause is not visible
#   - cap the answer at 3 statements to cut verbosity (complete-answer p95)
# The held-out split was inspected under v1.0, so it is no longer clean for a
# final promotion claim; a fresh held-out set is required before promoting.
FROZEN = {
    "schema_version": "1.0",
    "config_version": "1.1",
    "corpus_size": 48,
    "dev_cases": 24,
    "heldout_cases": 24,
    "image": {"max_width": 8192, "max_height": 8192, "max_pixels": 40_000_000},
    "image_tokens": {"policy": "internal artifact reference; no raw pixels in trace"},
    "prompt": (
        "You are reading one user-selected screenshot. Answer the question in "
        "at most 3 statements, each labelled [visible], [inferred], or "
        "[unknown].\n"
        "Copy every on-screen string exactly as shown, character for "
        "character (labels, values, numbers, error codes, status phrases); "
        "never reword, paraphrase, or round a shown string.\n"
        "[visible]: only what the screenshot plainly shows.\n"
        "[inferred]: only a cause that is strongly supported by the visible "
        "evidence; if you are not sure, do not use [inferred].\n"
        "[unknown]: what the screenshot does not establish.\n"
        "If the screenshot does not show the requested cause or answer, your "
        "reply MUST include an [unknown] statement saying it is not visible, "
        "and you must not guess a cause."
    ),
    "answer_schema": {"visible": "list[str]", "inferred": "list[str]", "unknown": "list[str]"},
    "decoding": {"max_tokens": 256, "deadline_s": 30},
    "thresholds": {
        "required_fact_recall": 0.90,
        "unsupported_claim_rate": 0.05,
        "forbidden_claims": 0,
        "ui_string_match": 0.90,
        "abstain_heldout_correct": 1.0,
    },
    "ceilings": {
        "balanced_active_rss_gib": 8.0,
        "quality_active_rss_gib": 14.0,
        "swap_growth_mib": 256,
        "acquisition_gib": 25,
        "cold_readiness_s": 60,
        "first_token_p95_s": 5,
        "complete_answer_p95_s": 20,
        "cancel_to_idle_s": 2,
    },
    "promotion": "Promote the smallest configuration meeting all frozen "
    "thresholds on the held-out set; public benchmarks nominate only, they do "
    "not promote.",
}


def _is_abstain(case: CorpusCase) -> bool:
    return case.category == "insufficient_evidence" or not case.required_facts


def gold_answer(case: CorpusCase) -> LabelledAnswer:
    """A hand-authored answer that should pass every case metric."""
    if _is_abstain(case):
        return LabelledAnswer(visible=tuple(case.ui_strings), inferred=(), unknown=(case.uncertainty,))
    seen: list[str] = []
    for s in (*case.required_facts, *case.ui_strings):
        if s not in seen:
            seen.append(s)
    return LabelledAnswer(visible=tuple(seen), inferred=(), unknown=(case.uncertainty,))


def bad_answer(case: CorpusCase) -> LabelledAnswer:
    """A confidently wrong answer that the scorer must flag."""
    if _is_abstain(case):
        return LabelledAnswer(visible=("The screen shows an error",), inferred=(), unknown=())
    forbidden = case.forbidden_claims[0] if case.forbidden_claims else "The root cause is visible"
    return LabelledAnswer(visible=(forbidden,), inferred=(), unknown=())


def write_corpus(out_dir: Path) -> tuple[Path, Path]:
    cases = build_corpus(out_dir)
    manifest_path = out_dir / "corpus-manifest.json"
    manifest_path.write_text(json.dumps(manifest(cases), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    frozen_path = out_dir / "frozen-config.json"
    frozen_path.write_text(json.dumps(FROZEN, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return manifest_path, frozen_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Milestone 004 frozen screen-understanding corpus")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="directory for generated fixtures + manifest")
    parser.add_argument("--freeze", action="store_true", help="generate fixtures, manifest, and frozen config")
    parser.add_argument("--verify", action="store_true", help="determinism + scorer self-test and aggregate")
    args = parser.parse_args(argv)

    if args.freeze:
        manifest_path, frozen_path = write_corpus(args.corpus)
        print(f"manifest={manifest_path}")
        print(f"frozen-config={frozen_path}")
        cases = build_corpus()
        print(f"cases={len(cases)} dev={sum(1 for c in cases if c.split == 'dev')} heldout={sum(1 for c in cases if c.split == 'heldout')}")

    if args.verify:
        cases = build_corpus()
        # Determinism: rebuild and compare manifest bytes.
        m1 = json.dumps(manifest(cases), ensure_ascii=False, sort_keys=True).encode("utf-8")
        m2 = json.dumps(manifest(build_corpus()), ensure_ascii=False, sort_keys=True).encode("utf-8")
        deterministic = hashlib.sha256(m1).hexdigest() == hashlib.sha256(m2).hexdigest()

        # Scorer sanity: every gold answer passes; every bad answer fails.
        gold_scores = [score(c, gold_answer(c)) for c in cases]
        bad_scores = [score(c, bad_answer(c)) for c in cases]
        gold_failures = [s["case_id"] for s in gold_scores if not s["pass"]]
        bad_passes = [s["case_id"] for s in bad_scores if s["pass"]]

        agg = aggregate(gold_scores)

        print(f"deterministic={deterministic}")
        print(f"gold_pass={len(gold_scores) - len(gold_failures)}/{len(gold_scores)} bad_fail={len(bad_scores) - len(bad_passes)}/{len(bad_scores)}")
        print(json.dumps(agg, sort_keys=True))
        ok = deterministic and not gold_failures and not bad_passes
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1

    if not args.freeze and not args.verify:
        parser.error("choose --freeze and/or --verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
