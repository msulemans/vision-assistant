"""M007 measurement: does OCR evidence improve the frozen difficult subset?

Runs the pinned model twice per case — the frozen question alone, then the
same question with local Vision OCR facts appended — and scores both with the
frozen scorer. Synthetic fixtures only; never user screenshots.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIN_DIR = REPO_ROOT / "models" / "qwen3.5-4b"
FROZEN_SUBSET = (
    "m004-dialog-14",
    "m004-small_text-13",
    "m004-small_text-14",
    "m004-small_text-15",
)
CONDITIONS = ("baseline", "ocr")


def select_cases(cases, *, case_ids=None, heldout_all: bool = False):
    if heldout_all:
        selected = [case for case in cases if case.split == "heldout"]
        if not selected:
            raise SystemExit("no held-out cases found")
        return selected
    wanted = tuple(case_ids) if case_ids else FROZEN_SUBSET
    by_id = {case.case_id: case for case in cases}
    missing = [case_id for case_id in wanted if case_id not in by_id]
    if missing:
        raise SystemExit(f"unknown case ids: {', '.join(missing)}")
    return [by_id[case_id] for case_id in wanted]


def summarize(rows: list[dict]) -> dict:
    summary: dict = {"cases": len(rows)}
    for condition in CONDITIONS:
        scores = [row[condition] for row in rows]
        summary[condition] = {
            "passes": sum(1 for s in scores if s["pass"]),
            "ui_string_match_mean": round(
                sum(s["ui_string_match"] for s in scores) / len(scores), 4
            ),
            "required_fact_recall_mean": round(
                sum(s["required_fact_recall"] for s in scores) / len(scores), 4
            ),
            "unsupported_claim_rate_mean": round(
                sum(s["unsupported_claim_rate"] for s in scores) / len(scores), 4
            ),
            "forbidden_claim_total": sum(s["forbidden_claim_count"] for s in scores),
            "abstain_correct": sum(1 for s in scores if s["abstain_correct"]),
        }
    return summary


def evaluate(rows: list[dict]) -> dict:
    """Frozen gate reading: improvement without guard regressions or new claims."""
    baseline = {row["case_id"]: row["baseline"] for row in rows}
    augmented = {row["case_id"]: row["ocr"] for row in rows}
    regressions = [
        case_id
        for case_id in augmented
        if case_id.startswith("m004-small_text")
        and augmented[case_id]["pass"] < baseline[case_id]["pass"]
    ]
    return {
        "baseline_passes": sum(1 for s in baseline.values() if s["pass"]),
        "ocr_passes": sum(1 for s in augmented.values() if s["pass"]),
        "dialog14_baseline_pass": baseline.get("m004-dialog-14", {}).get("pass"),
        "dialog14_ocr_pass": augmented.get("m004-dialog-14", {}).get("pass"),
        "small_text_regressions": regressions,
        "unsupported_rate_sum": {
            "baseline": round(
                sum(s["unsupported_claim_rate"] for s in baseline.values()), 4
            ),
            "ocr": round(sum(s["unsupported_claim_rate"] for s in augmented.values()), 4),
        },
        "forbidden_claim_total": sum(
            s["forbidden_claim_count"] for s in (*baseline.values(), *augmented.values())
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M007 evidence-augmentation measurement")
    parser.add_argument(
        "--cases", default=None, help="comma-separated case ids (default: the frozen subset)"
    )
    parser.add_argument(
        "--heldout-all", action="store_true", help="run every held-out case instead"
    )
    parser.add_argument("--pin-dir", type=Path, default=DEFAULT_PIN_DIR)
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--out", type=Path, default=None, help="result JSON path")
    args = parser.parse_args(argv)

    case_ids = [item.strip() for item in args.cases.split(",")] if args.cases else None

    from .assistant import gather_evidence
    from .corpus import build_corpus
    from .evidence import facts_to_prompt
    from .ocr_vision import OcrUnavailable, VisionOcrAdapter
    from .runtime_llamaserver import LlamaServerAdapter
    from .scorer import score

    print("building the frozen corpus in memory...")
    cases = select_cases(build_corpus(), case_ids=case_ids, heldout_all=args.heldout_all)

    pin_path = args.pin_dir / "pin.json"
    if not pin_path.exists():
        print(json.dumps({"status": "failed", "reason": f"no pin at {pin_path}"}))
        return 1
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    model = next(f for f in pin["files"] if f["role"] == "model")
    mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")

    evidence_port = VisionOcrAdapter()
    adapter = LlamaServerAdapter(
        args.pin_dir / model["name"],
        args.pin_dir / mmproj["name"],
        ctx_size=args.ctx_size,
        jinja=True,
        chat_template_kwargs={"enable_thinking": False},
        log_path=REPO_ROOT / "runs" / "m007-server.log",
    )
    run_id = f"m007-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    out_path = args.out or REPO_ROOT / "runs" / "m007" / f"subset-{run_id}.json"

    rows: list[dict] = []
    try:
        adapter.start()
        started = time.monotonic()
        for case in cases:
            png_bytes = case.fixture.png_bytes

            t0 = time.monotonic()
            base_answer, _ = adapter.predict_image(png_bytes, case.question)
            base_ms = (time.monotonic() - t0) * 1000.0
            base_score = score(case, base_answer)

            report = gather_evidence(png_bytes, evidence_port)
            block = facts_to_prompt(report)
            prompt = f"{case.question}\n\n{block}" if block else case.question
            t0 = time.monotonic()
            aug_answer, _ = adapter.predict_image(png_bytes, prompt)
            aug_ms = (time.monotonic() - t0) * 1000.0
            aug_score = score(case, aug_answer)

            rows.append(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "ocr_facts": len(report.facts),
                    "baseline": base_score,
                    "ocr": aug_score,
                    "timing_ms": {"baseline": round(base_ms, 1), "ocr": round(aug_ms, 1)},
                    "answers": {
                        "baseline": {
                            "visible": list(base_answer.visible),
                            "inferred": list(base_answer.inferred),
                            "unknown": list(base_answer.unknown),
                        },
                        "ocr": {
                            "visible": list(aug_answer.visible),
                            "inferred": list(aug_answer.inferred),
                            "unknown": list(aug_answer.unknown),
                        },
                    },
                }
            )
            print(
                f"{case.case_id:24s} base={'PASS' if base_score['pass'] else 'FAIL'}"
                f" ui={base_score['ui_string_match']:.2f}"
                f"  ->  ocr={'PASS' if aug_score['pass'] else 'FAIL'}"
                f" ui={aug_score['ui_string_match']:.2f}"
                f"  (facts={len(report.facts)}, {aug_ms:.0f} ms)"
            )
        total_ms = (time.monotonic() - started) * 1000.0
    except OcrUnavailable as exc:
        print(json.dumps({"status": "failed", "stage": "ocr", "reason": str(exc)}))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "run_id": run_id}))
        return 130
    finally:
        adapter.stop()

    result = {
        "run_id": run_id,
        "config": {
            "candidate": "qwen3.5-4b",
            "ctx_size": args.ctx_size,
            "evidence": "vision-ocr-apple, zoom x2, literal",
            "cases": [case.case_id for case in cases],
        },
        "rows": rows,
        "summary": summarize(rows),
        "gate": evaluate(rows),
        "total_ms": round(total_ms, 1),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nsummary: {json.dumps(result['summary'], sort_keys=True)}")
    print(f"gate: {json.dumps(result['gate'], sort_keys=True)}")
    print(f"result: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
